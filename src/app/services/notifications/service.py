from dataclasses import dataclass
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Reminder, ScheduledJob
from app.repositories import ScheduledJobRepository, UserContactRepository, UserProfileRepository

EMAIL_DEFAULT_TIMEZONE = "Asia/Shanghai"
EMAIL_JOB_TYPES = {"email_daily_briefing", "email_reminder_due", "email_test"}


@dataclass(frozen=True)
class EmailPreferences:
    enabled: bool
    daily_briefing_enabled: bool
    daily_briefing_time: str
    reminder_enabled: bool
    timezone: str


class EmailNotificationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.contacts = UserContactRepository(session)
        self.profiles = UserProfileRepository(session)
        self.jobs = ScheduledJobRepository(session)

    async def set_user_email(
        self,
        *,
        user_id: int,
        email: str,
        enabled: bool,
        daily_briefing_time: str = "09:00",
        reminder_enabled: bool = True,
        now: datetime | None = None,
    ) -> None:
        # Store contact separately, while lightweight preferences stay in user_profiles.
        now = now or datetime.now(UTC)
        await self.contacts.upsert_email(
            user_id=user_id,
            email=email,
            status="active" if enabled else "disabled",
            now=now,
        )
        await self.profiles.upsert(
            user_id=user_id,
            profile_key="email_enabled",
            profile_value=str(enabled).lower(),
            value_type="boolean",
            source="admin",
            now=now,
        )
        await self.profiles.upsert(
            user_id=user_id,
            profile_key="email_daily_briefing_enabled",
            profile_value=str(enabled).lower(),
            value_type="boolean",
            source="admin",
            now=now,
        )
        await self.profiles.upsert(
            user_id=user_id,
            profile_key="email_daily_briefing_time",
            profile_value=daily_briefing_time or self.settings.email_default_daily_briefing_time,
            source="admin",
            now=now,
        )
        await self.profiles.upsert(
            user_id=user_id,
            profile_key="email_reminder_enabled",
            profile_value=str(reminder_enabled).lower(),
            value_type="boolean",
            source="admin",
            now=now,
        )
        await self.profiles.upsert(
            user_id=user_id,
            profile_key="email_timezone",
            profile_value=EMAIL_DEFAULT_TIMEZONE,
            source="admin",
            now=now,
        )

    async def get_user_email_settings(self, *, user_id: int) -> dict[str, object]:
        contact = await self.contacts.get_email(user_id=user_id)
        prefs = await self.get_preferences(user_id=user_id)
        has_active_email = contact is not None and contact.status == "active"
        return {
            "email": contact.contact_value if contact else None,
            "email_status": contact.status if contact else "missing",
            "email_enabled": prefs.enabled and has_active_email,
            "email_daily_briefing_enabled": prefs.daily_briefing_enabled and has_active_email,
            "email_daily_briefing_time": prefs.daily_briefing_time,
            "email_reminder_enabled": prefs.reminder_enabled and has_active_email,
            "email_timezone": prefs.timezone,
        }

    async def get_preferences(self, *, user_id: int) -> EmailPreferences:
        values: dict[str, str] = {}
        for key in [
            "email_enabled",
            "email_daily_briefing_enabled",
            "email_daily_briefing_time",
            "email_reminder_enabled",
            "email_timezone",
        ]:
            profile = await self.profiles.get_active_by_key(user_id=user_id, profile_key=key)
            if profile is not None:
                values[key] = profile.profile_value
        enabled = _as_bool(values.get("email_enabled"), default=True)
        return EmailPreferences(
            enabled=enabled,
            daily_briefing_enabled=_as_bool(
                values.get("email_daily_briefing_enabled"),
                default=enabled,
            ),
            daily_briefing_time=values.get(
                "email_daily_briefing_time",
                self.settings.email_default_daily_briefing_time,
            ),
            reminder_enabled=_as_bool(values.get("email_reminder_enabled"), default=True),
            timezone=values.get("email_timezone", EMAIL_DEFAULT_TIMEZONE),
        )

    async def create_test_email_job(
        self,
        *,
        user_id: int,
        now: datetime | None = None,
    ) -> ScheduledJob:
        now = now or datetime.now(UTC)
        contact = await self._active_email_contact(user_id=user_id)
        return await self.jobs.create_email_job(
            user_id=user_id,
            email_type="test",
            email=contact.contact_value,
            subject="生活管家测试邮件",
            content="这是一封生活管家 Agent 测试邮件。如果你收到它，说明邮件触达已配置成功。",
            next_run_at=now,
            max_retries=self.settings.email_max_retries,
            now=now,
        )

    async def create_reminder_email_job(
        self,
        *,
        reminder: Reminder,
        now: datetime | None = None,
    ) -> ScheduledJob | None:
        now = now or datetime.now(UTC)
        prefs = await self.get_preferences(user_id=reminder.user_id)
        contact = await self.contacts.get_email(user_id=reminder.user_id)
        if (
            not prefs.enabled
            or not prefs.reminder_enabled
            or contact is None
            or contact.status != "active"
        ):
            return None
        subject = f"生活管家提醒：{reminder.title}"
        content = _reminder_email_content(reminder)
        return await self.jobs.create_email_job(
            user_id=reminder.user_id,
            email_type="reminder_due",
            email=contact.contact_value,
            subject=subject,
            content=content,
            next_run_at=now,
            ref_type="reminder",
            ref_id=reminder.id,
            max_retries=self.settings.email_max_retries,
            now=now,
        )

    async def create_due_daily_briefing_jobs(
        self,
        *,
        now: datetime | None = None,
        limit: int = 500,
    ) -> int:
        now = now or datetime.now(UTC)
        created = 0
        for contact in await self.contacts.list_active_email_contacts(limit=limit):
            prefs = await self.get_preferences(user_id=contact.user_id)
            if not prefs.enabled or not prefs.daily_briefing_enabled:
                continue
            local_now = now.astimezone(ZoneInfo(prefs.timezone))
            send_time = _parse_time(prefs.daily_briefing_time)
            if (
                local_now.time().hour != send_time.hour
                or local_now.time().minute != send_time.minute
            ):
                continue
            briefing_date = local_now.date().isoformat()
            existing = await self.jobs.get_email_daily_briefing_job(
                user_id=contact.user_id,
                briefing_date=briefing_date,
            )
            if existing is not None:
                continue
            subject = f"生活管家今日简报 - {briefing_date}"
            content = await self.build_daily_briefing_content(
                user_id=contact.user_id,
                local_date=briefing_date,
            )
            await self.jobs.create_email_job(
                user_id=contact.user_id,
                email_type="daily_briefing",
                email=contact.contact_value,
                subject=subject,
                content=content,
                next_run_at=now,
                max_retries=self.settings.email_max_retries,
                payload_extra={"briefing_date": briefing_date},
                now=now,
            )
            created += 1
        return created

    async def build_daily_briefing_content(self, *, user_id: int, local_date: str) -> str:
        # Keep the MVP text-only briefing compact and reliable.
        from app.repositories import ReminderRepository, SubscriptionRepository

        reminders = await ReminderRepository(self.session).list_active(user_id=user_id, limit=10)
        subscriptions = await SubscriptionRepository(self.session).list_active(
            user_id=user_id,
            limit=10,
        )
        lines = [f"生活管家今日简报 - {local_date}", ""]
        lines.append("今日待办：")
        if reminders:
            lines.extend([f"- {item.title}" for item in reminders])
        else:
            lines.append("- 暂无待办")
        lines.append("")
        lines.append("订阅资讯：")
        if subscriptions:
            for item in subscriptions:
                topics = ", ".join((item.preferences or {}).get("topics", []))
                lines.append(f"- {item.subscription_type}: {topics or '默认主题'}")
        else:
            lines.append("- 暂无订阅")
        lines.append("")
        lines.append("祝你今天顺利。")
        return "\n".join(lines)

    async def _active_email_contact(self, *, user_id: int):
        contact = await self.contacts.get_email(user_id=user_id)
        if contact is None or contact.status != "active":
            raise RuntimeError("user email is not configured")
        return contact


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _parse_time(value: str) -> time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return time(hour=int(hour_text), minute=int(minute_text))
    except Exception:
        return time(hour=9, minute=0)


def _reminder_email_content(reminder: Reminder) -> str:
    lines = [
        f"你有一个提醒事项到时间了：{reminder.title}",
        "",
        reminder.content or "",
    ]
    if reminder.scheduled_at:
        lines.extend(["", f"提醒时间：{reminder.scheduled_at.isoformat()}"])
    return "\n".join(lines).strip()
