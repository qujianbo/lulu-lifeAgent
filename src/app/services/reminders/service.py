import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder
from app.repositories import ReminderRepository, ScheduledJobRepository
from app.services.reminders.parser import DEFAULT_TIMEZONE, parse_reminder_text


@dataclass(frozen=True)
class ReminderCreateResult:
    status: str
    message: str
    reminder: Reminder | None = None
    needs_clarification: bool = False


@dataclass(frozen=True)
class ReminderMutationResult:
    status: str
    message: str
    reminder: Reminder | None = None
    candidates: list[Reminder] | None = None
    needs_confirmation: bool = False


class ReminderService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = ReminderRepository(session)
        self.scheduled_jobs = ScheduledJobRepository(session)

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
        await self.scheduled_jobs.create_reminder_job(reminder=reminder)
        return ReminderCreateResult(
            status="created",
            message="提醒已创建。",
            reminder=reminder,
        )

    async def list_active(self, *, user_id: int, limit: int = 20) -> list[Reminder]:
        return await self.repository.list_active(user_id=user_id, limit=limit)

    async def complete_from_text(self, *, user_id: int, text: str) -> ReminderMutationResult:
        reminder = await self._resolve_one_reminder(user_id=user_id, text=text)
        if isinstance(reminder, list):
            return ReminderMutationResult(
                status="needs_confirmation",
                message="找到多个可能的提醒，需要指定要完成哪一个。",
                candidates=reminder,
                needs_confirmation=True,
            )
        if reminder is None:
            return ReminderMutationResult(status="not_found", message="没有找到可完成的提醒。")
        updated = await self.repository.mark_completed(reminder_id=reminder.id, user_id=user_id)
        await self.scheduled_jobs.cancel_pending_by_ref(
            job_type="reminder_due",
            ref_type="reminder",
            ref_id=reminder.id,
        )
        return ReminderMutationResult(status="completed", message="提醒已完成。", reminder=updated)

    async def delete_from_text(self, *, user_id: int, text: str) -> ReminderMutationResult:
        reminder = await self._resolve_one_reminder(user_id=user_id, text=text)
        if isinstance(reminder, list):
            return ReminderMutationResult(
                status="needs_confirmation",
                message="找到多个可能的提醒，需要指定要删除哪一个。",
                candidates=reminder,
                needs_confirmation=True,
            )
        if reminder is None:
            return ReminderMutationResult(status="not_found", message="没有找到可删除的提醒。")
        updated = await self.repository.soft_delete(reminder_id=reminder.id, user_id=user_id)
        await self.scheduled_jobs.cancel_pending_by_ref(
            job_type="reminder_due",
            ref_type="reminder",
            ref_id=reminder.id,
        )
        return ReminderMutationResult(status="deleted", message="提醒已删除。", reminder=updated)

    async def _resolve_one_reminder(
        self,
        *,
        user_id: int,
        text: str,
    ) -> Reminder | list[Reminder] | None:
        reminder_id = _extract_id(text)
        if reminder_id is not None:
            return await self.repository.get_active(reminder_id=reminder_id, user_id=user_id)

        reminders = await self.repository.list_active(user_id=user_id, limit=20)
        keyword = _extract_keyword(text)
        if keyword:
            reminders = [
                item
                for item in reminders
                if keyword in item.title or (item.content and keyword in item.content)
            ]
        if len(reminders) == 1:
            return reminders[0]
        if len(reminders) > 1:
            return reminders
        return None


def _extract_id(text: str) -> int | None:
    match = re.search(r"(?:#|编号|id|ID)\s*(\d+)", text)
    return int(match.group(1)) if match else None


def _extract_keyword(text: str) -> str:
    keyword = re.sub(r"(完成|做完|已办|办完|删除|取消|删掉|提醒|待办|编号|id|ID|#|\d+)", "", text)
    return keyword.strip(" ，。,.")
