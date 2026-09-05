"""Real liquidity-risk signal derived from DepthMatrix — the depth grid that,
until now, was computed on every tick and only ever written to the sample
log, never actually used by the decision itself (backend.ml.heuristic only
looked at net-alpha persistence and price volatility).

This is a genuine, if simple, use of real order-book data: it estimates how
much of the resting liquidity near the touch our own order would consume.
A thin book there is a real reason to expect slippage beyond what
compute_net_alpha's fixed slippage_est assumes — the fixed estimate has no
way to know whether today's book happens to be thin.
"""
from __future__ import annotations

from backend.schemas import DepthMatrix

# How many price bins out from mid to count as "near the touch" when
# summing resting liquidity. Each bin is bin_width_pct wide (see
# backend.marketdata.features.DepthMatrixBuilder, default 5 bps), so 5 bins
# covers roughly the nearest 25 bps of resting depth on that side.
_NEAR_TOUCH_BINS = 5


def compute_depth_liquidity_hazard(depth_matrix: DepthMatrix, quantity: float, side: str = "ask") -> float:
    """Fraction of `quantity` (base-asset units) that would consume the
    resting liquidity visible in the nearest `_NEAR_TOUCH_BINS` bins on the
    requested side of the book, clipped to [0, 1].

    0.0 means our order is negligible next to the visible depth (safe);
    1.0 means it would consume all of it or more (real slippage risk this
    tick's fixed slippage_est doesn't account for). `side` is "ask" for a
    buy order or "bid" for a sell order, matching DepthMatrixBuilder's
    layout (bids in the left half of each row, asks in the right half).
    """
    if not depth_matrix.grid or quantity <= 0:
        return 0.0

    row = depth_matrix.grid[-1]  # most recent tick
    half = len(row) // 2
    if side == "ask":
        near_touch_bins = row[half : half + _NEAR_TOUCH_BINS]
    else:
        near_touch_bins = row[max(0, half - _NEAR_TOUCH_BINS) : half]

    near_touch_liquidity = sum(near_touch_bins)
    if near_touch_liquidity <= 0:
        return 1.0  # no visible resting liquidity near the touch at all

    return min(1.0, quantity / near_touch_liquidity)
