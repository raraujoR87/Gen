"""Smoke tests for the shared fixtures in tests/conftest.py themselves —
not part of the cross-unit integration spec, just verifying the CI
infrastructure (db engine/session, JWT, risk limits) works standalone before
any other unit's code exists.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text


def test_default_risk_limits_are_conservative(default_risk_limits):
    assert default_risk_limits.kill_switch_engaged is False
    assert default_risk_limits.max_notional_usd_per_trade > 0


def test_valid_jwt_roundtrips(valid_jwt, jwt_secret, test_user_id):
    import jwt as pyjwt

    payload = pyjwt.decode(valid_jwt, jwt_secret, algorithms=["HS256"])
    assert payload["sub"] == test_user_id


@pytest.mark.asyncio
async def test_db_session_executes_a_query(db_session):
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1
