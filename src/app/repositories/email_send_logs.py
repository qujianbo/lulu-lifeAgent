from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailSendLog


class EmailSendLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        email: str,
        email_type: str,
        recipient: str,
        subject: str,
        status: str,
        job_id: int | None = None,
        provider: str = "smtp",
        provider_message_id: str | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
        now: datetime | None = None,
    ) -> EmailSendLog:
        # Record every send attempt so retry behavior is auditable.
        now = now or datetime.now(UTC)
        item = EmailSendLog(
            job_id=job_id,
            user_id=user_id,
            email=email,
            email_type=email_type,
            recipient=recipient,
            subject=subject[:255],
            status=status,
            provider=provider,
            provider_message_id=provider_message_id,
            error_message=error_message[:2000] if error_message else None,
            latency_ms=latency_ms,
            created_at=now,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        limit: int = 50,
    ) -> list[EmailSendLog]:
        query: Select[tuple[EmailSendLog]] = (
            select(EmailSendLog).order_by(EmailSendLog.id.desc()).limit(limit)
        )
        if user_id is not None:
            query = query.where(EmailSendLog.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())
