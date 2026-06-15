"""email contacts and send logs

Revision ID: 20260615_0004
Revises: 20260614_0003
Create Date: 2026-06-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_0004"
down_revision: str | None = "20260614_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_contacts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("contact_type", sa.String(length=32), nullable=False),
        sa.Column("contact_value", sa.String(length=255), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_contacts")),
    )
    # user_id is a logical reference to users.id; no database FK by design.
    op.create_index(
        "ix_user_contacts_contact_type_status",
        "user_contacts",
        ["contact_type", "status"],
    )
    op.create_index(
        "ix_user_contacts_user_id_contact_type",
        "user_contacts",
        ["user_id", "contact_type"],
    )

    op.create_table(
        "email_send_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("email_type", sa.String(length=64), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_message_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_send_logs")),
    )
    # job_id is a logical reference to scheduled_jobs.id; no database FK by design.
    op.create_index("ix_email_send_logs_job_id", "email_send_logs", ["job_id"])
    op.create_index(
        "ix_email_send_logs_status_created_at",
        "email_send_logs",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_email_send_logs_user_id_created_at",
        "email_send_logs",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_send_logs_user_id_created_at", table_name="email_send_logs")
    op.drop_index("ix_email_send_logs_status_created_at", table_name="email_send_logs")
    op.drop_index("ix_email_send_logs_job_id", table_name="email_send_logs")
    op.drop_table("email_send_logs")
    op.drop_index("ix_user_contacts_user_id_contact_type", table_name="user_contacts")
    op.drop_index("ix_user_contacts_contact_type_status", table_name="user_contacts")
    op.drop_table("user_contacts")
