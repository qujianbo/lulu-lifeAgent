from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageLog


class MessageLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        direction: str,
        message_type: str,
        user_id: int | None = None,
        content: str | None = None,
        content_summary: str | None = None,
        agent_intent: str | None = None,
        tool_name: str | None = None,
        tool_status: str | None = None,
        llm_provider: str | None = None,
        llm_latency_ms: int | None = None,
        raw_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        status: str = "success",
        now: datetime | None = None,
    ) -> MessageLog:
        # Store one message event for audit, debugging and storage analysis.
        now = now or datetime.now(UTC)
        log = MessageLog(
            message_uuid=uuid4(),
            user_id=user_id,
            direction=direction,
            message_type=message_type,
            content=content,
            content_summary=content_summary or _summarize(content),
            agent_intent=agent_intent,
            tool_name=tool_name,
            tool_status=tool_status,
            llm_provider=llm_provider,
            llm_latency_ms=llm_latency_ms,
            raw_payload=raw_payload,
            error_code=error_code,
            status=status,
            created_at=now,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def list_recent(
        self,
        *,
        user_id: int | None = None,
        limit: int = 20,
    ) -> list[MessageLog]:
        query: Select[tuple[MessageLog]] = (
            select(MessageLog).order_by(MessageLog.id.desc()).limit(limit)
        )
        if user_id is not None:
            query = query.where(MessageLog.user_id == user_id)
        result = await self.session.execute(query)
        return list(result.scalars().all())


def _summarize(content: str | None) -> str | None:
    if content is None:
        return None
    return content.strip()[:200]
