"""Paper-trading ExchangeClient: simulates fills against real market prices
without ever sending a real order to an exchange.

Implements the `backend.execution.broken_leg.ExchangeClient` protocol, so
`BrokenLegMitigator` (the real broken-leg-mitigation state machine) can run
unmodified against it. Prices come from `backend.marketdata.orderbook_cache`
(real order book snapshots ingested by the runner) — so a paper trade is
priced exactly as a real one would be, only the actual order placement is
skipped.

This is intentionally optimistic (every order fills in full at the requested
price): real markets have partial fills, latency and slippage that this
does not model. That's an accepted simplification for "would this have been
profitable" validation, not a claim of realistic fill simulation — see
RUN_LOCAL.md.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict

from backend.execution.broken_leg import LegResult, Side
from backend.marketdata.orderbook_cache import OrderBookCache

logger = logging.getLogger(__name__)


class PaperExchangeClient:
    """In-memory simulated exchange, priced from real cached order books."""

    def __init__(self, cache: OrderBookCache, starting_balance_usd: float = 10_000.0) -> None:
        self._cache = cache
        # (exchange, asset) -> free balance. Seeded lazily with
        # starting_balance_usd of "USDT" per exchange the first time it's
        # touched, so paper trading works out of the box with no setup.
        self._balances: dict[tuple[str, str], float] = defaultdict(float)
        self._starting_balance_usd = starting_balance_usd
        self.fills: list[dict] = []  # audit trail, most recent last

    def _ensure_seeded(self, exchange: str) -> None:
        key = (exchange, "USDT")
        if key not in self._balances:
            self._balances[key] = self._starting_balance_usd

    async def _best_price(self, exchange: str, symbol: str, side: Side) -> float:
        snapshot = await self._cache.get_snapshot(exchange, symbol)
        if snapshot is None:
            raise RuntimeError(
                f"no cached order book for {exchange}/{symbol} — paper fill needs a "
                "recent real snapshot (the runner ingests these continuously)"
            )
        levels = snapshot.asks if side == "buy" else snapshot.bids
        if not levels:
            raise RuntimeError(f"cached order book for {exchange}/{symbol} has no {side} side")
        return levels[0].price

    async def _fill(self, exchange: str, symbol: str, side: Side, amount: float, price: float) -> LegResult:
        self._ensure_seeded(exchange)
        fill = {
            "id": str(uuid.uuid4()),
            "exchange": exchange,
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "paper": True,
        }
        self.fills.append(fill)
        logger.info("paper fill: %s", fill)
        return LegResult(accepted=True, filled_amount=amount, avg_price=price, reason=None)

    async def place_ioc_order(
        self, exchange: str, symbol: str, side: Side, amount: float, price: float
    ) -> LegResult:
        # Optimistic paper model: IOC always fills in full at the requested
        # price (real IOC can reject partially/fully on thin books — not
        # modeled here).
        return await self._fill(exchange, symbol, side, amount, price)

    async def place_limit_order(
        self, exchange: str, symbol: str, side: Side, amount: float, price: float
    ) -> LegResult:
        return await self._fill(exchange, symbol, side, amount, price)

    async def place_market_order(self, exchange: str, symbol: str, side: Side, amount: float) -> LegResult:
        price = await self._best_price(exchange, symbol, side)
        return await self._fill(exchange, symbol, side, amount, price)

    async def best_bid(self, exchange: str, symbol: str) -> float:
        snapshot = await self._cache.get_snapshot(exchange, symbol)
        if snapshot is None or not snapshot.bids:
            raise RuntimeError(f"no cached bid for {exchange}/{symbol}")
        return snapshot.bids[0].price
