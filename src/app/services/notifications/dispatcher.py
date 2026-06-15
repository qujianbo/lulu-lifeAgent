from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import ScheduledJob
from app.repositories import EmailSendLogRepository
from app.services.notifications.email import EmailNotifier


class NotificationDispatcher:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.logs = EmailSendLogRepository(session)
        self.email = EmailNotifier(settings)

    async def send_email_job(self, *, job: ScheduledJob, now: datetime | None = None) -> bool:
        # Dispatch one scheduled email job and record the attempt.
        now = now or datetime.now(UTC)
        payload = job.payload or {}
        recipient = str(payload.get("email") or "")
        subject = str(payload.get("subject") or "生活管家通知")
        content = str(payload.get("content") or "")
        email_type = _email_type_from_job(job)
        result = self.email.send_email(
            to_email=recipient,
            subject=subject,
            text_content=content,
        )
        await self.logs.create(
            job_id=job.id,
            user_id=job.user_id or 0,
            email=recipient,
            email_type=email_type,
            recipient=recipient,
            subject=subject,
            status=result.status,
            error_message=result.error_message,
            latency_ms=result.latency_ms,
            now=now,
        )
        if result.status == "success":
            return True
        raise RuntimeError(result.error_message or "email send failed")


def next_retry_at(*, retry_count: int, now: datetime) -> datetime:
    # retry_count is the value after the failed attempt is recorded.
    delays = [5, 15, 30]
    index = max(0, min(retry_count - 1, len(delays) - 1))
    return now + timedelta(minutes=delays[index])


def _email_type_from_job(job: ScheduledJob) -> str:
    if job.job_type == "email_daily_briefing":
        return "daily_briefing"
    if job.job_type == "email_reminder_due":
        return "reminder_due"
    if job.job_type == "email_test":
        return "test"
    return job.job_type
