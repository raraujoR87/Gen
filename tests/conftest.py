"""Shared pytest fixtures for the backend test suite.

These fixtures are intentionally decoupled from the concrete implementations
of the other units (security/marketdata/ml/execution/api/db) — they only
depend on `backend.schemas` (the shared contract module) plus the standard
library / third-party test tooling, so they work today even though most of
`backend/*` is still empty stubs, and keep working once the other units land.

Design notes:
  - `DATABASE_URL` env var (set by CI to point at the `postgres` service) is
    honored when present; otherwise an in-memory async SQLite engine is used
    so the suite runs with zero external services for local/offline dev.
  - The FastAPI `TestClient` fixture is built lazily via `pytest.importorskip`
    so this file itself never fails to collect before `backend.api.main`
    exists.
"""
from __future__ import annotations

import datetime as dt
import os
import uuid

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def _test_database_url() -> str:
    """Resolve the async SQLAlchemy URL to use for tests.

    CI sets DATABASE_URL to point at the `postgres` service container
    (see .github/workflows/ci.yml). Locally, absent that env var, we fall
    back to an in-memory SQLite database via aiosqlite so the suite needs no
    external services.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        # Normalize a plain "postgresql://" into the asyncpg driver URL the
        # rest of the codebase (backend/db, unit 6) expects.
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    return "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def database_url() -> str:
    return _test_database_url()


@pytest_asyncio.fixture
async def db_engine(database_url):
    """A fresh async SQLAlchemy engine for the test database.

    Yields the engine; disposes it after the test. Schema creation is left
    to backend.db (unit 6) models via Base.metadata.create_all — tests that
    need tables should import those models with pytest.importorskip and
    create them explicitly, keeping this fixture free of a hard dependency
    on unit 6 existing yet.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """An AsyncSession bound to db_engine, for tests that talk to the DB directly."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        yield session


# ---------------------------------------------------------------------------
# API / HTTP test client
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """A FastAPI TestClient for backend.api.main:app.

    Skips (rather than fails) when the API app doesn't exist yet — unit 5
    is developed in parallel with this CI unit.
    """
    pytest.importorskip("backend.api.main", reason="backend.api.main not implemented yet")
    from fastapi.testclient import TestClient

    from backend.api.main import app

    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# Risk limits
# ---------------------------------------------------------------------------


@pytest.fixture
def default_risk_limits():
    """A conservative, default-valued RiskLimits for use across tests."""
    from backend.schemas import RiskLimits

    return RiskLimits()


# ---------------------------------------------------------------------------
# Auth / JWT
# ---------------------------------------------------------------------------


@pytest.fixture
def jwt_secret() -> str:
    return os.environ.get("JWT_SECRET", "test-secret-do-not-use-in-prod")


@pytest.fixture
def test_user_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def valid_jwt(jwt_secret, test_user_id) -> str:
    """A valid, non-expired JWT signed with jwt_secret for `test_user_id`.

    Uses the same claim shape (`sub`, `exp`, `iat`) that backend.security
    (unit 1) is expected to issue/verify — see docs/ARCHITECTURE.md section 2
    and .env.example (JWT_SECRET / JWT_ALGORITHM / JWT_EXPIRE_MINUTES).
    """
    import jwt as pyjwt

    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": test_user_id,
        "iat": now,
        "exp": now + dt.timedelta(minutes=int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))),
    }
    algorithm = os.environ.get("JWT_ALGORITHM", "HS256")
    return pyjwt.encode(payload, jwt_secret, algorithm=algorithm)


@pytest.fixture
def auth_headers(valid_jwt) -> dict:
    return {"Authorization": f"Bearer {valid_jwt}"}
