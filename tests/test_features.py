"""Tests for backend.marketdata.features: turning real OrderBookSnapshots
into the model's actual TemporalFeatures/DepthMatrix tensors."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.marketdata.features import DepthMatrixBuilder, TemporalFeatureWindow
from backend.schemas import (
    DepthMatrix,
    OrderBookLevel,
    OrderBookSnapshot,
    TemporalFeatures,
)


def snapshot(mid: float, ts: datetime) -> OrderBookSnapshot:
    spread = mid * 0.001
    return OrderBookSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        timestamp=ts,
        bids=[
            OrderBookLevel(price=mid - spread / 2, volume=1.0),
            OrderBookLevel(price=mid - spread, volume=2.0),
        ],
        asks=[
            OrderBookLevel(price=mid + spread / 2, volume=1.0),
            OrderBookLevel(price=mid + spread, volume=2.0),
        ],
    )


def test_temporal_feature_window_not_ready_until_full():
    window = TemporalFeatureWindow()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(TemporalFeatures.WINDOW_SIZE - 1):
        window.update(snapshot(100.0 + i, base + timedelta(seconds=i)))
        assert not window.is_ready
        assert window.to_temporal_features() is None


def test_temporal_feature_window_ready_and_shaped():
    window = TemporalFeatureWindow()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(TemporalFeatures.WINDOW_SIZE):
        window.update(snapshot(100.0 + i * 0.01, base + timedelta(seconds=i)))

    assert window.is_ready
    features = window.to_temporal_features()
    assert features is not None
    assert len(features.window) == TemporalFeatures.WINDOW_SIZE
    for row in features.window:
        assert len(row) == TemporalFeatures.FEATURE_COUNT


def test_temporal_feature_window_skips_empty_book():
    window = TemporalFeatureWindow()
    empty = OrderBookSnapshot(
        exchange="binance",
        symbol="BTC/USDT",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bids=[],
        asks=[],
    )
    window.update(empty)
    assert not window.is_ready
    assert len(window._rows) == 0


def test_depth_matrix_builder_ready_and_shaped():
    builder = DepthMatrixBuilder()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(DepthMatrix.SIZE):
        builder.update(snapshot(100.0 + i * 0.01, base + timedelta(seconds=i)))

    assert builder.is_ready
    depth = builder.to_depth_matrix()
    assert depth is not None
    assert len(depth.grid) == DepthMatrix.SIZE
    for row in depth.grid:
        assert len(row) == DepthMatrix.SIZE


def test_depth_matrix_builder_places_volume_near_center():
    builder = DepthMatrixBuilder(bin_width_pct=0.0005)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(DepthMatrix.SIZE):
        builder.update(snapshot(100.0, base + timedelta(seconds=i)))

    depth = builder.to_depth_matrix()
    assert depth is not None
    last_row = depth.grid[-1]
    half = DepthMatrix.SIZE // 2
    # Best bid/ask levels are within one bin of the mid price -> volume
    # should land in the two central bins, not at the row edges.
    assert sum(last_row[half - 2 : half + 2]) > 0
    assert last_row[0] == 0.0
    assert last_row[-1] == 0.0
