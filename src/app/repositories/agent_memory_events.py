from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMemoryEvent


class AgentMemoryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        event_type: str,
        provider: str = "mem0",
        provider_memory_id: str | None = None,
        query_text: str | None = None,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str,
        error_message: str | None = None,
        latency_ms: int | None = None,
        now: datetime | None = None,
    ) -> AgentMemoryEvent:
        # Record memory operations for debugging and audit without storing vectors.
        item = AgentMemoryEvent(
            user_id=user_id,
            event_type=event_type,
            provider=provider,
            provider_memory_id=provider_memory_id,
            query_text=query_text,
            content=content,
            extra_metadata=metadata,
            status=status,
            error_message=error_message,
            latency_ms=latency_ms,
            created_at=now or datetime.now(UTC),
        )
        self.session.add(item)
        await self.session.flush()
        return item

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[AgentMemoryEvent]:
        query: Select[tuple[AgentMemoryEvent]] = (
            select(AgentMemoryEvent).order_by(AgentMemoryEvent.id.desc()).limit(limit)
        )
        if user_id is not None:
            query = query.where(AgentMemoryEvent.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())
