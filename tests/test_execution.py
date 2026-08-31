"""Tests for backend/execution/: alpha, decision gate, broken-leg mitigation."""
from __future__ import annotations

import math

import pytest

from backend.execution.alpha import compute_net_alpha
from backend.execution.broken_leg import BrokenLegMitigator, LegResult
from backend.execution.decision import should_execute
from backend.execution.kill_switch import KillSwitch
from backend.schemas import ArbitrageSignal, ExecutionStatus, RiskLimits


# ---------------------------------------------------------------------------
# compute_net_alpha
# ---------------------------------------------------------------------------


def test_compute_net_alpha_known_values():
    # Buy on A at 100 with 0.1% fee, sell on B at 101 with 0.1% fee.
    # gross = (101*0.999 - 100*1.001) / (100*1.001)
    #       = (100.899 - 100.1) / 100.1 = 0.799 / 100.1
    vwap_bid_b = 101.0
    tau_b = 0.001
    vwap_ask_a = 100.0
    tau_a = 0.001
    slippage_est = 0.0005
    transfer_cost = 1.0
    capital_usd = 1000.0

    expected_gross = (vwap_bid_b * (1 - tau_b) - vwap_ask_a * (1 + tau_a)) / (
        vwap_ask_a * (1 + tau_a)
    )
    expected = expected_gross - slippage_est - (transfer_cost / capital_usd)

    result = compute_net_alpha(
        vwap_bid_b, tau_b, vwap_ask_a, tau_a, slippage_est, transfer_cost, capital_usd
    )
    assert math.isclose(result, expected, rel_tol=1e-9)
    assert math.isclose(result, 0.006482017982, rel_tol=1e-6)


def test_compute_net_alpha_zero_fees_zero_costs():
    result = compute_net_alpha(
        vwap_bid_b=110.0,
        tau_b=0.0,
        vwap_ask_a=100.0,
        tau_a=0.0,
        slippage_est=0.0,
        transfer_cost=0.0,
        capital_usd=100.0,
    )
    assert math.isclose(result, 0.10, rel_tol=1e-9)


def test_compute_net_alpha_negative_when_no_edge():
    result = compute_net_alpha(
        vwap_bid_b=100.0,
        tau_b=0.001,
        vwap_ask_a=100.0,
        tau_a=0.001,
        slippage_est=0.001,
        transfer_cost=5.0,
        capital_usd=100.0,
    )
    assert result < 0


def test_compute_net_alpha_rejects_nonpositive_capital():
    with pytest.raises(ValueError):
        compute_net_alpha(101.0, 0.001, 100.0, 0.001, 0.0005, 1.0, 0.0)


# ---------------------------------------------------------------------------
# should_execute
# ---------------------------------------------------------------------------


def _good_signal() -> ArbitrageSignal:
    return ArbitrageSignal(
        execution_probability=0.95,
        expected_alpha_bps=30.0,
        adverse_hazard=0.05,
    )


def _default_limits() -> RiskLimits:
    return RiskLimits(
        min_alpha_bps=15.0,
        min_execution_probability=0.85,
        max_adverse_hazard=0.20,
        max_notional_usd_per_trade=50.0,
        max_daily_notional_usd=500.0,
        kill_switch_engaged=False,
    )


def test_should_execute_approves_when_all_conditions_met():
    ok, reason = should_execute(
        net_alpha_bps=30.0,
        signal=_good_signal(),
        limits=_default_limits(),
        trade_notional_usd=40.0,
        daily_notional_used_usd=100.0,
    )
    assert ok is True
    assert reason == ""


def test_should_execute_rejects_kill_switch_engaged():
    limits = RiskLimits(kill_switch_engaged=True)
    ok, reason = should_execute(30.0, _good_signal(), limits)
    assert ok is False
    assert "kill switch" in reason.lower()


def test_should_execute_rejects_alpha_below_minimum():
    ok, reason = should_execute(10.0, _good_signal(), _default_limits())
    assert ok is False
    assert "alpha" in reason.lower()


