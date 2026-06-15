from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Reminder, ScheduledJob, Subscription


class ScheduledJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_reminder_job(
        self,
        *,
        reminder: Reminder,
        now: datetime | None = None,
    ) -> ScheduledJob:
        # Enqueue one reminder delivery job for scheduler polling.
        now = now or datetime.now(UTC)
        job = ScheduledJob(
            job_uuid=uuid4(),
            job_type="reminder_due",
            user_id=reminder.user_id,
            ref_type="reminder",
            ref_id=reminder.id,
            payload={
                "reminder_id": reminder.id,
                "title": reminder.title,
                "scheduled_at": reminder.scheduled_at.isoformat()
                if reminder.scheduled_at
                else None,
            },
            next_run_at=reminder.next_trigger_at or reminder.scheduled_at or now,
            retry_count=0,
            max_retries=3,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def create_subscription_job(
        self,
        *,
        subscription: Subscription,
        now: datetime | None = None,
    ) -> ScheduledJob:
        # Enqueue one subscription job; scheduler updates the next cycle after processing.
        now = now or datetime.now(UTC)
        existing = await self.get_pending_by_ref(
            job_type="briefing_due",
            ref_type="subscription",
            ref_id=subscription.id,
        )
        if existing is not None:
            existing.next_run_at = subscription.next_push_at or now
            existing.payload = {
                "subscription_id": subscription.id,
                "subscription_type": subscription.subscription_type,
                "preferences": subscription.preferences,
            }
            existing.updated_at = now
            await self.session.flush()
            return existing
        job = ScheduledJob(
            job_uuid=uuid4(),
            job_type="briefing_due",
            user_id=subscription.user_id,
            ref_type="subscription",
            ref_id=subscription.id,
            payload={
                "subscription_id": subscription.id,
                "subscription_type": subscription.subscription_type,
                "preferences": subscription.preferences,
            },
            next_run_at=subscription.next_push_at or now,
            retry_count=0,
            max_retries=3,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def create_email_job(
        self,
        *,
        user_id: int,
        email_type: str,
        email: str,
        subject: str,
        content: str,
        next_run_at: datetime,
        ref_type: str | None = None,
        ref_id: int | None = None,
        max_retries: int = 3,
        payload_extra: dict | None = None,
        now: datetime | None = None,
    ) -> ScheduledJob:
        # Enqueue one email delivery job while reusing the scheduler table.
        now = now or datetime.now(UTC)
        job_type = f"email_{email_type}"
        existing = None
        if ref_type is not None and ref_id is not None:
            existing = await self.get_pending_by_ref(
                job_type=job_type,
                ref_type=ref_type,
                ref_id=ref_id,
            )
        if existing is not None:
            existing.next_run_at = next_run_at
            existing.payload = {
                "email": email,
                "subject": subject,
                "content": content,
                **(payload_extra or {}),
            }
            existing.updated_at = now
            await self.session.flush()
            return existing
        job = ScheduledJob(
            job_uuid=uuid4(),
            job_type=job_type,
            user_id=user_id,
            ref_type=ref_type,
            ref_id=ref_id,
            payload={
                "email": email,
                "subject": subject,
                "content": content,
                **(payload_extra or {}),
            },
            next_run_at=next_run_at,
            retry_count=0,
            max_retries=max_retries,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get_email_daily_briefing_job(
        self,
        *,
        user_id: int,
        briefing_date: str,
    ) -> ScheduledJob | None:
        result = await self.session.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.job_type == "email_daily_briefing",
                ScheduledJob.user_id == user_id,
                ScheduledJob.payload["briefing_date"].as_string() == briefing_date,
            )
            .order_by(ScheduledJob.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def force_due_reminder_job(
        self,
        *,
        reminder: Reminder,
        now: datetime | None = None,
    ) -> ScheduledJob:
        # Debug helper: make the reminder's pending job runnable immediately.
        now = now or datetime.now(UTC)
        job = await self.get_pending_by_ref(
            job_type="reminder_due",
            ref_type="reminder",
            ref_id=reminder.id,
        )
        if job is None:
            return await self.create_reminder_job(reminder=reminder, now=now)
        job.next_run_at = now
        job.locked_at = None
        job.locked_by = None
        job.last_error = None
        job.updated_at = now
        await self.session.flush()
        return job

    async def get_pending_by_ref(
        self,
        *,
        job_type: str,
        ref_type: str,
        ref_id: int,
    ) -> ScheduledJob | None:
        result = await self.session.execute(
            select(ScheduledJob)
            .where(
                ScheduledJob.job_type == job_type,
                ScheduledJob.ref_type == ref_type,
                ScheduledJob.ref_id == ref_id,
                ScheduledJob.status == "pending",
            )
            .order_by(ScheduledJob.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_due_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[ScheduledJob]:
        now = now or datetime.now(UTC)
        query: Select[tuple[ScheduledJob]] = (
            select(ScheduledJob)
            .where(
                ScheduledJob.status == "pending",
                ScheduledJob.next_run_at <= now,
            )
            .order_by(ScheduledJob.next_run_at, ScheduledJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[ScheduledJob]:
        query: Select[tuple[ScheduledJob]] = (
            select(ScheduledJob).order_by(ScheduledJob.id.desc()).limit(limit)
        )
        if user_id is not None:
            query = query.where(ScheduledJob.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def mark_running(
        self,
        *,
        job: ScheduledJob,
        worker_id: str,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        job.status = "running"
        job.locked_at = now
        job.locked_by = worker_id
        job.started_at = now
        job.updated_at = now

    async def mark_succeeded(
        self,
        *,
        job: ScheduledJob,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        job.status = "succeeded"
        job.finished_at = now
        job.updated_at = now
        job.last_error = None

    async def mark_failed(
        self,
        *,
        job: ScheduledJob,
        error: str,
        now: datetime | None = None,
    ) -> None:
        now = now or datetime.now(UTC)
        job.retry_count += 1
        job.last_error = error[:2000]
        job.status = "failed" if job.retry_count >= job.max_retries else "pending"
        job.locked_at = None
        job.locked_by = None
        job.finished_at = now if job.status == "failed" else None
        if job.status == "pending" and job.job_type.startswith("email_"):
            job.next_run_at = _email_retry_at(retry_count=job.retry_count, now=now)
        job.updated_at = now

    async def cancel_pending_by_ref(
        self,
        *,
        job_type: str,
        ref_type: str,
        ref_id: int,
        now: datetime | None = None,
    ) -> int:
        # Cancel future jobs when the related reminder is completed or deleted.
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(ScheduledJob).where(
                ScheduledJob.job_type == job_type,
                ScheduledJob.ref_type == ref_type,
                ScheduledJob.ref_id == ref_id,
                ScheduledJob.status == "pending",
            )
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = "canceled"
            job.finished_at = now
            job.updated_at = now
        return len(jobs)


def _email_retry_at(*, retry_count: int, now: datetime) -> datetime:
    from datetime import timedelta

    delays = [5, 15, 30]
    index = max(0, min(retry_count - 1, len(delays) - 1))
    return now + timedelta(minutes=delays[index])
