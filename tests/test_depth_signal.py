"""Tests for backend.ml.depth_signal.compute_depth_liquidity_hazard."""
from __future__ import annotations

from backend.ml.depth_signal import compute_depth_liquidity_hazard
from backend.schemas import DepthMatrix


def make_depth(row: list[float]) -> DepthMatrix:
    return DepthMatrix(grid=[row])


def test_small_order_against_deep_book_is_low_hazard():
    half = 25
    row = [0.0] * 50
    for i in range(half, half + 5):
        row[i] = 100.0  # deep resting ask liquidity near the touch
    depth = make_depth(row)

    hazard = compute_depth_liquidity_hazard(depth, quantity=1.0, side="ask")
    assert hazard < 0.01


def test_large_order_against_thin_book_is_high_hazard():
    half = 25
    row = [0.0] * 50
    for i in range(half, half + 5):
        row[i] = 1.0  # thin resting ask liquidity
    depth = make_depth(row)

    hazard = compute_depth_liquidity_hazard(depth, quantity=10.0, side="ask")
    assert hazard == 1.0


def test_order_equal_to_visible_liquidity_is_full_hazard():
    half = 25
    row = [0.0] * 50
    row[half] = 5.0
    depth = make_depth(row)

    hazard = compute_depth_liquidity_hazard(depth, quantity=5.0, side="ask")
    assert hazard == 1.0


def test_no_visible_liquidity_is_maximal_hazard():
    depth = make_depth([0.0] * 50)
    hazard = compute_depth_liquidity_hazard(depth, quantity=1.0, side="ask")
    assert hazard == 1.0


def test_zero_quantity_is_zero_hazard():
    half = 25
    row = [0.0] * 50
    row[half] = 5.0
    depth = make_depth(row)
    assert compute_depth_liquidity_hazard(depth, quantity=0.0, side="ask") == 0.0


def test_empty_grid_is_zero_hazard():
    depth = DepthMatrix(grid=[])
    assert compute_depth_liquidity_hazard(depth, quantity=1.0, side="ask") == 0.0


def test_bid_side_uses_left_half_of_row():
    half = 25
    row = [0.0] * 50
    for i in range(half - 5, half):
        row[i] = 100.0  # deep resting bid liquidity
    depth = make_depth(row)

    hazard = compute_depth_liquidity_hazard(depth, quantity=1.0, side="bid")
    assert hazard < 0.01
