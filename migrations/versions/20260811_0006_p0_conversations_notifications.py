"""P0 conversations, in-app notifications and reminder cancellation

Revision ID: 20260811_0006
Revises: 20260731_0005
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260811_0006"
down_revision: str | None = "20260731_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_uuid", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint("conversation_uuid", name=op.f("uq_conversations_conversation_uuid")),
    )
    op.create_index(
        "ix_conversations_user_id_last_message_at",
        "conversations",
        ["user_id", "last_message_at"],
    )
    op.create_index("ix_conversations_user_id_status", "conversations", ["user_id", "status"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("related_entities", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id_created_at",
        "conversation_messages",
        ["conversation_id", "created_at"],
    )

    op.create_table(
        "in_app_notifications",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("related_entity_type", sa.String(length=64), nullable=True),
        sa.Column("related_entity_id", sa.BigInteger(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_in_app_notifications")),
    )
    op.create_index(
        "ix_in_app_notifications_user_id_created_at",
        "in_app_notifications",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_in_app_notifications_user_id_read_at",
        "in_app_notifications",
        ["user_id", "read_at"],
    )
    op.add_column("reminders", sa.Column("cancelled_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("reminders", "cancelled_at")
    op.drop_index("ix_in_app_notifications_user_id_read_at", table_name="in_app_notifications")
    op.drop_index("ix_in_app_notifications_user_id_created_at", table_name="in_app_notifications")
    op.drop_table("in_app_notifications")
    op.drop_index(
        "ix_conversation_messages_conversation_id_created_at",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_user_id_status", table_name="conversations")
    op.drop_index("ix_conversations_user_id_last_message_at", table_name="conversations")
    op.drop_table("conversations")
