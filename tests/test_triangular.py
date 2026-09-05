"""Tests for backend.execution.alpha.compute_triangular_net_alpha and
backend.execution.triangular (TriangleConfig, TriangularMitigator)."""
from __future__ import annotations

import pytest

from backend.execution.alpha import compute_triangular_net_alpha
from backend.execution.broken_leg import LegResult
from backend.execution.triangular import TriangleConfig, TriangularMitigator
from backend.schemas import ExecutionStatus

# ---------------------------------------------------------------------------
# TriangleConfig
# ---------------------------------------------------------------------------


def test_triangle_config_derives_symbols():
    triangle = TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="ETH")
    assert triangle.symbol_bridge_quote == "BTC/USDT"
    assert triangle.symbol_target_bridge == "ETH/BTC"
    assert triangle.symbol_target_quote == "ETH/USDT"
    assert triangle.symbols == ("BTC/USDT", "ETH/BTC", "ETH/USDT")


def test_triangle_config_label():
    triangle = TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="ETH")
    assert triangle.label == "USDT->BTC->ETH->USDT"


# ---------------------------------------------------------------------------
# compute_triangular_net_alpha
# ---------------------------------------------------------------------------


def test_triangular_net_alpha_profitable_round_trip():
    # Perfectly circular prices with zero fees: 1 USDT -> 1/100 BTC ->
    # (1/100)/10 ETH -> (1/1000)*1000 USDT = exactly break-even.
    alpha = compute_triangular_net_alpha(
        quote_notional=1000.0,
        vwap_bridge_quote=100.0,  # 1 BTC = 100 USDT
        vwap_target_bridge=10.0,  # 1 ETH = 10 BTC
        vwap_target_quote=1000.0,  # 1 ETH = 1000 USDT
        tau=0.0,
    )
    assert alpha.net_alpha == pytest.approx(0.0, abs=1e-9)
    assert alpha.bridge_qty == pytest.approx(10.0)  # 1000 / 100
    assert alpha.target_qty == pytest.approx(1.0)  # 10 / 10


def test_triangular_net_alpha_positive_when_mispriced():
    # Same as above but target_quote is priced higher than break-even ->
    # selling the target back yields more quote than we started with.
    alpha = compute_triangular_net_alpha(
        quote_notional=1000.0,
        vwap_bridge_quote=100.0,
        vwap_target_bridge=10.0,
        vwap_target_quote=1010.0,  # 1% richer than break-even
        tau=0.0,
    )
    assert alpha.net_alpha > 0.0
    assert alpha.net_alpha == pytest.approx(0.01, rel=1e-6)


def test_triangular_net_alpha_fees_erode_a_marginal_edge():
    no_fee = compute_triangular_net_alpha(
        quote_notional=1000.0,
        vwap_bridge_quote=100.0,
        vwap_target_bridge=10.0,
        vwap_target_quote=1010.0,
        tau=0.0,
    )
    with_fee = compute_triangular_net_alpha(
        quote_notional=1000.0,
        vwap_bridge_quote=100.0,
        vwap_target_bridge=10.0,
        vwap_target_quote=1010.0,
        tau=0.001,  # 10 bps per leg, three legs
    )
    assert with_fee.net_alpha < no_fee.net_alpha


def test_triangular_net_alpha_rejects_nonpositive_notional():
    with pytest.raises(ValueError):
        compute_triangular_net_alpha(
            quote_notional=0.0,
            vwap_bridge_quote=100.0,
            vwap_target_bridge=10.0,
            vwap_target_quote=1000.0,
            tau=0.0,
        )


def test_triangular_net_alpha_rejects_nonpositive_vwap():
    with pytest.raises(ValueError):
        compute_triangular_net_alpha(
            quote_notional=1000.0,
            vwap_bridge_quote=0.0,
            vwap_target_bridge=10.0,
            vwap_target_quote=1000.0,
            tau=0.0,
        )


# ---------------------------------------------------------------------------
# TriangularMitigator
# ---------------------------------------------------------------------------


class FakeClient:
    """Fake ExchangeClient with per-symbol scripted outcomes for each call."""

    def __init__(self, ioc_results: dict[str, LegResult], market_results: dict[str, LegResult] | None = None):
        self._ioc_results = ioc_results
        self._market_results = market_results or {}
        self.ioc_calls: list[tuple] = []
        self.market_calls: list[tuple] = []

    async def place_ioc_order(self, exchange, symbol, side, amount, price):
        self.ioc_calls.append((exchange, symbol, side, amount, price))
        return self._ioc_results[symbol]

    async def place_limit_order(self, exchange, symbol, side, amount, price):
        raise NotImplementedError

    async def place_market_order(self, exchange, symbol, side, amount):
        self.market_calls.append((exchange, symbol, side, amount))
        return self._market_results[symbol]

    async def best_bid(self, exchange, symbol):
        raise NotImplementedError


