"""agent memory events

Revision ID: 20260731_0005
Revises: 20260615_0004
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0005"
down_revision: str | None = "20260615_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_memory_id", sa.String(length=128), nullable=True),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_memory_events")),
    )
    # user_id is a logical reference to users.id; no database FK by design.
    op.create_index(
        "ix_agent_memory_events_event_type_status",
        "agent_memory_events",
        ["event_type", "status"],
    )
    op.create_index(
        "ix_agent_memory_events_provider_memory_id",
        "agent_memory_events",
        ["provider_memory_id"],
    )
    op.create_index(
        "ix_agent_memory_events_user_id_created_at",
        "agent_memory_events",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_memory_events_user_id_created_at",
        table_name="agent_memory_events",
    )
    op.drop_index(
        "ix_agent_memory_events_provider_memory_id",
        table_name="agent_memory_events",
    )
    op.drop_index(
        "ix_agent_memory_events_event_type_status",
        table_name="agent_memory_events",
    )
    op.drop_table("agent_memory_events")
