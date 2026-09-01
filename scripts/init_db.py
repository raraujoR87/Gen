"""Create all tables directly from the SQLAlchemy models, bypassing Alembic.

alembic/versions/0001_initial.py is Postgres-specific (native UUID column
type, the uuid-ossp extension, NOW() server defaults) and does not run
against SQLite. backend.db.models already supports both (see its GUID
TypeDecorator), so for a local SQLite setup this script — using
Base.metadata.create_all, the same mechanism tests/conftest.py uses for
the in-memory test database — is the right tool instead of `alembic
upgrade head`.

For a real Postgres database, keep using `alembic upgrade head` so schema
changes stay tracked as migrations; this script is for local SQLite only.

Usage:
    DATABASE_URL=sqlite+aiosqlite:///./local.db python scripts/init_db.py
"""
from __future__ import annotations

import asyncio
import os
import sys

# Make the repo root importable so `backend.*` resolves regardless of cwd,
# matching alembic/env.py's approach.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.models import Base
from backend.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"Tables created (via SQLAlchemy metadata) at {engine.url}")


if __name__ == "__main__":
    asyncio.run(main())