TRIANGLE = TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="ETH")


@pytest.mark.asyncio
async def test_execute_triangle_all_legs_fill_is_success():
    client = FakeClient(
        ioc_results={
            "BTC/USDT": LegResult(accepted=True, filled_amount=10.0, avg_price=100.0),
            "ETH/BTC": LegResult(accepted=True, filled_amount=1.0, avg_price=10.0),
            "ETH/USDT": LegResult(accepted=True, filled_amount=1.0, avg_price=1010.0),
        }
    )
    mitigator = TriangularMitigator(client)

    result = await mitigator.execute_triangle(
        triangle=TRIANGLE,
        quote_notional_usd=1000.0,
        bridge_quote_price=100.0,
        target_bridge_price=10.0,
        target_quote_price=1010.0,
        bridge_qty=10.0,
        target_qty=1.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.01,
        ml_confidence_score=0.9,
    )

    assert result.status == ExecutionStatus.SUCCESS
    assert result.executed_volume_usd == 1000.0
    assert result.realized_pnl_usd == pytest.approx(10.0)
    assert result.symbol == TRIANGLE.label
    assert len(client.ioc_calls) == 3


@pytest.mark.asyncio
async def test_execute_triangle_all_legs_rejected():
    client = FakeClient(
        ioc_results={
            "BTC/USDT": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="no liquidity"),
            "ETH/BTC": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="no liquidity"),
            "ETH/USDT": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="no liquidity"),
        }
    )
    mitigator = TriangularMitigator(client)

    result = await mitigator.execute_triangle(
        triangle=TRIANGLE,
        quote_notional_usd=1000.0,
        bridge_quote_price=100.0,
        target_bridge_price=10.0,
        target_quote_price=1010.0,
        bridge_qty=10.0,
        target_qty=1.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.01,
        ml_confidence_score=0.9,
    )

    assert result.status == ExecutionStatus.REJECTED
    assert result.executed_volume_usd == 0.0
    assert result.realized_pnl_usd == 0.0


@pytest.mark.asyncio
async def test_execute_triangle_leg2_fails_unwinds_bridge_position():
    client = FakeClient(
        ioc_results={
            "BTC/USDT": LegResult(accepted=True, filled_amount=10.0, avg_price=100.0),
            "ETH/BTC": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="rejected"),
            "ETH/USDT": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="rejected"),
        },
        market_results={
            "BTC/USDT": LegResult(accepted=True, filled_amount=10.0, avg_price=99.5),
        },
    )
    mitigator = TriangularMitigator(client)

    result = await mitigator.execute_triangle(
        triangle=TRIANGLE,
        quote_notional_usd=1000.0,
        bridge_quote_price=100.0,
        target_bridge_price=10.0,
        target_quote_price=1010.0,
        bridge_qty=10.0,
        target_qty=1.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.01,
        ml_confidence_score=0.9,
    )

    assert result.status == ExecutionStatus.HEDGED
    assert result.executed_volume_usd == pytest.approx(995.0)  # 10.0 * 99.5
    assert client.market_calls == [("binance", "BTC/USDT", "sell", 10.0)]


@pytest.mark.asyncio
async def test_execute_triangle_leg3_fails_unwinds_target_position():
    client = FakeClient(
        ioc_results={
            "BTC/USDT": LegResult(accepted=True, filled_amount=10.0, avg_price=100.0),
            "ETH/BTC": LegResult(accepted=True, filled_amount=1.0, avg_price=10.0),
            "ETH/USDT": LegResult(accepted=False, filled_amount=0.0, avg_price=0.0, reason="rejected"),
        },
        market_results={
            "ETH/USDT": LegResult(accepted=True, filled_amount=1.0, avg_price=1000.0),
        },
    )
    mitigator = TriangularMitigator(client)

    result = await mitigator.execute_triangle(
        triangle=TRIANGLE,
        quote_notional_usd=1000.0,
        bridge_quote_price=100.0,
        target_bridge_price=10.0,
        target_quote_price=1010.0,
        bridge_qty=10.0,
        target_qty=1.0,
        gross_spread_pct=0.01,
        net_spread_pct=0.01,
        ml_confidence_score=0.9,
    )

    assert result.status == ExecutionStatus.HEDGED
    assert result.executed_volume_usd == pytest.approx(1000.0)  # 1.0 * 1000.0
    assert client.market_calls == [("binance", "ETH/USDT", "sell", 1.0)]
