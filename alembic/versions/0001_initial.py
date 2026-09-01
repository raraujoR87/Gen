"""initial schema: users, exchange_accounts, arbitrage_executions

Mirrors db/schema.sql exactly.

Revision ID: 0001
Revises:
Create Date: 2026-08-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "exchange_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("exchange_name", sa.String(50), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("encrypted_api_secret", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_table(
        "arbitrage_executions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("buy_exchange", sa.String(50), nullable=False),
        sa.Column("sell_exchange", sa.String(50), nullable=False),
        sa.Column("gross_spread_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("net_spread_pct", sa.Numeric(6, 4), nullable=False),
        sa.Column("executed_volume_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("realized_pnl_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("ml_confidence_score", sa.Numeric(4, 3), nullable=False),
        # 'SUCCESS', 'PARTIAL_FILL', 'HEDGED', 'REJECTED'
        sa.Column("execution_status", sa.String(30), nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
        ),
    )

    op.create_index(
        "idx_executions_user_time",
        "arbitrage_executions",
        ["user_id", sa.text("executed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_executions_user_time", table_name="arbitrage_executions")
    op.drop_table("arbitrage_executions")
    op.drop_table("exchange_accounts")
    op.drop_table("users")
