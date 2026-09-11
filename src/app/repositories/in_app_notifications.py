from datetime import UTC, datetime

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InAppNotification


class InAppNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        notification_type: str,
        title: str,
        content: str | None = None,
        related_entity_type: str | None = None,
        related_entity_id: int | None = None,
    ) -> InAppNotification:
        now = datetime.now(UTC)
        item = InAppNotification(
            user_id=user_id,
            notification_type=notification_type,
            title=title[:200],
            content=content,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_for_user(self, *, user_id: int, limit: int = 20) -> list[InAppNotification]:
        query: Select[tuple[InAppNotification]] = (
            select(InAppNotification)
            .where(InAppNotification.user_id == user_id)
            .order_by(InAppNotification.created_at.desc(), InAppNotification.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def unread_count(self, *, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count(InAppNotification.id)).where(
                InAppNotification.user_id == user_id,
                InAppNotification.read_at.is_(None),
            )
        )
        return int(result.scalar_one())

    async def mark_read(self, *, notification_id: int, user_id: int) -> InAppNotification | None:
        result = await self.session.execute(
            select(InAppNotification).where(
                InAppNotification.id == notification_id,
                InAppNotification.user_id == user_id,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            return None
        item.read_at = datetime.now(UTC)
        item.updated_at = item.read_at
        return item

