"""L2 order book ingestion workers.

`ccxt.pro` (the WebSocket-native sibling of `ccxt`) is the intended transport
for this module — see docs/ARCHITECTURE.md section 3 ("Sem polling REST —
WebSockets L2/L3 persistentes multi-par"). It is **not** a free/open-source
package (it ships under CCXT's commercial Pro license) and is therefore not
guaranteed to be installed in every environment this code runs in (it is not
pinned in requirements.txt, which only lists plain `ccxt`).

To keep this module importable and useful regardless of which package is
present, ingestion is expressed behind the `MarketDataFeed` abstract
interface, with two concrete implementations:

- `CcxtProFeed`: the production adapter, using `ccxt.pro`'s `watch_order_book`
  websocket streaming API. Used automatically when `ccxt.pro` is importable.
- `CcxtRestPollingFeed`: an explicit, documented fallback that polls
  `fetch_order_book` over plain `ccxt` on a fixed interval via async REST
  calls. It satisfies the same interface so callers (and tests) don't need to
  care which transport is active, but it is materially higher-latency than a
  real WebSocket feed and should not be relied on for production trading —
  only for environments where `ccxt.pro` is unavailable (e.g. CI, local dev).

`get_default_feed()` picks whichever implementation is available at import
time, preferring `ccxt.pro`.
"""
from __future__ import annotations

import abc
import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from backend.schemas import OrderBookLevel, OrderBookSnapshot

logger = logging.getLogger(__name__)

SnapshotCallback = Callable[[OrderBookSnapshot], Awaitable[None]]


def _raw_book_to_snapshot(exchange: str, symbol: str, raw_book: dict) -> OrderBookSnapshot:
    """Convert a ccxt/ccxt.pro raw order book dict into our OrderBookSnapshot."""
    ts_ms = raw_book.get("timestamp")
    if ts_ms is not None:
        timestamp = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    else:
        timestamp = datetime.now(tz=timezone.utc)

    bids = [OrderBookLevel(price=float(p), volume=float(v)) for p, v, *_ in raw_book.get("bids", [])]
    asks = [OrderBookLevel(price=float(p), volume=float(v)) for p, v, *_ in raw_book.get("asks", [])]

    return OrderBookSnapshot(
        exchange=exchange,
        symbol=symbol,
        timestamp=timestamp,
        bids=bids,
        asks=asks,
    )


class MarketDataFeed(abc.ABC):
    """Abstract L2 order book feed for a single (exchange, symbol) pair.

    Implementations push `OrderBookSnapshot`s onto an `asyncio.Queue` and/or
    invoke an optional async callback for every update, then run until
    `stop()` is called or the underlying connection is closed.
    """

    def __init__(self, exchange_id: str, symbol: str) -> None:
        self.exchange_id = exchange_id
        self.symbol = symbol
        self._stopped = asyncio.Event()

    @abc.abstractmethod
    async def _fetch_one(self) -> OrderBookSnapshot:
        """Return the next OrderBookSnapshot (blocks/awaits until available)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """Release any underlying exchange connection/session."""
        raise NotImplementedError

    def stop(self) -> None:
        self._stopped.set()

    async def run(
        self,
        queue: Optional["asyncio.Queue[OrderBookSnapshot]"] = None,
        callback: Optional[SnapshotCallback] = None,
    ) -> None:
        """Continuously fetch snapshots until stopped, publishing each one.

        At least one of `queue` or `callback` should be provided or updates
        are silently dropped.
        """
        try:
            while not self._stopped.is_set():
                snapshot = await self._fetch_one()
                if queue is not None:
                    await queue.put(snapshot)
                if callback is not None:
                    await callback(snapshot)
        finally:
            await self.close()


class CcxtProFeed(MarketDataFeed):
    """Production adapter: streams L2 order books via ccxt.pro websockets."""

    def __init__(self, exchange_id: str, symbol: str, limit: int = 50) -> None:
        super().__init__(exchange_id, symbol)
        try:
            import ccxt.pro as ccxtpro  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "ccxt.pro is not installed. Use CcxtRestPollingFeed as a "
                "fallback, or install the ccxt.pro package."
            ) from exc

        exchange_cls = getattr(ccxtpro, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"ccxt.pro has no exchange named {exchange_id!r}")
        self._exchange = exchange_cls()
        self._limit = limit

    async def _fetch_one(self) -> OrderBookSnapshot:
        raw_book = await self._exchange.watch_order_book(self.symbol, limit=self._limit)
        return _raw_book_to_snapshot(self.exchange_id, self.symbol, raw_book)

    async def close(self) -> None:
        close = getattr(self._exchange, "close", None)
        if close is not None:
            await close()


class CcxtRestPollingFeed(MarketDataFeed):
    """Fallback adapter: polls fetch_order_book over async REST at an interval.

    Only used when ccxt.pro is unavailable. Materially higher latency than a
    real websocket feed — documented as a fallback, not a production path.
    """

    def __init__(self, exchange_id: str, symbol: str, limit: int = 50, poll_interval_s: float = 1.0) -> None:
        super().__init__(exchange_id, symbol)
        import ccxt.async_support as ccxt_async  # plain ccxt's asyncio REST client

        exchange_cls = getattr(ccxt_async, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"ccxt has no exchange named {exchange_id!r}")
        self._exchange = exchange_cls()
        self._limit = limit
        self._poll_interval_s = poll_interval_s

    async def _fetch_one(self) -> OrderBookSnapshot:
        raw_book = await self._exchange.fetch_order_book(self.symbol, limit=self._limit)
        await asyncio.sleep(self._poll_interval_s)
        return _raw_book_to_snapshot(self.exchange_id, self.symbol, raw_book)

    async def close(self) -> None:
        await self._exchange.close()


def get_default_feed(exchange_id: str, symbol: str, **kwargs) -> MarketDataFeed:
    """Build the best available feed: ccxt.pro if importable, REST polling otherwise."""
    try:
        return CcxtProFeed(exchange_id, symbol, **kwargs)
    except RuntimeError:
        logger.warning(
            "ccxt.pro unavailable; falling back to REST-polling MarketDataFeed "
            "for %s/%s (higher latency, not recommended for production).",
            exchange_id,
            symbol,
        )
        return CcxtRestPollingFeed(exchange_id, symbol, **kwargs)
