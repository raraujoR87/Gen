"""Tests for backend.config.get_taker_fee_bps."""
from __future__ import annotations

from backend.config import get_taker_fee_bps


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
