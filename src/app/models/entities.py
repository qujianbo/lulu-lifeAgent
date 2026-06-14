from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BigIntPrimaryKeyMixin, TimestampMixin


class User(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "public_user_id >= 10000000000000 AND public_user_id <= 99999999999999",
            name="public_user_id_14_digits",
        ),
        Index("ix_users_status", "status"),
        Index("ix_users_last_active_at", "last_active_at"),
    )

    public_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    wechat_openid: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    subscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BetaUser(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "beta_users"
    __table_args__ = (
        Index("ix_beta_users_status", "status"),
        Index("ix_beta_users_user_id", "user_id"),
    )

    # Logical reference to users.id; the beta account is only an auth wrapper.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="tester")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    remark: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BetaSession(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "beta_sessions"
    __table_args__ = (
        Index("ix_beta_sessions_user_id", "user_id"),
        Index("ix_beta_sessions_expires_at", "expires_at"),
    )

    # Logical reference to beta_users.id.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BetaFeedback(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "beta_feedback"
    __table_args__ = (
        Index("ix_beta_feedback_user_id_created_at", "user_id", "created_at"),
        Index("ix_beta_feedback_status_created_at", "status", "created_at"),
    )

    # Logical reference to users.id; feedback follows the business user identity.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    beta_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_url: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class IdSequence(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "id_sequences"

    sequence_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    current_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class UserProfile(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        Index(
            "uq_user_profiles_user_id_profile_key_active",
            "user_id",
            "profile_key",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        Index("ix_user_profiles_user_id_status", "user_id", "status"),
        Index("ix_user_profiles_profile_key", "profile_key"),
    )

    # Logical reference to users.id; consistency is enforced in the service layer.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    profile_key: Mapped[str] = mapped_column(String(128), nullable=False)
    profile_value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False, default="string")
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="user_explicit")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), default=Decimal("1.000"))
    # The database column is named "metadata"; the Python attribute avoids
    # colliding with SQLAlchemy's reserved Base.metadata attribute.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageLog(BigIntPrimaryKeyMixin, Base):
    __tablename__ = "message_logs"
    __table_args__ = (
        Index("ix_message_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_message_logs_agent_intent_created_at", "agent_intent", "created_at"),
        Index("ix_message_logs_status_created_at", "status", "created_at"),
        Index("ix_message_logs_wechat_msg_id", "wechat_msg_id"),
    )

    message_uuid: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), unique=True)
    # Logical reference to users.id for messages that can be matched to a user.
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    wechat_msg_id: Mapped[str | None] = mapped_column(String(128))
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    message_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_summary: Mapped[str | None] = mapped_column(Text)
    agent_intent: Mapped[str | None] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(128))
    tool_status: Mapped[str | None] = mapped_column(String(32))
    llm_provider: Mapped[str | None] = mapped_column(String(64))
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Reminder(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reminders"
    __table_args__ = (
        Index("ix_reminders_user_id_status", "user_id", "status"),
        Index("ix_reminders_user_id_scheduled_at", "user_id", "scheduled_at"),
        Index("ix_reminders_next_trigger_at_status", "next_trigger_at", "status"),
        Index("ix_reminders_reminder_type", "reminder_type"),
    )

    reminder_uuid: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), unique=True)
    # Logical reference to users.id; database foreign keys are intentionally avoided.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    reminder_type: Mapped[str] = mapped_column(String(32), nullable=False, default="reminder")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    repeat_rule: Mapped[str | None] = mapped_column(Text)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # Logical reference to message_logs.id for tracing the originating request.
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    # Stores original natural-language time text and extracted slots for debugging.
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LifeRecord(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "life_records"
    __table_args__ = (
        Index(
            "ix_life_records_user_id_record_type_recorded_at",
            "user_id",
            "record_type",
            "recorded_at",
        ),
        Index("ix_life_records_user_id_recorded_at", "user_id", "recorded_at"),
    )

    record_uuid: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), unique=True)
    # Logical reference to users.id; service code validates ownership.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str | None] = mapped_column(String(16), default="CNY")
    tags: Mapped[list[str] | None] = mapped_column(JSONB)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Logical reference to message_logs.id for audit/debug lookup.
    source_message_id: Mapped[int | None] = mapped_column(BigInteger)
    extra_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Subscription(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("ix_subscriptions_user_id_status", "user_id", "status"),
        Index(
            "ix_subscriptions_user_id_subscription_type_status",
            "user_id",
            "subscription_type",
            "status",
        ),
        Index("ix_subscriptions_next_push_at_status", "next_push_at", "status"),
    )

    subscription_uuid: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), unique=True)
    # Logical reference to users.id; service code validates the user before writes.
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subscription_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_rule: Mapped[str] = mapped_column(Text, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_push_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WechatToken(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wechat_tokens"
    __table_args__ = (
        UniqueConstraint("app_id", "token_type", name="uq_wechat_tokens_app_id_token_type"),
    )

    app_id: Mapped[str] = mapped_column(String(128), nullable=False)
    token_type: Mapped[str] = mapped_column(String(64), nullable=False, default="access_token")
    token_value: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(Text)


class ScheduledJob(BigIntPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        Index("ix_scheduled_jobs_next_run_at_status", "next_run_at", "status"),
        Index("ix_scheduled_jobs_job_type_status", "job_type", "status"),
        Index("ix_scheduled_jobs_user_id_status", "user_id", "status"),
        Index("ix_scheduled_jobs_ref_type_ref_id", "ref_type", "ref_id"),
    )

    job_uuid: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), unique=True)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Logical reference to users.id for user-scoped jobs.
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    ref_type: Mapped[str | None] = mapped_column(String(64))
    ref_id: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
