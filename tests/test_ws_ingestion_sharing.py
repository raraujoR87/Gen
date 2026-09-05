"""Confirms backend.marketdata.ws_ingestion shares one exchange instance per
exchange_id across feeds, instead of one per (exchange, symbol) pair.

Regression test for a real bug: with many monitored pairs sharing an
exchange (e.g. several pairs all touching Kraken), a fresh ccxt.pro
instance per pair meant load_markets() fired once per pair, all at once —
Kraken's REST API reliably timed out under that concurrent load. Sharing
one instance per exchange means load_markets() only happens once no matter
how many symbols/pairs use that exchange.
"""
from __future__ import annotations

import pytest

ccxt_pro = pytest.importorskip("ccxt.pro")

from backend.marketdata.ws_ingestion import (
    CcxtProFeed,
    _pro_exchange_cache,
)


def test_same_exchange_id_shares_one_instance():
    _pro_exchange_cache.pop("binance", None)
    feed_a = CcxtProFeed("binance", "BTC/USDT")
    feed_b = CcxtProFeed("binance", "ETH/USDT")
    assert feed_a._exchange is feed_b._exchange


def test_different_exchange_ids_get_different_instances():
    _pro_exchange_cache.pop("binance", None)
    _pro_exchange_cache.pop("kraken", None)
    feed_a = CcxtProFeed("binance", "BTC/USDT")
    feed_b = CcxtProFeed("kraken", "BTC/USDT")
    assert feed_a._exchange is not feed_b._exchange


@pytest.mark.asyncio
async def test_close_does_not_tear_down_shared_instance():
    _pro_exchange_cache.pop("binance", None)
    feed_a = CcxtProFeed("binance", "BTC/USDT")
    feed_b = CcxtProFeed("binance", "ETH/USDT")
    await feed_a.close()
    # feed_b's (shared) exchange instance must still be usable afterwards —
    # closing one feed must not tear down another feed's connection.
    assert feed_b._exchange is feed_a._exchange
