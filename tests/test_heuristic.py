"""Tests for backend.ml.heuristic.HeuristicSignalEstimator."""
from __future__ import annotations

from backend.ml.heuristic import HeuristicConfig, HeuristicSignalEstimator


def test_first_tick_positive_alpha_gives_full_persistence():
    estimator = HeuristicSignalEstimator()
    signal = estimator.update(net_alpha_bps=20.0, mid_price_return=0.0)
    assert signal.execution_probability == 1.0
    assert signal.expected_alpha_bps == 20.0
    assert signal.adverse_hazard == 0.0


def test_first_tick_negative_alpha_gives_zero_persistence():
    estimator = HeuristicSignalEstimator()
    signal = estimator.update(net_alpha_bps=-5.0, mid_price_return=0.0)
    assert signal.execution_probability == 0.0


def test_persistence_is_fraction_of_positive_ticks():
    estimator = HeuristicSignalEstimator()
    for alpha in (10.0, -10.0, 10.0, 10.0):
        signal = estimator.update(net_alpha_bps=alpha, mid_price_return=0.0)
    # 3 of 4 ticks positive
    assert signal.execution_probability == 0.75


def test_window_size_caps_history():
    estimator = HeuristicSignalEstimator(HeuristicConfig(window_size=2))
    estimator.update(net_alpha_bps=10.0, mid_price_return=0.0)
    estimator.update(net_alpha_bps=-10.0, mid_price_return=0.0)
    signal = estimator.update(net_alpha_bps=10.0, mid_price_return=0.0)
    # Only the last 2 ticks count: [-10.0 dropped], now [-10.0, 10.0] -> wait,
    # window keeps the 2 most recent: (-10.0, 10.0) -> 1 of 2 positive
    assert signal.execution_probability == 0.5


def test_volatile_returns_increase_hazard():
    calm = HeuristicSignalEstimator()
    for _ in range(10):
        calm_signal = calm.update(net_alpha_bps=10.0, mid_price_return=0.0)

    volatile = HeuristicSignalEstimator()
    for r in (0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01):
        volatile_signal = volatile.update(net_alpha_bps=10.0, mid_price_return=r)

    assert calm_signal.adverse_hazard == 0.0
    assert volatile_signal.adverse_hazard > calm_signal.adverse_hazard
    assert volatile_signal.adverse_hazard == 1.0  # clipped at the configured scale


def test_hazard_is_clipped_to_one():
    estimator = HeuristicSignalEstimator(HeuristicConfig(volatility_hazard_scale_bps=1.0))
    signal = estimator.update(net_alpha_bps=0.0, mid_price_return=0.01)
    estimator.update(net_alpha_bps=0.0, mid_price_return=-0.01)
    signal = estimator.update(net_alpha_bps=0.0, mid_price_return=0.01)
    assert 0.0 <= signal.adverse_hazard <= 1.0


def test_depth_liquidity_hazard_dominates_when_higher():
    estimator = HeuristicSignalEstimator()
    # Calm market (volatility hazard 0.0) but a thin book (liquidity hazard 0.9).
    signal = estimator.update(net_alpha_bps=10.0, mid_price_return=0.0, depth_liquidity_hazard=0.9)
    assert signal.adverse_hazard == 0.9


def test_volatility_hazard_dominates_when_higher():
    estimator = HeuristicSignalEstimator()
    for r in (0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01):
        signal = estimator.update(net_alpha_bps=10.0, mid_price_return=r, depth_liquidity_hazard=0.1)
    assert signal.adverse_hazard == 1.0  # volatility hazard (1.0) beats liquidity hazard (0.1)
