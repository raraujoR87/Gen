"""Autonomous local paper-trading runner.

For each configured pair (symbol, exchange_buy, exchange_sell), this module
runs two real market-data feeds concurrently (one per exchange), keeps the
Redis order book cache warm, builds the model's real (non-synthetic) input
tensors from the buy-exchange stream, and — once enough history has
accumulated — evaluates the opportunity with the real ML model and the real
risk gate (backend.execution.decision.should_execute). Approved signals are
executed via PaperExchangeClient (simulated fills against real cached
prices, never a real order) and persisted through
backend.db.repository.record_execution. Every evaluation, approved or not,
is recorded into backend.runtime_state.STATE for the local dashboard.

This is the "real data + paper trading" mode the user chose: real market
data drives the model's decision, but no real order is ever sent — see
backend.execution.broken_leg.dispatch_orders (raises NotImplementedError)
for the live path, which this runner never touches.

Signal source: BimodalArbitrageNet (backend.ml.model) is untrained —
random weights, not real intelligence — so the actual decision signal
here comes from backend.ml.heuristic.HeuristicSignalEstimator, a
transparent statistic computed from this pair's own real recent history
(net alpha persistence and price volatility) plus a real order-book
liquidity signal from the buy-side DepthMatrix
(backend.ml.depth_signal.compute_depth_liquidity_hazard) — not a trained
model. Every evaluated tick is also logged
(backend.marketdata.sample_logger) so a real, non-fabricated training set
accumulates for when there's enough of it to actually train the model.
"""
from __future__ import annotations

import asyncio
import logging

from backend.config import (
    PairConfig,
    RunnerConfig,
    get_taker_fee_bps,
    load_runner_config,
)
from backend.db.repository import get_or_create_user_by_email, record_execution
from backend.db.session import AsyncSessionLocal
from backend.execution.alpha import compute_net_alpha
from backend.execution.broken_leg import BrokenLegMitigator
from backend.execution.decision import should_execute
from backend.execution.paper_exchange import PaperExchangeClient
from backend.marketdata.features import DepthMatrixBuilder, TemporalFeatureWindow
from backend.marketdata.microstructure import compute_vwap
from backend.marketdata.orderbook_cache import OrderBookCache
from backend.marketdata.sample_logger import SampleLogger
from backend.marketdata.ws_ingestion import get_default_feed
from backend.ml.depth_signal import compute_depth_liquidity_hazard
from backend.ml.heuristic import HeuristicSignalEstimator
from backend.runtime_state import STATE
from backend.schemas import OrderBookSnapshot, RiskLimits

logger = logging.getLogger(__name__)

# adverse_hazard (from HeuristicSignalEstimator, itself real recent price
# volatility scaled to [0, 1]) above this threshold routes a broken leg to
# immediate market liquidation instead of a re-pegged limit order — see
# BrokenLegMitigator._auto_hedge's high_volatility branch.
_HIGH_VOLATILITY_HAZARD_THRESHOLD = 0.5


