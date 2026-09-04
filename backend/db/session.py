"""Async SQLAlchemy engine/session wiring.

Other units (e.g. the API gateway) depend on this module's public surface:
``get_db_session`` as a FastAPI dependency yielding an ``AsyncSession``.
Keep that signature simple and stable.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Loads .env (if present) into os.environ before DATABASE_URL is read below.
# This is the first backend module every entry point (backend.api.main,
# scripts/init_db.py, run_local.bat) ends up importing, so this is also
# where every other os.environ.get(...) call in the app (backend.config,
# etc.) picks up .env values — a no-op when no .env file exists, e.g. in
# CI, where DATABASE_URL is set directly as a real environment variable.
load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://user:password@localhost:5432/arbitrage"
)

engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_pre_ping=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a request-scoped AsyncSession.

    Usage:
        @app.get("/x")
        async def handler(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        yield session
