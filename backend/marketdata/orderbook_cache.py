"""Redis cache of the latest OrderBookSnapshot per (exchange, symbol).

Uses `redis.asyncio` so it composes with the rest of the async ingestion
pipeline. Snapshots are serialized as JSON and stored with a short TTL —
default 5 seconds, since a stale L2 snapshot is worse than useless for an
arbitrage engine reading off it.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import redis.asyncio as redis

from backend.schemas import OrderBookLevel, OrderBookSnapshot

DEFAULT_TTL_SECONDS = 5


def _cache_key(exchange: str, symbol: str) -> str:
    return f"orderbook:{exchange}:{symbol}"


def _snapshot_to_json(snapshot: OrderBookSnapshot) -> str:
    payload = {
        "exchange": snapshot.exchange,
        "symbol": snapshot.symbol,
        "timestamp": snapshot.timestamp.isoformat(),
        "bids": [[lvl.price, lvl.volume] for lvl in snapshot.bids],
        "asks": [[lvl.price, lvl.volume] for lvl in snapshot.asks],
    }
    return json.dumps(payload)


def _json_to_snapshot(raw: str) -> OrderBookSnapshot:
    payload = json.loads(raw)
    return OrderBookSnapshot(
        exchange=payload["exchange"],
        symbol=payload["symbol"],
        timestamp=datetime.fromisoformat(payload["timestamp"]),
        bids=[OrderBookLevel(price=p, volume=v) for p, v in payload["bids"]],
        asks=[OrderBookLevel(price=p, volume=v) for p, v in payload["asks"]],
    )


class OrderBookCache:
    """Thin async wrapper around a Redis client for order book snapshots."""

    def __init__(self, redis_client: "redis.Redis", ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> "OrderBookCache":
        return cls(redis.from_url(url, decode_responses=True), ttl_seconds=ttl_seconds)

    async def set_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        key = _cache_key(snapshot.exchange, snapshot.symbol)
        await self._redis.set(key, _snapshot_to_json(snapshot), ex=self._ttl_seconds)

    async def get_snapshot(self, exchange: str, symbol: str) -> Optional[OrderBookSnapshot]:
        raw = await self._redis.get(_cache_key(exchange, symbol))
        if raw is None:
            return None
        return _json_to_snapshot(raw)

    async def close(self) -> None:
        await self._redis.aclose()