class PairMonitor:
    """Runs one (symbol, exchange_buy, exchange_sell) pair end to end."""

    def __init__(
        self,
        pair: PairConfig,
        cache: OrderBookCache,
        config: RunnerConfig,
        user_id,
    ) -> None:
        self.pair = pair
        self._cache = cache
        self._config = config
        self._user_id = user_id
        self._heuristic = HeuristicSignalEstimator()
        self._sample_logger = SampleLogger(config.sample_log_path) if config.sample_logging_enabled else None
        self._client = PaperExchangeClient(cache)
        self._mitigator = BrokenLegMitigator(self._client)

        self._temporal_window = TemporalFeatureWindow()
        self._depth_builder = DepthMatrixBuilder()
        self._daily_notional_used_usd = 0.0
        self._evaluating = asyncio.Lock()

    async def run(self) -> None:
        buy_feed = get_default_feed(self.pair.exchange_buy, self.pair.symbol)
        sell_feed = get_default_feed(self.pair.exchange_sell, self.pair.symbol)
        try:
            await asyncio.gather(
                buy_feed.run(callback=self._on_buy_snapshot),
                sell_feed.run(callback=self._on_sell_snapshot),
            )
        except Exception as exc:
            STATE.record_error(f"{self.pair.symbol} monitor crashed: {exc!r}")
            logger.exception("PairMonitor for %s crashed", self.pair.symbol)
            raise

    async def _on_buy_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        await self._cache.set_snapshot(snapshot)
        self._temporal_window.update(snapshot)
        self._depth_builder.update(snapshot)
        await self._maybe_evaluate()

    async def _on_sell_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        await self._cache.set_snapshot(snapshot)

    async def _maybe_evaluate(self) -> None:
        if not (self._temporal_window.is_ready and self._depth_builder.is_ready):
            return
        if self._evaluating.locked():
            return  # a previous evaluation is still in flight; skip this tick
        async with self._evaluating:
            await self._evaluate_once()

    async def _evaluate_once(self) -> None:
        buy_snapshot = await self._cache.get_snapshot(self.pair.exchange_buy, self.pair.symbol)
        sell_snapshot = await self._cache.get_snapshot(self.pair.exchange_sell, self.pair.symbol)
        if buy_snapshot is None or sell_snapshot is None:
            return
        if not buy_snapshot.asks or not sell_snapshot.bids:
            return

        temporal = self._temporal_window.to_temporal_features()
        depth = self._depth_builder.to_depth_matrix()
        if temporal is None or depth is None:
            return

        best_ask_price = buy_snapshot.asks[0].price
        quantity = self._config.notional_per_trade_usd / best_ask_price

        try:
            vwap_ask_a = compute_vwap(buy_snapshot.asks, quantity)
            vwap_bid_b = compute_vwap(sell_snapshot.bids, quantity)
        except ValueError:
            # Not enough resting depth on one side to fill this quantity.
            return

        tau_a = get_taker_fee_bps(self.pair.exchange_buy, self._config.default_taker_fee_bps) / 10_000
        tau_b = get_taker_fee_bps(self.pair.exchange_sell, self._config.default_taker_fee_bps) / 10_000
        try:
            net_alpha = compute_net_alpha(
                vwap_bid_b=vwap_bid_b,
                tau_b=tau_b,
                vwap_ask_a=vwap_ask_a,
                tau_a=tau_a,
                slippage_est=0.0005,
                transfer_cost=0.0,
                capital_usd=self._config.notional_per_trade_usd,
            )
        except ValueError:
            return
        net_alpha_bps = net_alpha * 1e4

        if self._sample_logger is not None:
            await asyncio.to_thread(
                self._sample_logger.log,
                symbol=self.pair.symbol,
                exchange_buy=self.pair.exchange_buy,
                exchange_sell=self.pair.exchange_sell,
                temporal=temporal,
                depth=depth,
                net_alpha_bps=net_alpha_bps,
            )

        mid_price_return = temporal.window[-1][0]  # most recent tick's first feature
        # Real depth-based liquidity risk: how much of the buy-side book's
        # resting near-touch liquidity our own order would consume. Uses
        # `depth` (the buy-exchange DepthMatrix), which was already being
        # computed every tick but previously only ever logged, never fed
        # into the decision itself.
        liquidity_hazard = compute_depth_liquidity_hazard(depth, quantity, side="ask")
        signal = self._heuristic.update(
            net_alpha_bps=net_alpha_bps,
            mid_price_return=mid_price_return,
            depth_liquidity_hazard=liquidity_hazard,
        )

        limits = STATE.kill_switch.apply(RiskLimits())
        approved, reason = should_execute(
            net_alpha_bps=net_alpha_bps,
            signal=signal,
            limits=limits,
            trade_notional_usd=self._config.notional_per_trade_usd,
            daily_notional_used_usd=self._daily_notional_used_usd,
        )

        record = STATE.record_signal(
            symbol=self.pair.symbol,
            exchange_buy=self.pair.exchange_buy,
            exchange_sell=self.pair.exchange_sell,
            net_alpha_bps=net_alpha_bps,
            execution_probability=signal.execution_probability,
            adverse_hazard=signal.adverse_hazard,
            approved=approved,
            reason=reason,
        )

        if not approved:
            return

        high_volatility = signal.adverse_hazard > _HIGH_VOLATILITY_HAZARD_THRESHOLD
        result = await self._mitigator.execute_paired_orders(
            buy_exchange=self.pair.exchange_buy,
            sell_exchange=self.pair.exchange_sell,
            symbol=self.pair.symbol,
            amount=quantity,
            buy_price=vwap_ask_a,
            sell_price=vwap_bid_b,
            gross_spread_pct=(vwap_bid_b - vwap_ask_a) / vwap_ask_a,
            net_spread_pct=net_alpha,
            ml_confidence_score=signal.execution_probability,
            high_volatility=high_volatility,
        )

        record.execution_status = result.status.value
        record.realized_pnl_usd = result.realized_pnl_usd
        self._daily_notional_used_usd += result.executed_volume_usd

        async with AsyncSessionLocal() as session:
            await record_execution(session, result, self._user_id)


async def run_forever(config: RunnerConfig | None = None) -> None:
    """Entry point: bootstraps the local user and runs every configured pair.

    Runs until cancelled. Each pair's monitor is isolated — one pair's feed
    crashing (recorded via STATE.record_error) does not take down the
    others, since asyncio.gather here uses return_exceptions=True.
    """
    config = config or load_runner_config()
    if not config.enabled:
        logger.info("Runner disabled via RUNNER_ENABLED=false; not starting.")
        return
    if not config.monitored_pairs:
        logger.warning("No MONITORED_PAIRS configured; runner has nothing to do.")
        return

    async with AsyncSessionLocal() as session:
        user = await get_or_create_user_by_email(session, config.local_user_email)

    STATE.local_user_id = user.id
    STATE.monitored_pairs = [pair.symbol for pair in config.monitored_pairs]

    cache = OrderBookCache.from_url(config.redis_url)
    monitors = [PairMonitor(pair, cache, config, user.id) for pair in config.monitored_pairs]

    results = await asyncio.gather(*(m.run() for m in monitors), return_exceptions=True)
    for pair, result in zip(config.monitored_pairs, results):
        if isinstance(result, Exception):
            STATE.record_error(f"{pair.symbol} monitor exited: {result!r}")
