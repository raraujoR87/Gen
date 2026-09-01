"""Tests for backend.execution.paper_exchange.PaperExchangeClient.

Uses a fake in-memory cache (same shape as OrderBookCache.get_snapshot)
rather than a real Redis-backed OrderBookCache, keeping this suite free of
external services.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.execution.paper_exchange import PaperExchangeClient
from backend.schemas import OrderBookLevel, OrderBookSnapshot


class FakeCache:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], OrderBookSnapshot] = {}

    def put(self, snapshot: OrderBookSnapshot) -> None:
        self._snapshots[(snapshot.exchange, snapshot.symbol)] = snapshot

    async def get_snapshot(self, exchange: str, symbol: str):
        return self._snapshots.get((exchange, symbol))


def make_snapshot(exchange="binance", symbol="BTC/USDT", bid=99.0, ask=101.0) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange=exchange,
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[OrderBookLevel(price=bid, volume=1.0)],
        asks=[OrderBookLevel(price=ask, volume=1.0)],
    )


@pytest.mark.asyncio
async def test_place_ioc_order_fills_at_requested_price():
    cache = FakeCache()
    client = PaperExchangeClient(cache)

    result = await client.place_ioc_order("binance", "BTC/USDT", "buy", 0.5, 100.0)

    assert result.accepted is True
    assert result.filled_amount == 0.5
    assert result.avg_price == 100.0
    assert len(client.fills) == 1
    assert client.fills[0]["paper"] is True


@pytest.mark.asyncio
async def test_place_limit_order_fills_at_requested_price():
    cache = FakeCache()
    client = PaperExchangeClient(cache)

    result = await client.place_limit_order("kraken", "BTC/USDT", "sell", 1.0, 200.0)

    assert result.accepted is True
    assert result.avg_price == 200.0


@pytest.mark.asyncio
async def test_place_market_order_uses_cached_best_price():
    cache = FakeCache()
    cache.put(make_snapshot(bid=99.0, ask=101.0))
    client = PaperExchangeClient(cache)

    buy_result = await client.place_market_order("binance", "BTC/USDT", "buy", 1.0)
    sell_result = await client.place_market_order("binance", "BTC/USDT", "sell", 1.0)

    assert buy_result.avg_price == 101.0  # buys fill at the best ask
    assert sell_result.avg_price == 99.0  # sells fill at the best bid


@pytest.mark.asyncio
async def test_place_market_order_without_cached_snapshot_raises():
    cache = FakeCache()
    client = PaperExchangeClient(cache)

    with pytest.raises(RuntimeError):
        await client.place_market_order("binance", "BTC/USDT", "buy", 1.0)


@pytest.mark.asyncio
async def test_best_bid_reads_cached_snapshot():
    cache = FakeCache()
    cache.put(make_snapshot(bid=99.5, ask=101.5))
    client = PaperExchangeClient(cache)

    assert await client.best_bid("binance", "BTC/USDT") == 99.5


@pytest.mark.asyncio
async def test_best_bid_without_cached_snapshot_raises():
    cache = FakeCache()
    client = PaperExchangeClient(cache)

    with pytest.raises(RuntimeError):
        await client.best_bid("binance", "BTC/USDT")