def test_should_execute_rejects_alpha_equal_to_minimum():
    limits = _default_limits()
    ok, reason = should_execute(limits.min_alpha_bps, _good_signal(), limits)
    assert ok is False


def test_should_execute_rejects_low_execution_probability():
    signal = ArbitrageSignal(
        execution_probability=0.80, expected_alpha_bps=30.0, adverse_hazard=0.05
    )
    ok, reason = should_execute(30.0, signal, _default_limits())
    assert ok is False
    assert "execution_probability" in reason


def test_should_execute_rejects_high_adverse_hazard():
    signal = ArbitrageSignal(
        execution_probability=0.95, expected_alpha_bps=30.0, adverse_hazard=0.25
    )
    ok, reason = should_execute(30.0, signal, _default_limits())
    assert ok is False
    assert "adverse_hazard" in reason


def test_should_execute_rejects_trade_notional_over_cap():
    ok, reason = should_execute(
        30.0,
        _good_signal(),
        _default_limits(),
        trade_notional_usd=60.0,
        daily_notional_used_usd=0.0,
    )
    assert ok is False
    assert "max_notional_usd_per_trade" in reason


def test_should_execute_rejects_daily_notional_over_cap():
    ok, reason = should_execute(
        30.0,
        _good_signal(),
        _default_limits(),
        trade_notional_usd=50.0,
        daily_notional_used_usd=480.0,
    )
    assert ok is False
    assert "max_daily_notional_usd" in reason


def test_should_execute_ignores_notional_checks_when_not_provided():
    ok, reason = should_execute(30.0, _good_signal(), _default_limits())
    assert ok is True
    assert reason == ""


# ---------------------------------------------------------------------------
# BrokenLegMitigator / execute_paired_orders
# ---------------------------------------------------------------------------


class FakeExchangeClient:
    """Scripted ExchangeClient for deterministic tests."""

    def __init__(self, buy_accepted: bool, sell_accepted: bool, hedge_fully_fills: bool = True):
        self.buy_accepted = buy_accepted
        self.sell_accepted = sell_accepted
        self.hedge_fully_fills = hedge_fully_fills
        self.calls: list[tuple] = []

    async def place_ioc_order(self, exchange, symbol, side, amount, price):
        self.calls.append(("ioc", exchange, symbol, side, amount, price))
        if side == "buy":
            accepted = self.buy_accepted
        else:
            accepted = self.sell_accepted
        if accepted:
            return LegResult(accepted=True, filled_amount=amount, avg_price=price)
        return LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="IOC not filled")

    async def place_limit_order(self, exchange, symbol, side, amount, price):
        self.calls.append(("limit", exchange, symbol, side, amount, price))
        if self.hedge_fully_fills:
            return LegResult(accepted=True, filled_amount=amount, avg_price=price)
        return LegResult(accepted=True, filled_amount=amount * 0.5, avg_price=price)

    async def place_market_order(self, exchange, symbol, side, amount):
        self.calls.append(("market", exchange, symbol, side, amount))
        return LegResult(accepted=True, filled_amount=amount, avg_price=0.0)

    async def best_bid(self, exchange, symbol):
        self.calls.append(("best_bid", exchange, symbol))
        return 100.0


