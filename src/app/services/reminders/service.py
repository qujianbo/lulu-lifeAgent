from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder
from app.repositories import ReminderRepository
from app.services.reminders.parser import DEFAULT_TIMEZONE, parse_reminder_text


@dataclass(frozen=True)
class ReminderCreateResult:
    status: str
    message: str
    reminder: Reminder | None = None
    needs_clarification: bool = False


class ReminderService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = ReminderRepository(session)

    async def create_from_text(
        self,
        *,
        user_id: int,
        text: str,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> ReminderCreateResult:
        parsed = parse_reminder_text(text, timezone=timezone)
        if parsed.needs_clarification:
            return ReminderCreateResult(
                status="needs_clarification",
                message="我还需要知道具体时间和提醒事项。",
                needs_clarification=True,
            )

        reminder = await self.repository.create(
            user_id=user_id,
            title=parsed.title,
            content=text,
            scheduled_at=parsed.scheduled_at,
            timezone=timezone,
            extra_metadata={
                "original_text": text,
                "time_text": parsed.time_text,
                "source": "local_agent",
            },
        )
        return ReminderCreateResult(
            status="created",
            message="提醒已创建。",
            reminder=reminder,
        )

    async def list_active(self, *, user_id: int, limit: int = 20) -> list[Reminder]:
        return await self.repository.list_active(user_id=user_id, limit=limit)
