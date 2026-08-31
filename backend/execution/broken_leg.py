"""Broken Leg Mitigation state machine.

Per docs/ARCHITECTURE.md section 5: both legs of an arbitrage pair are fired
concurrently as IOC orders. If both are accepted, execution is a SUCCESS. If
one leg is rejected while the other fills, the filled ("open") leg leaves the
book unhedged and must be flattened immediately:

  * low volatility  -> limit order re-pegged to the best bid, to capture
    favorable execution while still moving fast;
  * high volatility / rupture -> immediate market liquidation with a hard
    stop at break-even, prioritizing certainty of exit over price.

This module depends only on an abstract ExchangeClient protocol so it can be
tested without real exchange credentials (ccxt.pro is the intended concrete
implementation, injected by the caller).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from backend.schemas import ExecutionStatus, TradeExecutionResult

Side = Literal["buy", "sell"]


@dataclass(frozen=True)
class LegResult:
    """Outcome of a single order placement."""

    accepted: bool
    filled_amount: float
    avg_price: float
    reason: Optional[str] = None


class ExchangeClient(Protocol):
    """Abstract execution surface. A ccxt-async-backed implementation is the
    intended production adapter; tests inject a fake."""

    async def place_ioc_order(
        self, exchange: str, symbol: str, side: Side, amount: float, price: float
    ) -> LegResult: ...

    async def place_limit_order(
        self, exchange: str, symbol: str, side: Side, amount: float, price: float
    ) -> LegResult: ...

    async def place_market_order(
        self, exchange: str, symbol: str, side: Side, amount: float
    ) -> LegResult: ...

    async def best_bid(self, exchange: str, symbol: str) -> float: ...


class BrokenLegMitigator:
    """Fires paired IOC legs and auto-hedges a broken leg when needed."""

    def __init__(self, client: ExchangeClient, max_repegs: int = 3):
        self.client = client
        self.max_repegs = max_repegs

    async def execute_paired_orders(
        self,
        buy_exchange: str,
        sell_exchange: str,
        symbol: str,
        amount: float,
        buy_price: float,
        sell_price: float,
        gross_spread_pct: float,
        net_spread_pct: float,
        ml_confidence_score: float,
        high_volatility: bool,
    ) -> TradeExecutionResult:
        """Fire both legs in parallel and mitigate a broken leg if one occurs.

        Args:
            buy_exchange: Exchange to buy (leg A / ask side) on.
            sell_exchange: Exchange to sell (leg B / bid side) on.
            symbol: Trading pair symbol, e.g. "BTC/USDT".
            amount: Base-asset quantity for each leg.
            buy_price: Limit/IOC price for the buy leg.
            sell_price: Limit/IOC price for the sell leg.
            gross_spread_pct: Gross spread of the opportunity, for reporting.
            net_spread_pct: Net (post-cost) spread, for reporting.
            ml_confidence_score: Model confidence carried into the result.
            high_volatility: Whether current market conditions call for
                immediate market liquidation (True) rather than a re-pegged
                limit order (False) when hedging a broken leg.

        Returns:
            A TradeExecutionResult describing the final outcome.
        """
        buy_result, sell_result = await asyncio.gather(
            self.client.place_ioc_order(buy_exchange, symbol, "buy", amount, buy_price),
            self.client.place_ioc_order(sell_exchange, symbol, "sell", amount, sell_price),
        )

        if buy_result.accepted and sell_result.accepted:
            executed_volume_usd = min(buy_result.filled_amount, sell_result.filled_amount) * buy_price
            return TradeExecutionResult(
                status=ExecutionStatus.SUCCESS,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                symbol=symbol,
                executed_volume_usd=executed_volume_usd,
                gross_spread_pct=gross_spread_pct,
                net_spread_pct=net_spread_pct,
                realized_pnl_usd=executed_volume_usd * net_spread_pct,
                ml_confidence_score=ml_confidence_score,
                reason=None,
            )

        if not buy_result.accepted and not sell_result.accepted:
            return TradeExecutionResult(
                status=ExecutionStatus.REJECTED,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                symbol=symbol,
                executed_volume_usd=0.0,
                gross_spread_pct=gross_spread_pct,
                net_spread_pct=net_spread_pct,
                realized_pnl_usd=0.0,
                ml_confidence_score=ml_confidence_score,
                reason=f"both legs rejected: buy={buy_result.reason}, sell={sell_result.reason}",
            )

        # Exactly one leg filled -> broken leg. Flatten the open position.
        if buy_result.accepted:
            open_exchange = buy_exchange
            open_amount = buy_result.filled_amount
            hedge_side: Side = "sell"
            broken_reason = f"sell leg rejected: {sell_result.reason}"
        else:
            open_exchange = sell_exchange
            open_amount = sell_result.filled_amount
            hedge_side = "buy"
            broken_reason = f"buy leg rejected: {buy_result.reason}"

        break_even_price = buy_price if hedge_side == "sell" else sell_price

        hedge_filled = await self._auto_hedge(
            exchange=open_exchange,
            symbol=symbol,
            side=hedge_side,
            amount=open_amount,
            break_even_price=break_even_price,
            high_volatility=high_volatility,
        )

        executed_volume_usd = open_amount * break_even_price
        if hedge_filled >= open_amount:
            status = ExecutionStatus.HEDGED
        else:
            status = ExecutionStatus.PARTIAL_FILL

        return TradeExecutionResult(
            status=status,
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            symbol=symbol,
            executed_volume_usd=executed_volume_usd,
            gross_spread_pct=gross_spread_pct,
            net_spread_pct=net_spread_pct,
            realized_pnl_usd=0.0,
            ml_confidence_score=ml_confidence_score,
            reason=broken_reason,
        )

    async def _auto_hedge(
        self,
        exchange: str,
        symbol: str,
        side: Side,
        amount: float,
        break_even_price: float,
        high_volatility: bool,
    ) -> float:
        """Flatten `amount` of the open leg. Returns the total filled amount.

        High volatility / rupture: immediate market liquidation (a hard stop
        at break-even is the caller's/exchange's responsibility to attach;
        here we prioritize certainty of exit).

        Low volatility: limit order re-pegged to the best bid, retried up to
        `max_repegs` times before falling back to a market order.
        """
        if high_volatility:
            result = await self.client.place_market_order(exchange, symbol, side, amount)
            return result.filled_amount

        remaining = amount
        filled_total = 0.0
        for _ in range(self.max_repegs):
            if remaining <= 0:
                break
            peg_price = await self.client.best_bid(exchange, symbol)
            result = await self.client.place_limit_order(exchange, symbol, side, remaining, peg_price)
            filled_total += result.filled_amount
            remaining -= result.filled_amount

        if remaining > 0:
            # Re-pegging exhausted without a full fill: liquidate the rest at
            # market to guarantee the broken leg is closed.
            result = await self.client.place_market_order(exchange, symbol, side, remaining)
            filled_total += result.filled_amount

        return filled_total
