import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription
from app.repositories import ScheduledJobRepository, SubscriptionRepository

DEFAULT_TIMEZONE = "Asia/Shanghai"


@dataclass(frozen=True)
class BriefingResult:
    status: str
    message: str
    subscription: Subscription | None = None
    preview_topics: list[str] | None = None


class BriefingService:
    def __init__(self, session: AsyncSession) -> None:
        self.subscriptions = SubscriptionRepository(session)
        self.jobs = ScheduledJobRepository(session)

    async def handle_from_text(
        self,
        *,
        user_id: int,
        text: str,
        memory_topics: list[str] | None = None,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> BriefingResult:
        topics = _extract_topics(text) or memory_topics or ["科技", "财经"]
        if _wants_subscription(text):
            next_push_at = _next_daily_push_at(text, timezone=timezone)
            subscription = await self.subscriptions.upsert(
                user_id=user_id,
                subscription_type="daily_briefing",
                schedule_rule=f"daily@{next_push_at.astimezone(ZoneInfo(timezone)).hour:02d}:00",
                timezone=timezone,
                preferences={"topics": topics},
                next_push_at=next_push_at,
            )
            await self.jobs.create_subscription_job(subscription=subscription)
            return BriefingResult(
                status="subscribed",
                message="资讯订阅已保存。",
                subscription=subscription,
                preview_topics=topics,
            )
        return BriefingResult(
            status="preview",
            message="当前先返回资讯偏好预览，外部资讯抓取后续接入。",
            preview_topics=topics,
        )

    async def list_active(self, *, user_id: int, limit: int = 20) -> list[Subscription]:
        return await self.subscriptions.list_active(user_id=user_id, limit=limit)


def _wants_subscription(text: str) -> bool:
    return any(keyword in text for keyword in ("每天", "每日", "订阅", "推送", "早报", "简报"))


def _extract_topics(text: str) -> list[str]:
    topics = ["AI", "科技", "财经", "商业", "体育", "娱乐", "国际", "国内", "健康", "天气"]
    return [topic for topic in topics if topic.lower() in text.lower()]


def _next_daily_push_at(text: str, *, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    hour = _extract_hour(text) or 8
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.astimezone(UTC)


def _extract_hour(text: str) -> int | None:
    match = re.search(r"([01]?\d|2[0-3])\s*[点:：时]", text)
    if not match:
        return None
    hour = int(match.group(1))
    if any(keyword in text for keyword in ("下午", "晚上")) and hour < 12:
        hour += 12
    return hour
