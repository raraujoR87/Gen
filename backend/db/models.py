"""SQLAlchemy 2.0 declarative models mirroring ``db/schema.sql`` exactly.

Column names, types, defaults, FKs, and the composite index on
``arbitrage_executions(user_id, executed_at DESC)`` all match the reference
schema in ``db/schema.sql``. Do not let this drift from that file — it is
the shared contract other units read.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator, CHAR
import uuid as _uuid


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses Postgres's native UUID type when available (matching
    ``db/schema.sql``'s ``UUID`` columns), and falls back to a
    CHAR(36) representation on backends without native UUID support
    (e.g. SQLite, used by the in-memory test suite).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID as PG_UUID

            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, _uuid.UUID):
            return str(_uuid.UUID(str(value)))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, _uuid.UUID):
            return value
        return _uuid.UUID(str(value))


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    exchange_accounts: Mapped[list["ExchangeAccount"]] = relationship(
        "ExchangeAccount",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    arbitrage_executions: Mapped[list["ArbitrageExecution"]] = relationship(
        "ArbitrageExecution",
        back_populates="user",
    )


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE")
    )
    exchange_name: Mapped[str] = mapped_column(String(50), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_api_secret: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="exchange_accounts")


class ArbitrageExecution(Base):
    __tablename__ = "arbitrage_executions"
    __table_args__ = (
        Index(
            "idx_executions_user_time",
            "user_id",
            "executed_at",
            postgresql_ops={"executed_at": "DESC"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id")
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    buy_exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    sell_exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    gross_spread_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    net_spread_pct: Mapped[float] = mapped_column(Numeric(6, 4), nullable=False)
    executed_volume_usd: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    realized_pnl_usd: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    ml_confidence_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    # 'SUCCESS', 'PARTIAL_FILL', 'HEDGED', 'REJECTED' — see backend.schemas.ExecutionStatus
    execution_status: Mapped[str] = mapped_column(String(30), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="arbitrage_executions")
