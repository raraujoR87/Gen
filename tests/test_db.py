"""Tests for backend/db/{models,repository}.py using an in-memory SQLite DB.

No Postgres required: create_async_engine("sqlite+aiosqlite:///:memory:")
plus Base.metadata.create_all exercises the same model/repository code
paths that run against Postgres in production.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.db.models import Base
from backend.db.repository import (
    create_exchange_account,
    create_user,
    get_recent_executions,
    record_execution,
)
from backend.schemas import ExecutionStatus, TradeExecutionResult


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_maker() as s:
        yield s

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user(session):
    user = await create_user(session, email="trader@example.com")

    assert user.id is not None
    assert user.email == "trader@example.com"
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_create_exchange_account(session):
    user = await create_user(session, email="trader2@example.com")

    account = await create_exchange_account(
        session,
        user_id=user.id,
        exchange_name="binance",
        encrypted_api_key="enc-key",
        encrypted_api_secret="enc-secret",
    )

    assert account.id is not None
    assert account.user_id == user.id
    assert account.exchange_name == "binance"
    assert account.is_active is True


@pytest.mark.asyncio
async def test_record_execution_and_get_recent(session):
    user = await create_user(session, email="trader3@example.com")

    result = TradeExecutionResult(
        status=ExecutionStatus.SUCCESS,
        buy_exchange="binance",
        sell_exchange="coinbase",
        symbol="BTC/USDT",
        executed_volume_usd=100.0,
        gross_spread_pct=0.25,
        net_spread_pct=0.18,
        realized_pnl_usd=1.5,
        ml_confidence_score=0.912,
    )

    await record_execution(session, result, user_id=user.id)

    rejected = TradeExecutionResult(
        status=ExecutionStatus.REJECTED,
        buy_exchange="kraken",
        sell_exchange="binance",
        symbol="ETH/USDT",
        executed_volume_usd=50.0,
        gross_spread_pct=0.05,
        net_spread_pct=0.01,
        realized_pnl_usd=0.0,
        ml_confidence_score=0.4,
        reason="below min_alpha_bps",
    )
    await record_execution(session, rejected, user_id=user.id)

    executions = await get_recent_executions(session, user_id=user.id, limit=10)

    assert len(executions) == 2
    # newest first
    assert executions[0].symbol == "ETH/USDT"
    assert executions[0].execution_status == "REJECTED"
    assert executions[1].symbol == "BTC/USDT"
    assert executions[1].execution_status == "SUCCESS"
    assert float(executions[1].realized_pnl_usd) == 1.5


@pytest.mark.asyncio
async def test_get_recent_executions_respects_limit(session):
    user = await create_user(session, email="trader4@example.com")

    for i in range(5):
        result = TradeExecutionResult(
            status=ExecutionStatus.SUCCESS,
            buy_exchange="binance",
            sell_exchange="coinbase",
            symbol=f"SYM{i}/USDT",
            executed_volume_usd=10.0,
            gross_spread_pct=0.1,
            net_spread_pct=0.05,
            realized_pnl_usd=0.1,
            ml_confidence_score=0.9,
        )
        await record_execution(session, result, user_id=user.id)

    executions = await get_recent_executions(session, user_id=user.id, limit=3)
    assert len(executions) == 3
