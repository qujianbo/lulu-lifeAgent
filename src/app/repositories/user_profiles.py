from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserProfile


class UserProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        user_id: int,
        profile_key: str,
        profile_value: str,
        value_type: str = "string",
        source: str = "user_explicit",
        extra_metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> UserProfile:
        # Keep one active profile row per user and profile_key.
        now = now or datetime.now(UTC)
        profile = await self.get_active_by_key(user_id=user_id, profile_key=profile_key)
        if profile is None:
            profile = UserProfile(
                user_id=user_id,
                profile_key=profile_key,
                profile_value=profile_value,
                value_type=value_type,
                source=source,
                confidence=Decimal("1.000"),
                extra_metadata=extra_metadata,
                status="active",
                created_at=now,
                updated_at=now,
            )
            self.session.add(profile)
        else:
            profile.profile_value = profile_value
            profile.value_type = value_type
            profile.source = source
            profile.extra_metadata = extra_metadata
            profile.status = "active"
            profile.updated_at = now
        await self.session.flush()
        return profile

    async def list_active(self, *, user_id: int, limit: int = 30) -> list[UserProfile]:
        query: Select[tuple[UserProfile]] = (
            select(UserProfile)
            .where(
                UserProfile.user_id == user_id,
                UserProfile.status == "active",
                UserProfile.deleted_at.is_(None),
            )
            .order_by(UserProfile.updated_at.desc(), UserProfile.id.desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_active_by_key(self, *, user_id: int, profile_key: str) -> UserProfile | None:
        result = await self.session.execute(
            select(UserProfile).where(
                UserProfile.user_id == user_id,
                UserProfile.profile_key == profile_key,
                UserProfile.status == "active",
                UserProfile.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def soft_delete(
        self,
        *,
        profile_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> UserProfile | None:
        now = now or datetime.now(UTC)
        result = await self.session.execute(
            select(UserProfile).where(
                UserProfile.id == profile_id,
                UserProfile.user_id == user_id,
                UserProfile.status == "active",
                UserProfile.deleted_at.is_(None),
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            return None
        profile.status = "deleted"
        profile.deleted_at = now
        profile.updated_at = now
        return profile
