"""beta auth tables

Revision ID: 20260614_0002
Revises: 20260608_0001
Create Date: 2026-06-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260614_0002"
down_revision: str | None = "20260608_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beta_users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beta_users")),
        sa.UniqueConstraint("username", name=op.f("uq_beta_users_username")),
    )
    # user_id is a logical reference to users.id; application services enforce it.
    op.create_index("ix_beta_users_status", "beta_users", ["status"])
    op.create_index("ix_beta_users_user_id", "beta_users", ["user_id"])

    op.create_table(
        "beta_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_beta_sessions")),
        sa.UniqueConstraint(
            "session_token_hash",
            name=op.f("uq_beta_sessions_session_token_hash"),
        ),
    )
    # session user_id points to beta_users.id logically; no database FK by design.
    op.create_index("ix_beta_sessions_expires_at", "beta_sessions", ["expires_at"])
    op.create_index("ix_beta_sessions_user_id", "beta_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_beta_sessions_user_id", table_name="beta_sessions")
    op.drop_index("ix_beta_sessions_expires_at", table_name="beta_sessions")
    op.drop_table("beta_sessions")
    op.drop_index("ix_beta_users_user_id", table_name="beta_users")
    op.drop_index("ix_beta_users_status", table_name="beta_users")
    op.drop_table("beta_users")
