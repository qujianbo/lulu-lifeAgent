import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ScheduledJob
from app.repositories import ReminderRepository, ScheduledJobRepository, SubscriptionRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerRunResult:
    scanned: int
    succeeded: int
    failed: int
    skipped: int


class SchedulerService:
    def __init__(self, session: AsyncSession, *, worker_id: str = "scheduler") -> None:
        self.session = session
        self.worker_id = worker_id
        self.jobs = ScheduledJobRepository(session)
        self.reminders = ReminderRepository(session)
        self.subscriptions = SubscriptionRepository(session)

    async def run_once(self, *, limit: int = 20, now: datetime | None = None) -> SchedulerRunResult:
        # Poll pending jobs and process a bounded batch per tick.
        now = now or datetime.now(UTC)
        jobs = await self.jobs.list_due_pending(now=now, limit=limit)
        succeeded = 0
        failed = 0
        skipped = 0
        for job in jobs:
            try:
                await self.jobs.mark_running(job=job, worker_id=self.worker_id, now=now)
                processed = await self._process_job(job=job, now=now)
                if processed:
                    await self.jobs.mark_succeeded(job=job, now=now)
                    succeeded += 1
                else:
                    await self.jobs.mark_succeeded(job=job, now=now)
                    skipped += 1
            except Exception as exc:  # pragma: no cover - defensive scheduler boundary
                failed += 1
                logger.exception("scheduled_job_failed", extra={"job_id": job.id})
                await self.jobs.mark_failed(job=job, error=str(exc), now=now)
        return SchedulerRunResult(
            scanned=len(jobs),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
        )

    async def _process_job(self, *, job: ScheduledJob, now: datetime) -> bool:
        if job.job_type == "reminder_due":
            return await self._process_reminder_due(job=job, now=now)
        if job.job_type == "briefing_due":
            return await self._process_briefing_due(job=job, now=now)
        logger.info("scheduled_job_skipped_unknown_type", extra={"job_id": job.id})
        return False

    async def _process_reminder_due(self, *, job: ScheduledJob, now: datetime) -> bool:
        if job.ref_id is None:
            logger.warning("reminder_job_missing_ref", extra={"job_id": job.id})
            return False

        reminder = await self.reminders.get_by_id(reminder_id=job.ref_id)
        if reminder is None or reminder.status != "active" or reminder.deleted_at is not None:
            logger.info("reminder_job_skipped_inactive", extra={"job_id": job.id})
            return False

        await self.reminders.mark_triggered(reminder_id=reminder.id, now=now)
        logger.info(
            "reminder_due_processed",
            extra={"job_id": job.id, "reminder_id": reminder.id, "user_id": reminder.user_id},
        )
        return True

    async def _process_briefing_due(self, *, job: ScheduledJob, now: datetime) -> bool:
        if job.ref_id is None:
            logger.warning("briefing_job_missing_ref", extra={"job_id": job.id})
            return False

        subscription = await self.subscriptions.get_by_id(subscription_id=job.ref_id)
        if (
            subscription is None
            or subscription.status != "active"
            or subscription.deleted_at is not None
        ):
            logger.info("briefing_job_skipped_inactive", extra={"job_id": job.id})
            return False

        next_push_at = (subscription.next_push_at or now) + timedelta(days=1)
        await self.subscriptions.mark_pushed(
            subscription_id=subscription.id,
            next_push_at=next_push_at,
            now=now,
        )
        await self.jobs.create_subscription_job(subscription=subscription, now=now)
        logger.info(
            "briefing_due_processed",
            extra={
                "job_id": job.id,
                "subscription_id": subscription.id,
                "user_id": subscription.user_id,
            },
        )
        return True
