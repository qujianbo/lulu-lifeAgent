from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserContact


class UserContactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_email(
        self,
        *,
        user_id: int,
        email: str,
        status: str = "active",
        now: datetime | None = None,
    ) -> UserContact:
        # Keep one active email contact per user for the MVP.
        now = now or datetime.now(UTC)
        contact = await self.get_email(user_id=user_id)
        if contact is None:
            contact = UserContact(
                user_id=user_id,
                contact_type="email",
                contact_value=email.strip(),
                is_verified=False,
                status=status,
                created_at=now,
                updated_at=now,
            )
            self.session.add(contact)
        else:
            contact.contact_value = email.strip()
            contact.status = status
            contact.updated_at = now
        await self.session.flush()
        return contact

    async def get_email(self, *, user_id: int) -> UserContact | None:
        result = await self.session.execute(
            select(UserContact)
            .where(
                UserContact.user_id == user_id,
                UserContact.contact_type == "email",
                UserContact.deleted_at.is_(None),
            )
            .order_by(UserContact.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_active_email_contacts(self, *, limit: int = 500) -> list[UserContact]:
        query: Select[tuple[UserContact]] = (
            select(UserContact)
            .where(
                UserContact.contact_type == "email",
                UserContact.status == "active",
                UserContact.deleted_at.is_(None),
            )
            .order_by(UserContact.id)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
