"""Tests for backend.config.get_taker_fee_bps and MONITORED_TRIANGLES parsing."""
from __future__ import annotations

import pytest

from backend.config import _parse_monitored_triangles, get_taker_fee_bps
from backend.execution.triangular import TriangleConfig


def test_known_exchange_uses_its_own_default(monkeypatch):
    monkeypatch.delenv("EXCHANGE_TAKER_FEE_BPS_KRAKEN", raising=False)
    assert get_taker_fee_bps("kraken", default_fee_bps=10.0) == 26.0
    assert get_taker_fee_bps("binance", default_fee_bps=10.0) == 10.0


def test_unknown_exchange_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("EXCHANGE_TAKER_FEE_BPS_OKX", raising=False)
    assert get_taker_fee_bps("okx", default_fee_bps=12.5) == 12.5


def test_env_override_takes_priority(monkeypatch):
    monkeypatch.setenv("EXCHANGE_TAKER_FEE_BPS_KRAKEN", "16.0")
    assert get_taker_fee_bps("kraken", default_fee_bps=10.0) == 16.0


def test_parse_monitored_triangles_empty_string():
    assert _parse_monitored_triangles("") == []


def test_parse_monitored_triangles_single_entry():
    triangles = _parse_monitored_triangles("USDT:BTC:ETH:binance")
    assert triangles == [TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="ETH")]


def test_parse_monitored_triangles_multiple_entries():
    triangles = _parse_monitored_triangles("USDT:BTC:ETH:binance,USDT:BTC:SOL:binance")
    assert triangles == [
        TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="ETH"),
        TriangleConfig(exchange="binance", quote="USDT", bridge="BTC", target="SOL"),
    ]


def test_parse_monitored_triangles_rejects_wrong_field_count():
    with pytest.raises(ValueError):
        _parse_monitored_triangles("USDT:BTC:binance")
