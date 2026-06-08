"""initial schema

Revision ID: 20260608_0001
Revises:
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260608_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_user_id", sa.BigInteger(), nullable=False),
        sa.Column("wechat_openid", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("subscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "public_user_id >= 10000000000000 AND public_user_id <= 99999999999999",
            name=op.f("ck_users_public_user_id_14_digits"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("public_user_id", name=op.f("uq_users_public_user_id")),
        sa.UniqueConstraint("wechat_openid", name=op.f("uq_users_wechat_openid")),
    )
    op.create_index(op.f("ix_users_last_active_at"), "users", ["last_active_at"])
    op.create_index(op.f("ix_users_status"), "users", ["status"])

    op.create_table(
        "id_sequences",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sequence_key", sa.String(length=128), nullable=False),
        sa.Column("current_value", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_id_sequences")),
        sa.UniqueConstraint("sequence_key", name=op.f("uq_id_sequences_sequence_key")),
    )

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("profile_key", sa.String(length=128), nullable=False),
        sa.Column("profile_value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profiles")),
    )
    # user_id is a logical reference to users.id; application services enforce it.
    op.create_index("ix_user_profiles_profile_key", "user_profiles", ["profile_key"])
    op.create_index("ix_user_profiles_user_id_status", "user_profiles", ["user_id", "status"])
    op.create_index(
        "uq_user_profiles_user_id_profile_key_active",
        "user_profiles",
        ["user_id", "profile_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    # Partial unique index: a user can have only one active value for a profile key,
    # while soft-deleted historical rows remain available for audit/debugging.

    op.create_table(
        "message_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("message_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("wechat_msg_id", sa.String(length=128), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("content_summary", sa.Text(), nullable=True),
        sa.Column("agent_intent", sa.String(length=64), nullable=True),
        sa.Column("tool_name", sa.String(length=128), nullable=True),
        sa.Column("tool_status", sa.String(length=32), nullable=True),
        sa.Column("llm_provider", sa.String(length=64), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_logs")),
        sa.UniqueConstraint("message_uuid", name=op.f("uq_message_logs_message_uuid")),
    )
    # user_id is nullable because some inbound events may be logged before user binding.
    op.create_index(
        "ix_message_logs_agent_intent_created_at",
        "message_logs",
        ["agent_intent", "created_at"],
    )
    op.create_index("ix_message_logs_status_created_at", "message_logs", ["status", "created_at"])
    op.create_index("ix_message_logs_user_id_created_at", "message_logs", ["user_id", "created_at"])
    op.create_index("ix_message_logs_wechat_msg_id", "message_logs", ["wechat_msg_id"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("reminder_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("reminder_type", sa.String(length=32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("repeat_rule", sa.Text(), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_trigger_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reminders")),
        sa.UniqueConstraint("reminder_uuid", name=op.f("uq_reminders_reminder_uuid")),
    )
    # user_id and source_message_id are logical references kept index-friendly.
    # Query paths used by the reminder scanner and user-facing reminder list.
    op.create_index(
        "ix_reminders_next_trigger_at_status",
        "reminders",
        ["next_trigger_at", "status"],
    )
    op.create_index("ix_reminders_reminder_type", "reminders", ["reminder_type"])
    op.create_index("ix_reminders_user_id_scheduled_at", "reminders", ["user_id", "scheduled_at"])
    op.create_index("ix_reminders_user_id_status", "reminders", ["user_id", "status"])

    op.create_table(
        "life_records",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("record_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("record_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_life_records")),
        sa.UniqueConstraint("record_uuid", name=op.f("uq_life_records_record_uuid")),
    )
    # Life records use logical references so imports and cleanup can stay flexible.
    op.create_index(
        "ix_life_records_user_id_record_type_recorded_at",
        "life_records",
        ["user_id", "record_type", "recorded_at"],
    )
    op.create_index(
        "ix_life_records_user_id_recorded_at",
        "life_records",
        ["user_id", "recorded_at"],
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("subscription_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("subscription_type", sa.String(length=64), nullable=False),
        sa.Column("schedule_rule", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_pushed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_push_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("subscription_uuid", name=op.f("uq_subscriptions_subscription_uuid")),
    )
    # user_id is a logical reference; active subscription ownership is service-checked.
    op.create_index(
        "ix_subscriptions_next_push_at_status",
        "subscriptions",
        ["next_push_at", "status"],
    )
    op.create_index(
        "ix_subscriptions_user_id_subscription_type_status",
        "subscriptions",
        ["user_id", "subscription_type", "status"],
    )
    op.create_index("ix_subscriptions_user_id_status", "subscriptions", ["user_id", "status"])

    op.create_table(
        "wechat_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("app_id", sa.String(length=128), nullable=False),
        sa.Column("token_type", sa.String(length=64), nullable=False),
        sa.Column("token_value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wechat_tokens")),
        sa.UniqueConstraint("app_id", "token_type", name="uq_wechat_tokens_app_id_token_type"),
    )
    op.create_index(op.f("ix_wechat_tokens_expires_at"), "wechat_tokens", ["expires_at"])

    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_uuid", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("ref_type", sa.String(length=64), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduled_jobs")),
        sa.UniqueConstraint("job_uuid", name=op.f("uq_scheduled_jobs_job_uuid")),
    )
    # The scheduler scans by next_run_at/status and uses ref_type/ref_id to cancel
    # jobs when the related reminder or subscription is cancelled.
    op.create_index("ix_scheduled_jobs_job_type_status", "scheduled_jobs", ["job_type", "status"])
    op.create_index(
        "ix_scheduled_jobs_next_run_at_status",
        "scheduled_jobs",
        ["next_run_at", "status"],
    )
    op.create_index("ix_scheduled_jobs_ref_type_ref_id", "scheduled_jobs", ["ref_type", "ref_id"])
    op.create_index("ix_scheduled_jobs_user_id_status", "scheduled_jobs", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_jobs_user_id_status", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_ref_type_ref_id", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_next_run_at_status", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_job_type_status", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")
    op.drop_index(op.f("ix_wechat_tokens_expires_at"), table_name="wechat_tokens")
    op.drop_table("wechat_tokens")
    op.drop_index("ix_subscriptions_user_id_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_user_id_subscription_type_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_next_push_at_status", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_life_records_user_id_recorded_at", table_name="life_records")
    op.drop_index("ix_life_records_user_id_record_type_recorded_at", table_name="life_records")
    op.drop_table("life_records")
    op.drop_index("ix_reminders_user_id_status", table_name="reminders")
    op.drop_index("ix_reminders_user_id_scheduled_at", table_name="reminders")
    op.drop_index("ix_reminders_reminder_type", table_name="reminders")
    op.drop_index("ix_reminders_next_trigger_at_status", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("ix_message_logs_wechat_msg_id", table_name="message_logs")
    op.drop_index("ix_message_logs_user_id_created_at", table_name="message_logs")
    op.drop_index("ix_message_logs_status_created_at", table_name="message_logs")
    op.drop_index("ix_message_logs_agent_intent_created_at", table_name="message_logs")
    op.drop_table("message_logs")
    op.drop_index("uq_user_profiles_user_id_profile_key_active", table_name="user_profiles")
    op.drop_index("ix_user_profiles_user_id_status", table_name="user_profiles")
    op.drop_index("ix_user_profiles_profile_key", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_table("id_sequences")
    op.drop_index(op.f("ix_users_status"), table_name="users")
    op.drop_index(op.f("ix_users_last_active_at"), table_name="users")
    op.drop_table("users")
