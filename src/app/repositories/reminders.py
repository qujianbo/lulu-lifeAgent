from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder


class ReminderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        title: str,
        content: str | None = None,
        scheduled_at: datetime | None = None,
        timezone: str = "Asia/Shanghai",
        extra_metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> Reminder:
        # Create one active reminder; scheduler jobs will be added in the push stage.
        now = now or datetime.now(UTC)
        reminder = Reminder(
            reminder_uuid=uuid4(),
            user_id=user_id,
            title=title[:200],
            content=content,
            reminder_type="reminder",
            scheduled_at=scheduled_at,
            timezone=timezone,
            next_trigger_at=scheduled_at,
            status="active",
            extra_metadata=extra_metadata,
            created_at=now,
            updated_at=now,
        )
        self.session.add(reminder)
        await self.session.flush()
        return reminder

    async def list_active(
        self,
        *,
        user_id: int,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[Reminder]:
        now = now or datetime.now(UTC)
        query: Select[tuple[Reminder]] = (
            select(Reminder)
            .where(
                Reminder.user_id == user_id,
                Reminder.status == "active",
                Reminder.deleted_at.is_(None),
            )
            .order_by(Reminder.next_trigger_at.is_(None), Reminder.next_trigger_at, Reminder.id)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def mark_completed(
        self,
        *,
        reminder_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> Reminder | None:
        # Completion keeps the reminder row for history and future audit.
        now = now or datetime.now(UTC)
        reminder = await self.get_active(reminder_id=reminder_id, user_id=user_id)
        if reminder is None:
            return None
        reminder.status = "completed"
        reminder.completed_at = now
        reminder.updated_at = now
        return reminder

    async def soft_delete(
        self,
        *,
        reminder_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> Reminder | None:
        now = now or datetime.now(UTC)
        reminder = await self.get_active(reminder_id=reminder_id, user_id=user_id)
        if reminder is None:
            return None
        reminder.status = "deleted"
        reminder.deleted_at = now
        reminder.updated_at = now
        return reminder

    async def get_active(self, *, reminder_id: int, user_id: int) -> Reminder | None:
        result = await self.session.execute(
            select(Reminder).where(
                Reminder.id == reminder_id,
                Reminder.user_id == user_id,
                Reminder.status == "active",
                Reminder.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
