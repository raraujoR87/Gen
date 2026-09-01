"""Builds BimodalArbitrageNet inputs (TemporalFeatures, DepthMatrix) from a
live stream of real OrderBookSnapshot updates on one exchange/symbol.

Neither this file nor any other unit previously turned a stream of real
order books into the model's actual tensors — units 3/5 only ever exercised
the model with synthetic/random data (see docs/ARCHITECTURE.md section 6
and backend/api/main.py's _synthetic_temporal_features/_synthetic_depth_matrix,
kept there as the documented interim mock for the on-demand HTTP endpoint).
This module is what the autonomous local runner (backend/marketdata/runner.py)
uses instead, once enough real history has accumulated.
"""
from __future__ import annotations

from collections import deque

from backend.marketdata.microstructure import (
    compute_micro_price,
    compute_order_flow_imbalance,
    compute_vwap,
)
from backend.schemas import DepthMatrix, OrderBookSnapshot, TemporalFeatures

# The 12 features per tick, in order. Each is directly computable from one
# OrderBookSnapshot plus (for OFI and the two "delta"/"accel" features) the
# immediately preceding one — matching docs/ARCHITECTURE.md section 4's
# "spread, OFI, VWAP drift, volume acceleration, ...".
FEATURE_NAMES = [
    "mid_price_return",
    "spread_pct",
    "vwap_bid_drift",
    "vwap_ask_drift",
    "micro_price_drift",
    "order_flow_imbalance",
    "best_bid_volume",
    "best_ask_volume",
    "volume_imbalance",
    "volume_acceleration",
    "bid_depth_notional",
    "ask_depth_notional",
]


class TemporalFeatureWindow:
    """Rolling buffer of the last WINDOW_SIZE feature rows for one (exchange, symbol).

    Feed it consecutive real OrderBookSnapshots via `update()`; once it has
    seen at least WINDOW_SIZE+1 snapshots, `to_temporal_features()` returns a
    real, non-synthetic TemporalFeatures window.
    """

    def __init__(self, notional_quantity: float = 1.0) -> None:
        self._notional_quantity = notional_quantity
        self._prev_snapshot: OrderBookSnapshot | None = None
        self._prev_total_volume: float | None = None
        self._rows: deque[list[float]] = deque(maxlen=TemporalFeatures.WINDOW_SIZE)

    def update(self, snapshot: OrderBookSnapshot) -> None:
        if not snapshot.bids or not snapshot.asks:
            return  # skip degenerate/empty books rather than crash the loop

        best_bid = snapshot.bids[0]
        best_ask = snapshot.asks[0]
        mid_price = (best_bid.price + best_ask.price) / 2
        spread_pct = (best_ask.price - best_bid.price) / mid_price if mid_price > 0 else 0.0

        try:
            vwap_bid = compute_vwap(snapshot.bids, self._notional_quantity)
            vwap_ask = compute_vwap(snapshot.asks, self._notional_quantity)
        except ValueError:
            # Not enough depth to fill the reference quantity yet — fall back
            # to best-price only rather than dropping the tick entirely.
            vwap_bid = best_bid.price
            vwap_ask = best_ask.price

        micro_price = compute_micro_price(best_bid, best_ask)
        bid_depth_notional = sum(level.price * level.volume for level in snapshot.bids)
        ask_depth_notional = sum(level.price * level.volume for level in snapshot.asks)
        total_volume = best_bid.volume + best_ask.volume
        volume_imbalance = (
            (best_bid.volume - best_ask.volume) / total_volume if total_volume > 0 else 0.0
        )

        if self._prev_snapshot is not None:
            prev_mid = (
                self._prev_snapshot.bids[0].price + self._prev_snapshot.asks[0].price
            ) / 2
            mid_price_return = (mid_price - prev_mid) / prev_mid if prev_mid > 0 else 0.0
            try:
                ofi = compute_order_flow_imbalance(self._prev_snapshot, snapshot)
            except (ValueError, IndexError):
                ofi = 0.0
            vwap_bid_drift = vwap_bid - self._prev_vwap_bid
            vwap_ask_drift = vwap_ask - self._prev_vwap_ask
            micro_price_drift = micro_price - self._prev_micro_price
            volume_accel = (
                total_volume - self._prev_total_volume
                if self._prev_total_volume is not None
                else 0.0
            )
        else:
            mid_price_return = 0.0
            ofi = 0.0
            vwap_bid_drift = 0.0
            vwap_ask_drift = 0.0
            micro_price_drift = 0.0
            volume_accel = 0.0

        self._rows.append(
            [
                mid_price_return,
                spread_pct,
                vwap_bid_drift,
                vwap_ask_drift,
                micro_price_drift,
                ofi,
                best_bid.volume,
                best_ask.volume,
                volume_imbalance,
                volume_accel,
                bid_depth_notional,
                ask_depth_notional,
            ]
        )

        self._prev_snapshot = snapshot
        self._prev_vwap_bid = vwap_bid
        self._prev_vwap_ask = vwap_ask
        self._prev_micro_price = micro_price
        self._prev_total_volume = total_volume

    @property
    def is_ready(self) -> bool:
        return len(self._rows) == TemporalFeatures.WINDOW_SIZE

    def to_temporal_features(self) -> TemporalFeatures | None:
        if not self.is_ready:
            return None
        return TemporalFeatures(window=[list(row) for row in self._rows])


class DepthMatrixBuilder:
    """Rolling SIZE x SIZE depth heatmap for one (exchange, symbol).

    Axis X (columns): SIZE price bins, symmetric around the mid price at
    each tick (bids on the left half, asks on the right half). Axis Y
    (rows): the last SIZE ticks, oldest first. Intensity: total volume
    resting in that price bin at that tick.
    """

    def __init__(self, bin_width_pct: float = 0.0005) -> None:
        """`bin_width_pct` is the width of each price bin as a fraction of
        the mid price (default 5 bps) — narrow enough to resolve real order
        book structure for a liquid pair without needing per-symbol tuning.
        """
        self._bin_width_pct = bin_width_pct
        self._rows: deque[list[float]] = deque(maxlen=DepthMatrix.SIZE)

    def update(self, snapshot: OrderBookSnapshot) -> None:
        if not snapshot.bids or not snapshot.asks:
            return

        mid_price = (snapshot.bids[0].price + snapshot.asks[0].price) / 2
        bin_width = mid_price * self._bin_width_pct
        if bin_width <= 0:
            return

        half = DepthMatrix.SIZE // 2
        row = [0.0] * DepthMatrix.SIZE

        for level in snapshot.bids:
            offset = int((mid_price - level.price) / bin_width)
            idx = half - 1 - offset
            if 0 <= idx < DepthMatrix.SIZE:
                row[idx] += level.volume

        for level in snapshot.asks:
            offset = int((level.price - mid_price) / bin_width)
            idx = half + offset
            if 0 <= idx < DepthMatrix.SIZE:
                row[idx] += level.volume

        self._rows.append(row)

    @property
    def is_ready(self) -> bool:
        return len(self._rows) == DepthMatrix.SIZE

    def to_depth_matrix(self) -> DepthMatrix | None:
        if not self.is_ready:
            return None
        return DepthMatrix(grid=[list(row) for row in self._rows])
