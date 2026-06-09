from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LifeRecord


class LifeRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        record_type: str,
        content: str,
        amount: Decimal | None = None,
        currency: str | None = "CNY",
        tags: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
        recorded_at: datetime | None = None,
        now: datetime | None = None,
    ) -> LifeRecord:
        # Store one normalized life event for later query and summarization.
        now = now or datetime.now(UTC)
        record = LifeRecord(
            record_uuid=uuid4(),
            user_id=user_id,
            record_type=record_type,
            content=content[:2000],
            amount=amount,
            currency=currency,
            tags=tags,
            recorded_at=recorded_at or now,
            extra_metadata=extra_metadata,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_active(
        self,
        *,
        user_id: int,
        record_type: str | None = None,
        limit: int = 20,
    ) -> list[LifeRecord]:
        query: Select[tuple[LifeRecord]] = (
            select(LifeRecord)
            .where(
                LifeRecord.user_id == user_id,
                LifeRecord.status == "active",
                LifeRecord.deleted_at.is_(None),
            )
            .order_by(LifeRecord.recorded_at.desc(), LifeRecord.id.desc())
            .limit(limit)
        )
        if record_type is not None:
            query = query.where(LifeRecord.record_type == record_type)
        result = await self.session.execute(query)
        return list(result.scalars().all())
