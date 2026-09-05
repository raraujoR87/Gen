"""Triangular arbitrage execution: three legs on a single exchange
(quote -> bridge -> target -> quote), fired concurrently.

This is the standard, and the only viable, way to run triangular
arbitrage: all three leg prices/quantities are derived from one frozen
read of the order books (see backend.execution.alpha.compute_triangular_net_alpha),
then all three IOC orders are placed at once. Waiting for leg 1 to fill
before placing leg 2, and leg 2 before leg 3, reintroduces exactly the
latency/slippage exposure the technique exists to eliminate — by the time
leg 3 fires, the price it was sized against is stale.

Unlike backend.execution.broken_leg (two exchanges, transfer/hedging risk
across venues), there's no cross-exchange risk here — but a failed leg
still leaves an unwanted position in the bridge or target asset on the
*same* exchange, which needs unwinding immediately.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from backend.execution.broken_leg import ExchangeClient
from backend.schemas import ExecutionStatus, TradeExecutionResult


@dataclass(frozen=True)
class TriangleConfig:
    """One triangular-arbitrage cycle: quote -> bridge -> target -> quote,
    all on `exchange`. Pair symbols are derived rather than hand-specified,
    so a triangle can't accidentally be configured with mismatched legs."""

    exchange: str
    quote: str
    bridge: str
    target: str

    @property
    def symbol_bridge_quote(self) -> str:
        """Pair to buy the bridge asset with the quote asset (e.g. BTC/USDT)."""
        return f"{self.bridge}/{self.quote}"

    @property
    def symbol_target_bridge(self) -> str:
        """Pair to buy the target asset with the bridge asset (e.g. ETH/BTC)."""
        return f"{self.target}/{self.bridge}"

    @property
    def symbol_target_quote(self) -> str:
        """Pair to sell the target asset back into the quote asset (e.g. ETH/USDT)."""
        return f"{self.target}/{self.quote}"

    @property
    def symbols(self) -> tuple[str, str, str]:
        return (self.symbol_bridge_quote, self.symbol_target_bridge, self.symbol_target_quote)

    @property
    def label(self) -> str:
        """Human-readable cycle description, used as the "symbol" in
        STATE.record_signal / persisted executions (there's no single
        trading-pair symbol for a 3-leg cycle)."""
        return f"{self.quote}->{self.bridge}->{self.target}->{self.quote}"


class TriangularMitigator:
    """Fires all three legs of a triangle concurrently; unwinds immediately
    on a partial fill."""

    def __init__(self, client: ExchangeClient) -> None:
        self.client = client

    async def execute_triangle(
        self,
        triangle: TriangleConfig,
        quote_notional_usd: float,
        bridge_quote_price: float,
        target_bridge_price: float,
        target_quote_price: float,
        bridge_qty: float,
        target_qty: float,
        gross_spread_pct: float,
        net_spread_pct: float,
        ml_confidence_score: float,
    ) -> TradeExecutionResult:
        """Dispatch the three legs concurrently and report the outcome.

        Args:
            triangle: The cycle being traded.
            quote_notional_usd: Capital deployed, in quote-currency units.
            bridge_quote_price, target_bridge_price, target_quote_price:
                The VWAPs each leg was sized against (from
                compute_triangular_net_alpha) — used as the IOC limit price
                for each leg.
            bridge_qty, target_qty: The quantities each leg trades (from
                compute_triangular_net_alpha's TriangularAlpha).
            gross_spread_pct, net_spread_pct, ml_confidence_score: Carried
                through to the persisted TradeExecutionResult, same as
                backend.execution.broken_leg.BrokenLegMitigator.
        """
        leg1, leg2, leg3 = await asyncio.gather(
            self.client.place_ioc_order(
                triangle.exchange, triangle.symbol_bridge_quote, "buy", bridge_qty, bridge_quote_price
            ),
            self.client.place_ioc_order(
                triangle.exchange, triangle.symbol_target_bridge, "buy", target_qty, target_bridge_price
            ),
            self.client.place_ioc_order(
                triangle.exchange, triangle.symbol_target_quote, "sell", target_qty, target_quote_price
            ),
        )

        if leg1.accepted and leg2.accepted and leg3.accepted:
            return TradeExecutionResult(
                status=ExecutionStatus.SUCCESS,
                buy_exchange=triangle.exchange,
                sell_exchange=triangle.exchange,
                symbol=triangle.label,
                executed_volume_usd=quote_notional_usd,
                gross_spread_pct=gross_spread_pct,
                net_spread_pct=net_spread_pct,
                realized_pnl_usd=quote_notional_usd * net_spread_pct,
                ml_confidence_score=ml_confidence_score,
                reason=None,
            )

        if not leg1.accepted and not leg2.accepted and not leg3.accepted:
            return TradeExecutionResult(
                status=ExecutionStatus.REJECTED,
                buy_exchange=triangle.exchange,
                sell_exchange=triangle.exchange,
                symbol=triangle.label,
                executed_volume_usd=0.0,
                gross_spread_pct=gross_spread_pct,
                net_spread_pct=net_spread_pct,
                realized_pnl_usd=0.0,
                ml_confidence_score=ml_confidence_score,
                reason=f"all three legs rejected: {leg1.reason}, {leg2.reason}, {leg3.reason}",
            )

        # Partial fill: unwind whatever legs succeeded back into the quote
        # asset immediately at market, so we don't end up holding an
        # unwanted position in the bridge or target asset. Not reachable
        # under backend.execution.paper_exchange.PaperExchangeClient today —
        # it always fills an accepted IOC order in full (see its own
        # docstring) — but real venues can and do reject individual legs
        # independently, so this path is real, not speculative; it mirrors
        # BrokenLegMitigator's equivalent (also currently unreachable under
        # the same paper client, for the same reason).
        unwind_notional = 0.0
        if leg1.accepted and not leg2.accepted:
            unwind = await self.client.place_market_order(
                triangle.exchange, triangle.symbol_bridge_quote, "sell", leg1.filled_amount
            )
            unwind_notional = unwind.filled_amount * unwind.avg_price
        elif leg1.accepted and leg2.accepted and not leg3.accepted:
            unwind = await self.client.place_market_order(
                triangle.exchange, triangle.symbol_target_quote, "sell", leg2.filled_amount
            )
            unwind_notional = unwind.filled_amount * unwind.avg_price

        status = ExecutionStatus.HEDGED if unwind_notional > 0 else ExecutionStatus.PARTIAL_FILL
        return TradeExecutionResult(
            status=status,
            buy_exchange=triangle.exchange,
            sell_exchange=triangle.exchange,
            symbol=triangle.label,
            executed_volume_usd=unwind_notional,
            gross_spread_pct=gross_spread_pct,
            net_spread_pct=net_spread_pct,
            realized_pnl_usd=0.0,
            ml_confidence_score=ml_confidence_score,
            reason=f"partial fill: leg1={leg1.accepted} leg2={leg2.accepted} leg3={leg3.accepted}",
        )