@pytest.mark.asyncio
async def test_execute_paired_orders_both_legs_accepted_is_success():
    client = FakeExchangeClient(buy_accepted=True, sell_accepted=True)
    mitigator = BrokenLegMitigator(client)

    result = await mitigator.execute_paired_orders(
        buy_exchange="binance",
        sell_exchange="kraken",
        symbol="BTC/USDT",
        amount=1.0,
        buy_price=100.0,
        sell_price=101.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.006,
        ml_confidence_score=0.9,
        high_volatility=False,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert result.executed_volume_usd == pytest.approx(100.0)
    assert result.reason is None


@pytest.mark.asyncio
async def test_execute_paired_orders_both_legs_rejected():
    client = FakeExchangeClient(buy_accepted=False, sell_accepted=False)
    mitigator = BrokenLegMitigator(client)

    result = await mitigator.execute_paired_orders(
        buy_exchange="binance",
        sell_exchange="kraken",
        symbol="BTC/USDT",
        amount=1.0,
        buy_price=100.0,
        sell_price=101.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.006,
        ml_confidence_score=0.9,
        high_volatility=False,
    )

    assert result.status == ExecutionStatus.REJECTED
    assert result.executed_volume_usd == 0.0


@pytest.mark.asyncio
async def test_execute_paired_orders_broken_leg_low_volatility_uses_repeg_limit():
    # Buy leg fills, sell leg rejected -> broken leg, low volatility hedge.
    client = FakeExchangeClient(buy_accepted=True, sell_accepted=False, hedge_fully_fills=True)
    mitigator = BrokenLegMitigator(client)

    result = await mitigator.execute_paired_orders(
        buy_exchange="binance",
        sell_exchange="kraken",
        symbol="BTC/USDT",
        amount=1.0,
        buy_price=100.0,
        sell_price=101.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.006,
        ml_confidence_score=0.9,
        high_volatility=False,
    )

    assert result.status == ExecutionStatus.HEDGED
    hedge_calls = [c for c in client.calls if c[0] == "limit"]
    assert len(hedge_calls) == 1
    assert hedge_calls[0][3] == "sell"  # flatten the bought leg by selling
    assert not any(c[0] == "market" for c in client.calls)


@pytest.mark.asyncio
async def test_execute_paired_orders_broken_leg_high_volatility_uses_market_order():
    # Sell leg fills, buy leg rejected -> broken leg, high volatility hedge.
    client = FakeExchangeClient(buy_accepted=False, sell_accepted=True)
    mitigator = BrokenLegMitigator(client)

    result = await mitigator.execute_paired_orders(
        buy_exchange="binance",
        sell_exchange="kraken",
        symbol="BTC/USDT",
        amount=1.0,
        buy_price=100.0,
        sell_price=101.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.006,
        ml_confidence_score=0.9,
        high_volatility=True,
    )

    assert result.status == ExecutionStatus.HEDGED
    market_calls = [c for c in client.calls if c[0] == "market"]
    assert len(market_calls) == 1
    assert market_calls[0][3] == "buy"  # flatten the shorted leg by buying back
    assert not any(c[0] == "limit" for c in client.calls)


@pytest.mark.asyncio
async def test_execute_paired_orders_broken_leg_partial_hedge_fill_is_partial_fill():
    client = FakeExchangeClient(buy_accepted=True, sell_accepted=False, hedge_fully_fills=False)
    mitigator = BrokenLegMitigator(client, max_repegs=1)

    result = await mitigator.execute_paired_orders(
        buy_exchange="binance",
        sell_exchange="kraken",
        symbol="BTC/USDT",
        amount=1.0,
        buy_price=100.0,
        sell_price=101.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.006,
        ml_confidence_score=0.9,
        high_volatility=False,
    )

    # One re-peg attempt fills half, remaining is liquidated via market order
    # -> still ends up fully hedged given the fallback.
    assert result.status == ExecutionStatus.HEDGED
    assert any(c[0] == "market" for c in client.calls)


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------


def test_kill_switch_engage_disengage_in_memory():
    ks = KillSwitch()
    assert ks.engaged is False
    ks.engage()
    assert ks.engaged is True
    ks.disengage()
    assert ks.engaged is False


def test_kill_switch_apply_returns_new_risk_limits_instance():
    ks = KillSwitch()
    ks.engage()
    base = RiskLimits(kill_switch_engaged=False)
    updated = ks.apply(base)
    assert updated.kill_switch_engaged is True
    assert base.kill_switch_engaged is False  # original untouched (frozen)


def test_kill_switch_persists_to_file(tmp_path):
    state_path = tmp_path / "kill_switch_state.json"
    ks1 = KillSwitch(state_path=state_path)
    ks1.engage()

    ks2 = KillSwitch(state_path=state_path)
    assert ks2.engaged is True
