from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        user_id: int,
        subscription_type: str,
        schedule_rule: str,
        timezone: str,
        preferences: dict[str, Any] | None,
        next_push_at: datetime | None,
        now: datetime | None = None,
    ) -> Subscription:
        # Keep one active subscription per user and subscription_type in MVP.
        now = now or datetime.now(UTC)
        subscription = await self.get_active_by_type(
            user_id=user_id,
            subscription_type=subscription_type,
        )
        if subscription is None:
            subscription = Subscription(
                subscription_uuid=uuid4(),
                user_id=user_id,
                subscription_type=subscription_type,
                schedule_rule=schedule_rule,
                timezone=timezone,
                preferences=preferences,
                next_push_at=next_push_at,
                status="active",
                created_at=now,
                updated_at=now,
            )
            self.session.add(subscription)
        else:
            subscription.schedule_rule = schedule_rule
            subscription.timezone = timezone
            subscription.preferences = preferences
            subscription.next_push_at = next_push_at
            subscription.status = "active"
            subscription.updated_at = now
        await self.session.flush()
        return subscription

    async def get_active_by_type(
        self,
        *,
        user_id: int,
        subscription_type: str,
    ) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(
                Subscription.user_id == user_id,
                Subscription.subscription_type == subscription_type,
                Subscription.status == "active",
                Subscription.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, *, subscription_id: int) -> Subscription | None:
        result = await self.session.execute(
            select(Subscription).where(Subscription.id == subscription_id)
        )
        return result.scalar_one_or_none()

    async def list_active(self, *, user_id: int, limit: int = 20) -> list[Subscription]:
        query: Select[tuple[Subscription]] = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == "active",
                Subscription.deleted_at.is_(None),
            )
            .order_by(Subscription.updated_at.desc(), Subscription.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def mark_pushed(
        self,
        *,
        subscription_id: int,
        next_push_at: datetime,
        now: datetime | None = None,
    ) -> Subscription | None:
        now = now or datetime.now(UTC)
        subscription = await self.get_by_id(subscription_id=subscription_id)
        if subscription is None:
            return None
        subscription.last_pushed_at = now
        subscription.next_push_at = next_push_at
        subscription.updated_at = now
        return subscription
