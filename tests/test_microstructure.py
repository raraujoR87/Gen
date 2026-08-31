"""Deterministic numeric tests for backend.marketdata.microstructure."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.marketdata.microstructure import (
    compute_micro_price,
    compute_microstructure_metrics,
    compute_order_flow_imbalance,
    compute_vwap,
)
from backend.schemas import OrderBookLevel, OrderBookSnapshot


def snapshot(bids, asks, ts=None) -> OrderBookSnapshot:
    return OrderBookSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        timestamp=ts or datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[OrderBookLevel(price=p, volume=v) for p, v in bids],
        asks=[OrderBookLevel(price=p, volume=v) for p, v in asks],
    )


# ---------------------------------------------------------------------------
# compute_vwap
# ---------------------------------------------------------------------------

def test_vwap_single_level_fully_covers_quantity():
    levels = [OrderBookLevel(price=100.0, volume=5.0)]
    # Q=2 fully filled by the first level: VWAP == price
    assert compute_vwap(levels, 2.0) == pytest.approx(100.0)


def test_vwap_walks_multiple_levels():
    levels = [
        OrderBookLevel(price=100.0, volume=1.0),
        OrderBookLevel(price=101.0, volume=1.0),
        OrderBookLevel(price=102.0, volume=5.0),
    ]
    # Q=3: take 1@100 + 1@101 + 1@102 -> notional = 100+101+102 = 303, /3 = 101.0
    assert compute_vwap(levels, 3.0) == pytest.approx(101.0)


def test_vwap_partial_fill_of_last_level():
    levels = [
        OrderBookLevel(price=10.0, volume=2.0),
        OrderBookLevel(price=11.0, volume=2.0),
    ]
    # Q=3: take 2@10 + 1@11 -> notional = 20 + 11 = 31, /3 = 10.333...
    assert compute_vwap(levels, 3.0) == pytest.approx(31.0 / 3.0)


def test_vwap_insufficient_depth_raises():
    levels = [OrderBookLevel(price=10.0, volume=1.0)]
    with pytest.raises(ValueError):
        compute_vwap(levels, 5.0)


def test_vwap_nonpositive_quantity_raises():
    levels = [OrderBookLevel(price=10.0, volume=1.0)]
    with pytest.raises(ValueError):
        compute_vwap(levels, 0.0)


# ---------------------------------------------------------------------------
# compute_micro_price
# ---------------------------------------------------------------------------

def test_micro_price_symmetric_volumes_is_midpoint():
    best_bid = OrderBookLevel(price=100.0, volume=1.0)
    best_ask = OrderBookLevel(price=102.0, volume=1.0)
    # equal volumes -> weights 0.5/0.5 -> plain midpoint
    assert compute_micro_price(best_bid, best_ask) == pytest.approx(101.0)


def test_micro_price_skews_toward_heavier_opposite_side():
    best_bid = OrderBookLevel(price=100.0, volume=3.0)
    best_ask = OrderBookLevel(price=102.0, volume=1.0)
    # P_micro = 100*(1/4) + 102*(3/4) = 25 + 76.5 = 101.5
    assert compute_micro_price(best_bid, best_ask) == pytest.approx(101.5)


def test_micro_price_zero_total_volume_raises():
    best_bid = OrderBookLevel(price=100.0, volume=0.0)
    best_ask = OrderBookLevel(price=102.0, volume=0.0)
    with pytest.raises(ValueError):
        compute_micro_price(best_bid, best_ask)


# ---------------------------------------------------------------------------
# compute_order_flow_imbalance
# ---------------------------------------------------------------------------

def test_ofi_bid_price_improves_and_ask_price_worsens():
    prev = snapshot(bids=[(100.0, 2.0)], asks=[(101.0, 2.0)])
    curr = snapshot(bids=[(100.5, 3.0)], asks=[(101.5, 4.0)])
    # e_bid: bid price up -> +V_bid_t = +3.0
    # e_ask: ask price up -> -V_ask_t = -4.0
    # OFI = e_bid - e_ask = 3.0 - (-4.0) = 7.0
    assert compute_order_flow_imbalance(prev, curr) == pytest.approx(7.0)


def test_ofi_prices_unchanged_uses_volume_delta():
    prev = snapshot(bids=[(100.0, 2.0)], asks=[(101.0, 5.0)])
    curr = snapshot(bids=[(100.0, 5.0)], asks=[(101.0, 3.0)])
    # e_bid: price same -> V_bid_t - V_bid_{t-1} = 5-2 = 3
    # e_ask: price same -> V_ask_t - V_ask_{t-1} = 3-5 = -2
    # OFI = 3 - (-2) = 5
    assert compute_order_flow_imbalance(prev, curr) == pytest.approx(5.0)


def test_ofi_bid_price_worsens_and_ask_price_improves():
    prev = snapshot(bids=[(100.0, 2.0)], asks=[(101.0, 2.0)])
    curr = snapshot(bids=[(99.5, 1.0)], asks=[(100.5, 6.0)])
    # e_bid: bid price down -> -V_bid_t = -1.0
    # e_ask: ask price down -> +V_ask_t = +6.0
    # OFI = -1.0 - 6.0 = -7.0
    assert compute_order_flow_imbalance(prev, curr) == pytest.approx(-7.0)


def test_ofi_zero_when_book_unchanged():
    book = snapshot(bids=[(100.0, 2.0)], asks=[(101.0, 3.0)])
    assert compute_order_flow_imbalance(book, book) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_microstructure_metrics (integration of the three above)
# ---------------------------------------------------------------------------

def test_compute_microstructure_metrics_bundles_all_three():
    prev = snapshot(bids=[(100.0, 2.0)], asks=[(101.0, 2.0)])
    curr = snapshot(
        bids=[(100.5, 3.0), (100.0, 5.0)],
        asks=[(101.5, 4.0), (102.0, 5.0)],
    )

    metrics = compute_microstructure_metrics(prev, curr, quantity=3.0)

    # vwap_ask: take 3@101.5 (level has 4) -> price 101.5
    assert metrics.vwap_ask == pytest.approx(101.5)
    # vwap_bid: take 3@100.5 (level has 3) -> price 100.5
    assert metrics.vwap_bid == pytest.approx(100.5)
    # micro_price = 100.5*(4/7) + 101.5*(3/7)
    expected_micro = 100.5 * (4.0 / 7.0) + 101.5 * (3.0 / 7.0)
    assert metrics.micro_price == pytest.approx(expected_micro)
    # OFI: bid price up -> +3.0; ask price up -> -4.0; OFI = 3 - (-4) = 7.0
    assert metrics.order_flow_imbalance == pytest.approx(7.0)
