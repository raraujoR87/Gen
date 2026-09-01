from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "test-secret")

import jwt
import pytest
from fastapi.testclient import TestClient

import backend.api.rate_limit as rate_limit_module
from backend.schemas import ArbitrageSignal, ExecutionStatus, TradeExecutionResult

# tests/conftest.py installs stub backend.ml.inference / backend.execution.*
# modules before this import executes, so backend.api.main can be imported
# in isolation even though the real ML/execution units don't exist yet.
from backend.api.main import app

JWT_SECRET = os.environ["JWT_SECRET"]
USER_ID = "user-123"


def make_token(user_id: str = USER_ID, secret: str = JWT_SECRET) -> str:
    return jwt.encode({"sub": user_id}, secret, algorithm="HS256")


def auth_headers(user_id: str = USER_ID, secret: str = JWT_SECRET) -> dict:
    return {"Authorization": f"Bearer {make_token(user_id, secret)}"}


VALID_PAYLOAD = {
    "user_id": USER_ID,
    "symbol": "BTC/USDT",
    "exchange_buy": "binance",
    "exchange_sell": "kraken",
    "capital_allocation_usd": 25.0,
    "min_alpha_bps": 15.0,
    "trading_mode": "testnet",
}


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rate_limit_module.limiter.reset()
    yield
    rate_limit_module.limiter.reset()


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_process_arbitrage_intent_requires_auth(client):
    resp = client.post("/process_arbitrage_intent", json=VALID_PAYLOAD)
    assert resp.status_code == 403 or resp.status_code == 401


def test_process_arbitrage_intent_rejects_invalid_jwt(client):
    resp = client.post(
        "/process_arbitrage_intent",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_process_arbitrage_intent_rejects_wrong_secret(client):
    resp = client.post(
        "/process_arbitrage_intent",
        json=VALID_PAYLOAD,
        headers=auth_headers(secret="wrong-secret"),
    )
    assert resp.status_code == 401


def test_process_arbitrage_intent_approved(client, monkeypatch):
    def fake_evaluate_spread(model, temporal, depth):
        return ArbitrageSignal(
            execution_probability=0.95,
            expected_alpha_bps=30.0,
            adverse_hazard=0.05,
        )

    def fake_should_execute(*, net_alpha_bps, signal, limits, trade_notional_usd=None, daily_notional_used_usd=0.0):
        return True, None

    async def fake_dispatch_orders(*, request, signal):
        return TradeExecutionResult(
            status=ExecutionStatus.SUCCESS,
            buy_exchange=request.exchange_buy,
            sell_exchange=request.exchange_sell,
            symbol=request.symbol,
            executed_volume_usd=request.capital_allocation_usd,
            gross_spread_pct=0.35,
            net_spread_pct=0.30,
            realized_pnl_usd=0.075,
            ml_confidence_score=signal.execution_probability,
        )

    import backend.execution.broken_leg as broken_leg_module
    import backend.execution.decision as decision_module
    import backend.ml.inference as ml_inference_module

    monkeypatch.setattr(ml_inference_module, "evaluate_spread", fake_evaluate_spread)
    monkeypatch.setattr(decision_module, "should_execute", fake_should_execute)
    monkeypatch.setattr(broken_leg_module, "dispatch_orders", fake_dispatch_orders)

    resp = client.post(
        "/process_arbitrage_intent",
        json=VALID_PAYLOAD,
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ORDER_DISPATCHED"
    assert body["reason"] is None
    assert body["allocated_capital"] == VALID_PAYLOAD["capital_allocation_usd"]
    assert body["metrics"]["execution_probability"] == 0.95


def test_process_arbitrage_intent_rejected(client, monkeypatch):
    def fake_evaluate_spread(model, temporal, depth):
        return ArbitrageSignal(
            execution_probability=0.4,
            expected_alpha_bps=5.0,
            adverse_hazard=0.5,
        )

    def fake_should_execute(*, net_alpha_bps, signal, limits, trade_notional_usd=None, daily_notional_used_usd=0.0):
        return False, "execution_probability below threshold"

    import backend.execution.decision as decision_module
    import backend.ml.inference as ml_inference_module

    monkeypatch.setattr(ml_inference_module, "evaluate_spread", fake_evaluate_spread)
    monkeypatch.setattr(decision_module, "should_execute", fake_should_execute)

    resp = client.post(
        "/process_arbitrage_intent",
        json=VALID_PAYLOAD,
        headers=auth_headers(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SIGNAL_REJECTED"
    assert body["reason"] == "execution_probability below threshold"


def test_process_arbitrage_intent_user_id_mismatch(client):
    payload = dict(VALID_PAYLOAD, user_id="someone-else")
    resp = client.post(
        "/process_arbitrage_intent",
        json=payload,
        headers=auth_headers(user_id=USER_ID),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "SIGNAL_REJECTED"
    assert "mismatch" in body["reason"]


def test_rate_limit_exceeded(client, monkeypatch):
    def fake_evaluate_spread(model, temporal, depth):
        return ArbitrageSignal(execution_probability=0.4, expected_alpha_bps=5.0, adverse_hazard=0.5)

    def fake_should_execute(*, net_alpha_bps, signal, limits, trade_notional_usd=None, daily_notional_used_usd=0.0):
        return False, "rejected"

    import backend.execution.decision as decision_module
    import backend.ml.inference as ml_inference_module

    monkeypatch.setattr(ml_inference_module, "evaluate_spread", fake_evaluate_spread)
    monkeypatch.setattr(decision_module, "should_execute", fake_should_execute)

    monkeypatch.setattr(rate_limit_module.limiter, "capacity", 2)
    rate_limit_module.limiter.reset()

    headers = auth_headers()
    for _ in range(2):
        resp = client.post("/process_arbitrage_intent", json=VALID_PAYLOAD, headers=headers)
        assert resp.status_code == 200

    resp = client.post("/process_arbitrage_intent", json=VALID_PAYLOAD, headers=headers)
    assert resp.status_code == 429
