"""Simple async CRUD helpers over the models in ``backend.db.models``."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ArbitrageExecution, ExchangeAccount, User
from backend.schemas import TradeExecutionResult


async def create_user(session: AsyncSession, email: str) -> User:
    """Create and persist a new user."""
    user = User(email=email)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def get_or_create_user_by_email(session: AsyncSession, email: str) -> User:
    """Return the existing user with this email, creating one if needed.

    User.email is unique, so the local runner (which bootstraps the same
    LOCAL_USER_EMAIL on every process restart) needs this instead of
    create_user, which would violate that constraint after the first run.
    """
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None:
        return user
    return await create_user(session, email)


async def create_exchange_account(
    session: AsyncSession,
    user_id: uuid.UUID,
    exchange_name: str,
    encrypted_api_key: str,
    encrypted_api_secret: str,
    is_active: bool = True,
) -> ExchangeAccount:
    """Create and persist a new exchange account linked to a user."""
    account = ExchangeAccount(
        user_id=user_id,
        exchange_name=exchange_name,
        encrypted_api_key=encrypted_api_key,
        encrypted_api_secret=encrypted_api_secret,
        is_active=is_active,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def record_execution(
    session: AsyncSession,
    result: TradeExecutionResult,
    user_id: uuid.UUID,
) -> None:
    """Persist a completed (or rejected) trade execution result."""
    execution = ArbitrageExecution(
        user_id=user_id,
        symbol=result.symbol,
        buy_exchange=result.buy_exchange,
        sell_exchange=result.sell_exchange,
        gross_spread_pct=result.gross_spread_pct,
        net_spread_pct=result.net_spread_pct,
        executed_volume_usd=result.executed_volume_usd,
        realized_pnl_usd=result.realized_pnl_usd,
        ml_confidence_score=result.ml_confidence_score,
        execution_status=result.status.value,
    )
    session.add(execution)
    await session.commit()


async def get_recent_executions(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 20
) -> list[ArbitrageExecution]:
    """Return a user's most recent executions, newest first."""
    stmt = (
        select(ArbitrageExecution)
        .where(ArbitrageExecution.user_id == user_id)
        .order_by(ArbitrageExecution.executed_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
