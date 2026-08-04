import logging
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.repositories import AgentMemoryEventRepository
from app.services.agent_memory.client import Mem0MemoryClient
from app.services.agent_memory.schemas import (
    MemoryDeleteResult,
    MemoryItem,
    MemoryMessage,
    MemorySearchResult,
    MemoryWriteResult,
)

logger = logging.getLogger(__name__)


class AgentMemoryService:
    def __init__(
        self,
        settings: Settings,
        *,
        session: AsyncSession | None = None,
        client: Mem0MemoryClient | None = None,
    ) -> None:
        self.settings = settings
        self.session = session
        self.client = client or Mem0MemoryClient(settings)

    async def search(
        self,
        *,
        user_id: int,
        query: str,
        limit: int | None = None,
    ) -> MemorySearchResult:
        if not self.settings.memory_enabled:
            return MemorySearchResult(status="skipped")
        started = perf_counter()
        top_k = limit or self.settings.memory_search_top_k
        try:
            items = await self.client.search(user_id=user_id, query=query, limit=top_k)
        except Exception as exc:
            latency_ms = _latency_ms(started)
            await self._record_event(
                user_id=user_id,
                event_type="search",
                query_text=query,
                status="failed",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            logger.warning("agent_memory_search_failed", extra={"_error": str(exc)})
            return MemorySearchResult(
                status="failed",
                latency_ms=latency_ms,
                error_message=str(exc),
            )

        latency_ms = _latency_ms(started)
        await self._record_event(
            user_id=user_id,
            event_type="search",
            query_text=query,
            status="succeeded",
            metadata={"count": len(items)},
            latency_ms=latency_ms,
        )
        return MemorySearchResult(items=items, latency_ms=latency_ms)

    async def add_conversation(
        self,
        *,
        user_id: int,
        messages: list[MemoryMessage],
    ) -> MemoryWriteResult:
        if not self.settings.memory_enabled or not self.settings.memory_write_enabled:
            return MemoryWriteResult(status="skipped")
        if not messages:
            return MemoryWriteResult(status="skipped")

        started = perf_counter()
        content = "\n".join(f"{item.role}: {item.content}" for item in messages)[:2000]
        try:
            items = await self.client.add_conversation(user_id=user_id, messages=messages)
        except Exception as exc:
            latency_ms = _latency_ms(started)
            await self._record_event(
                user_id=user_id,
                event_type="add",
                content=content,
                status="failed",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            logger.warning("agent_memory_add_failed", extra={"_error": str(exc)})
            return MemoryWriteResult(
                status="failed",
                latency_ms=latency_ms,
                error_message=str(exc),
            )

        latency_ms = _latency_ms(started)
        await self._record_event(
            user_id=user_id,
            event_type="add",
            provider_memory_id=_first_memory_id(items),
            content=content,
            status="succeeded",
            metadata={"count": len(items)},
            latency_ms=latency_ms,
        )
        return MemoryWriteResult(status="succeeded", items=items, latency_ms=latency_ms)

    async def add_manual(self, *, user_id: int, content: str) -> MemoryWriteResult:
        message = MemoryMessage(role="user", content=content, occurred_at=datetime.now(UTC))
        return await self.add_conversation(user_id=user_id, messages=[message])

    async def list(self, *, user_id: int, limit: int = 20) -> MemorySearchResult:
        if not self.settings.memory_enabled:
            return MemorySearchResult(status="skipped")
        started = perf_counter()
        try:
            items = await self.client.list(user_id=user_id, limit=limit)
        except Exception as exc:
            latency_ms = _latency_ms(started)
            await self._record_event(
                user_id=user_id,
                event_type="list",
                status="failed",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return MemorySearchResult(
                status="failed",
                latency_ms=latency_ms,
                error_message=str(exc),
            )
        latency_ms = _latency_ms(started)
        await self._record_event(
            user_id=user_id,
            event_type="list",
            status="succeeded",
            metadata={"count": len(items)},
            latency_ms=latency_ms,
        )
        return MemorySearchResult(items=items, latency_ms=latency_ms)

    async def delete(
        self,
        *,
        user_id: int,
        query: str | None = None,
        memory_id: str | None = None,
    ) -> MemoryDeleteResult:
        if not self.settings.memory_enabled or not self.settings.memory_write_enabled:
            return MemoryDeleteResult(status="skipped", message="记忆功能未启用。")
        started = perf_counter()
        candidates: list[MemoryItem] = []
        target_id = memory_id
        if target_id is None and query:
            candidates = (await self.search(user_id=user_id, query=query, limit=3)).items
            if len(candidates) == 1:
                target_id = candidates[0].memory_id
            elif len(candidates) > 1:
                return MemoryDeleteResult(
                    status="needs_confirmation",
                    message="找到多条相关记忆，请确认要删除哪一条。",
                    items=candidates,
                )
        if target_id is None:
            return MemoryDeleteResult(status="not_found", message="没有找到要删除的记忆。")

        try:
            await self.client.delete(memory_id=target_id)
        except Exception as exc:
            latency_ms = _latency_ms(started)
            await self._record_event(
                user_id=user_id,
                event_type="delete",
                provider_memory_id=target_id,
                query_text=query,
                status="failed",
                error_message=str(exc),
                latency_ms=latency_ms,
            )
            return MemoryDeleteResult(
                status="failed",
                message="记忆删除失败。",
                error_message=str(exc),
                latency_ms=latency_ms,
            )

        latency_ms = _latency_ms(started)
        await self._record_event(
            user_id=user_id,
            event_type="delete",
            provider_memory_id=target_id,
            query_text=query,
            status="deleted",
            latency_ms=latency_ms,
        )
        return MemoryDeleteResult(
            status="deleted",
            message="记忆已删除。",
            items=candidates,
            latency_ms=latency_ms,
        )

    async def _record_event(
        self,
        *,
        user_id: int,
        event_type: str,
        status: str,
        provider_memory_id: str | None = None,
        query_text: str | None = None,
        content: str | None = None,
        metadata: dict | None = None,
        error_message: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        if self.session is None:
            return
        try:
            await AgentMemoryEventRepository(self.session).create(
                user_id=user_id,
                event_type=event_type,
                provider="mem0",
                provider_memory_id=provider_memory_id,
                query_text=query_text,
                content=content,
                metadata=metadata,
                status=status,
                error_message=error_message,
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("agent_memory_event_record_failed", extra={"_error": str(exc)})


def _latency_ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


def _first_memory_id(items: list[MemoryItem]) -> str | None:
    return items[0].memory_id if items else None
