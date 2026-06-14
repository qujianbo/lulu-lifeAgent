"""beta feedback table

Revision ID: 20260614_0003
Revises: 20260614_0002
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260614_0003"
down_revision: str | None = "20260614_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beta_feedback",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("beta_user_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beta_feedback")),
    )
    # user_id and beta_user_id are logical references; service code controls ownership.
    op.create_index(
        "ix_beta_feedback_user_id_created_at",
        "beta_feedback",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_beta_feedback_status_created_at",
        "beta_feedback",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_beta_feedback_status_created_at", table_name="beta_feedback")
    op.drop_index("ix_beta_feedback_user_id_created_at", table_name="beta_feedback")
    op.drop_table("beta_feedback")
