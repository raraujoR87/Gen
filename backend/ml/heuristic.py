"""Statistical (non-neural) arbitrage signal, grounded in real market history.

BimodalArbitrageNet (backend/ml/model.py) is currently untrained — random
weights, contributing no real information; see backend/ml/model_cache.py's
own docstring. Training it needs labeled historical L2 order book data,
which cannot be downloaded and can only be collected by running this
service over time (see backend/marketdata/sample_logger.py). Until a real
checkpoint exists, this heuristic is the runner's actual "intelligence": a
transparent estimate computed directly from a pair's own recent real
history of net alpha and price movement, not a fabricated substitute for
a trained model.

Two real, computable quantities stand in for the model's two probability
heads:

  - execution_probability -> persistence: the fraction of recent ticks
    where net alpha was already positive. A real, if simple, proxy for
    "would this opportunity likely still be there by the time an order
    reaches the exchange" — an opportunity that flickers positive for one
    tick and vanishes is a bad bet even if its instantaneous value looks
    good.
  - adverse_hazard -> recent realized volatility of mid-price returns,
    scaled into [0, 1]. Higher volatility means the price is more likely
    to move against an open leg before it can be hedged.

expected_alpha_bps is not estimated at all here — the caller already has
the real value (backend.execution.alpha.compute_net_alpha), so this module
just carries it through unchanged.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from backend.schemas import ArbitrageSignal


@dataclass(frozen=True)
class HeuristicConfig:
    window_size: int = 30
    """How many recent ticks' net alpha / return history to consider."""

    volatility_hazard_scale_bps: float = 50.0
    """Stdev of mid-price return (in bps) that maps to adverse_hazard=1.0.
    Chosen as a round, documented number — not calibrated against real
    outcome data yet, since none exists (see sample_logger.py); revisit
    once logged samples make a real calibration possible."""


class HeuristicSignalEstimator:
    """Maintains rolling real-market history for one pair and derives an
    ArbitrageSignal from it — no model, no randomness, no fabricated data."""

    def __init__(self, config: HeuristicConfig | None = None) -> None:
        self._config = config or HeuristicConfig()
        self._alpha_history: deque[float] = deque(maxlen=self._config.window_size)
        self._return_history: deque[float] = deque(maxlen=self._config.window_size)

    def update(
        self,
        net_alpha_bps: float,
        mid_price_return: float,
        depth_liquidity_hazard: float = 0.0,
    ) -> ArbitrageSignal:
        """Feed the latest real tick and return the resulting signal.

        `depth_liquidity_hazard` is an optional real signal from
        backend.ml.depth_signal.compute_depth_liquidity_hazard — how much of
        the resting order-book depth near the touch this trade's own size
        would consume, in [0, 1]. Combined with the volatility-based hazard
        via max(), not an average: either one alone is a real, independent
        reason for caution (a calm, thin book is still risky; a volatile,
        deep book still is too), so the more cautious of the two should win
        rather than be diluted by the other.
        """
        self._alpha_history.append(net_alpha_bps)
        self._return_history.append(mid_price_return)

        n = len(self._alpha_history)
        positive_ticks = sum(1 for a in self._alpha_history if a > 0)
        persistence = positive_ticks / n if n else 0.0

        if n >= 2:
            mean_return = sum(self._return_history) / n
            variance = sum((r - mean_return) ** 2 for r in self._return_history) / n
            stdev_bps = (variance**0.5) * 1e4
        else:
            stdev_bps = 0.0
        volatility_hazard = min(1.0, stdev_bps / self._config.volatility_hazard_scale_bps)
        hazard = max(volatility_hazard, depth_liquidity_hazard)

        return ArbitrageSignal(
            execution_probability=persistence,
            expected_alpha_bps=net_alpha_bps,
            adverse_hazard=hazard,
        )
