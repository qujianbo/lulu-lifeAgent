from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdSequence, User
from app.services.user_ids import (
    DEFAULT_PRODUCT_CODE,
    DEFAULT_WEB_BETA_CHANNEL_CODE,
    DEFAULT_WECHAT_CHANNEL_CODE,
    build_public_user_id,
    sequence_key,
    year_code_from_datetime,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_openid(self, wechat_openid: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.wechat_openid == wechat_openid)
        )
        return result.scalar_one_or_none()

    async def create_wechat_user(
        self,
        *,
        wechat_openid: str,
        now: datetime | None = None,
        product_code: str = DEFAULT_PRODUCT_CODE,
        channel_code: str = DEFAULT_WECHAT_CHANNEL_CODE,
    ) -> User:
        now = now or datetime.now(UTC)
        public_user_id = await self._next_public_user_id(
            now=now,
            product_code=product_code,
            channel_code=channel_code,
        )
        user = User(
            public_user_id=public_user_id,
            wechat_openid=wechat_openid,
            status="active",
            subscribed_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_web_beta_user(
        self,
        *,
        beta_username: str,
        now: datetime | None = None,
        product_code: str = DEFAULT_PRODUCT_CODE,
        channel_code: str = DEFAULT_WEB_BETA_CHANNEL_CODE,
    ) -> User:
        now = now or datetime.now(UTC)
        public_user_id = await self._next_public_user_id(
            now=now,
            product_code=product_code,
            channel_code=channel_code,
        )
        user = User(
            public_user_id=public_user_id,
            wechat_openid=f"web_beta:{beta_username}",
            status="active",
            subscribed_at=now,
            last_active_at=now,
            created_at=now,
            updated_at=now,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def get_or_create_wechat_user(self, wechat_openid: str) -> User:
        user = await self.get_by_openid(wechat_openid)
        if user is not None:
            user.last_active_at = datetime.now(UTC)
            return user
        return await self.create_wechat_user(wechat_openid=wechat_openid)

    async def _next_public_user_id(
        self,
        *,
        now: datetime,
        product_code: str,
        channel_code: str,
    ) -> int:
        year_code = year_code_from_datetime(now)
        key = sequence_key(product_code, channel_code, year_code)

        # Lock one sequence row per product/channel/year so concurrent user creation
        # cannot allocate the same public_user_id. The unique index on users remains
        # a final database-level guard.
        result = await self.session.execute(
            select(IdSequence).where(IdSequence.sequence_key == key).with_for_update()
        )
        sequence = result.scalar_one_or_none()
        if sequence is None:
            sequence = IdSequence(
                sequence_key=key,
                current_value=0,
                created_at=now,
                updated_at=now,
            )
            self.session.add(sequence)
            await self.session.flush()

        sequence.current_value += 1
        sequence.updated_at = now
        await self.session.flush()

        return build_public_user_id(
            sequence.current_value,
            product_code=product_code,
            channel_code=channel_code,
            year_code=year_code,
        )
