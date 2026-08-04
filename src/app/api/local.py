import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.local_agent import LocalAgentService
from app.agent.planner import PlannerError
from app.config import Settings, get_settings
from app.dependencies import get_database_session
from app.models import (
    AgentMemoryEvent,
    LifeRecord,
    MessageLog,
    Reminder,
    ScheduledJob,
    Subscription,
    User,
    UserProfile,
)
from app.repositories import MessageLogRepository, ScheduledJobRepository, UserRepository
from app.services.agent_memory import AgentMemoryService
from app.services.briefing import BriefingService
from app.services.briefing.rss import fetch_rss_articles, split_rss_urls
from app.services.commodities import CommodityService
from app.services.life_records import LifeRecordService
from app.services.llm.deepseek import DeepSeekProvider, DeepSeekProviderError
from app.services.llm.types import LLMMessage
from app.services.markets import MarketService
from app.services.memory import MemoryService
from app.services.reminders.service import ReminderService
from app.services.scheduler import SchedulerService
from app.services.web_search import WebSearchService

router = APIRouter(prefix="/api/local", tags=["local"])
logger = logging.getLogger(__name__)
SETTINGS_DEPENDENCY = Depends(get_settings)
DATABASE_SESSION_DEPENDENCY = Depends(get_database_session)
DEBUG_LIST_LIMIT = 3


class DeepSeekPingResponse(BaseModel):
    ok: bool
    model: str
    content: str
    latency_ms: int


class LocalChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    user_id: int | None = Field(default=None, gt=0)


class LocalChatResponse(BaseModel):
    content: str
    intent: str
    model: str
    provider: str
    latency_ms: int
    user_id: int | None = None
    tool_result: dict[str, Any] | None = None
    planner: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] | None = None
    memory_trace: dict[str, Any] | None = None


class LocalReminderItem(BaseModel):
    id: int
    title: str
    scheduled_at: str | None
    status: str


class LocalMemoryItem(BaseModel):
    id: int
    profile_key: str
    profile_value: str
    status: str
    updated_at: str | None


class LocalLifeRecordItem(BaseModel):
    id: int
    record_type: str
    content: str
    amount: str | None
    currency: str | None
    recorded_at: str
    status: str


class LocalSubscriptionItem(BaseModel):
    id: int
    subscription_type: str
    schedule_rule: str
    preferences: dict[str, Any] | None
    next_push_at: str | None
    status: str


class LocalMessageLogItem(BaseModel):
    id: int
    direction: str
    message_type: str
    content_summary: str | None
    agent_intent: str | None
    tool_name: str | None
    tool_status: str | None
    llm_provider: str | None
    llm_latency_ms: int | None
    status: str
    created_at: str


class LocalMemoryEventItem(BaseModel):
    id: int
    event_type: str
    provider_memory_id: str | None
    query_text: str | None
    content: str | None
    status: str
    error_message: str | None
    latency_ms: int | None
    created_at: str


class LocalBriefingArticleItem(BaseModel):
    title: str
    link: str | None
    source: str


class LocalMemoriesResponse(BaseModel):
    user_id: int | None
    items: list[LocalMemoryItem]


class LocalLifeRecordsResponse(BaseModel):
    user_id: int | None
    items: list[LocalLifeRecordItem]


class LocalSubscriptionsResponse(BaseModel):
    user_id: int | None
    items: list[LocalSubscriptionItem]


class LocalMessageLogsResponse(BaseModel):
    user_id: int | None
    items: list[LocalMessageLogItem]


class LocalMemoryEventsResponse(BaseModel):
    user_id: int | None
    items: list[LocalMemoryEventItem]


class LocalBriefingPreviewResponse(BaseModel):
    status: str
    source_count: int
    items: list[LocalBriefingArticleItem]


class LocalRemindersResponse(BaseModel):
    user_id: int | None
    items: list[LocalReminderItem]


class LocalReminderMutationResponse(BaseModel):
    status: str
    message: str
    user_id: int | None
    reminder_id: int | None = None


class LocalScheduledJobItem(BaseModel):
    id: int
    job_type: str
    ref_type: str | None
    ref_id: int | None
    next_run_at: str
    status: str
    retry_count: int


class LocalScheduledJobsResponse(BaseModel):
    user_id: int | None
    items: list[LocalScheduledJobItem]


class LocalSchedulerRunResponse(BaseModel):
    status: str
    scanned: int
    succeeded: int
    failed: int
    skipped: int


class LocalStatsResponse(BaseModel):
    users: int
    reminders_active: int
    memories_active: int
    life_records_active: int
    subscriptions_active: int
    scheduled_jobs_pending: int
    message_logs: int


async def require_admin_token(
    settings: Settings = SETTINGS_DEPENDENCY,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    # Local debug APIs are open only when ADMIN_TOKEN is intentionally left empty.
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="invalid admin token")


ADMIN_DEPENDENCY = Depends(require_admin_token)


@router.get("/deepseek/ping", response_model=DeepSeekPingResponse)
async def deepseek_ping(
    _: None = ADMIN_DEPENDENCY,
    settings: Settings = SETTINGS_DEPENDENCY,
) -> DeepSeekPingResponse:
    provider = DeepSeekProvider(settings)
    try:
        response = await provider.chat(
            [
                LLMMessage(
                    role="user",
                    content="这是后端健康检查。请只输出这四个中文字符：后端正常",
                )
            ],
            temperature=0,
            max_tokens=64,
        )
    except DeepSeekProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not response.content.strip():
        raise HTTPException(status_code=502, detail="DeepSeek returned empty content")
    return DeepSeekPingResponse(
        ok=True,
        model=response.model,
        content=response.content,
        latency_ms=response.latency_ms,
    )


@router.post("/chat", response_model=LocalChatResponse)
async def local_chat(
    payload: LocalChatRequest,
    _: None = ADMIN_DEPENDENCY,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalChatResponse:
    service = build_local_agent_service(settings=settings, session=session)
    try:
        user_id, result = await _chat_with_optional_database(
            service=service,
            session=session,
            payload=payload,
        )
    except (DeepSeekProviderError, PlannerError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LocalChatResponse(
        content=result.content,
        intent=result.intent,
        model=result.model,
        provider=result.provider,
        latency_ms=result.latency_ms,
        user_id=user_id,
        tool_result=result.tool_result,
        planner=result.planner,
        tool_trace=result.tool_trace,
        memory_trace=result.memory_trace,
    )


async def _chat_with_optional_database(
    *,
    service: LocalAgentService,
    session: AsyncSession | None,
    payload: LocalChatRequest,
):
    try:
        async with _session_transaction(session):
            user_id = await _resolve_debug_user_id(session=session, user_id=payload.user_id)
            effective_message = payload.message
            if session is not None and _is_confirmation_message(payload.message):
                effective_message = await _resolve_confirmation_message(
                    session=session,
                    user_id=user_id,
                )
            if session is not None:
                await MessageLogRepository(session).create(
                    direction="in",
                    message_type="text",
                    user_id=user_id,
                    content=payload.message,
                    raw_payload={
                        "source": "local_debug",
                        "effective_message": effective_message,
                    },
                )
            result = await service.chat(effective_message, user_id=user_id)
            if session is not None:
                tool_name, tool_status = _tool_log_fields(result.tool_result)
                await MessageLogRepository(session).create(
                    direction="out",
                    message_type="text",
                    user_id=user_id,
                    content=result.content,
                    agent_intent=result.intent,
                    tool_name=tool_name,
                    tool_status=tool_status,
                    llm_provider=result.provider,
                    llm_latency_ms=result.latency_ms,
                    raw_payload={
                        "model": result.model,
                        "planner": result.planner,
                        "tool_result": result.tool_result,
                        "tool_trace": result.tool_trace,
                        "memory_trace": result.memory_trace,
                        "source": "local_debug",
                    },
                )
            return user_id, result
    except (DeepSeekProviderError, PlannerError):
        raise
    except Exception as exc:
        if session is None:
            raise
        # Let local Docker-free environments keep validating Agent behavior without DB.
        logger.warning("local_chat_database_fallback", extra={"_error": str(exc)})
        fallback_service = LocalAgentService(service.graph.llm)
        result = await fallback_service.chat(payload.message, user_id=payload.user_id)
        return payload.user_id, result


@router.get("/reminders", response_model=LocalRemindersResponse)
async def local_reminders(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalRemindersResponse:
    if session is None:
        return LocalRemindersResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            reminders = await ReminderService(session).list_active(
                user_id=resolved_user_id or 0,
                limit=DEBUG_LIST_LIMIT,
            )
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_reminders_database_fallback", extra={"_error": str(exc)})
        return LocalRemindersResponse(user_id=user_id, items=[])
    return LocalRemindersResponse(
        user_id=resolved_user_id,
        items=[
            LocalReminderItem(
                id=item.id,
                title=item.title,
                scheduled_at=item.scheduled_at.isoformat() if item.scheduled_at else None,
                status=item.status,
            )
            for item in reminders
        ],
    )


@router.get("/memories", response_model=LocalMemoriesResponse)
async def local_memories(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalMemoriesResponse:
    if session is None:
        return LocalMemoriesResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            memories = await MemoryService(session).list_active(
                user_id=resolved_user_id or 0,
                limit=DEBUG_LIST_LIMIT,
            )
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_memories_database_fallback", extra={"_error": str(exc)})
        return LocalMemoriesResponse(user_id=user_id, items=[])
    return LocalMemoriesResponse(
        user_id=resolved_user_id,
        items=[
            LocalMemoryItem(
                id=item.id,
                profile_key=item.profile_key,
                profile_value=item.profile_value,
                status=item.status,
                updated_at=item.updated_at.isoformat() if item.updated_at else None,
            )
            for item in memories
        ],
    )


@router.get("/life-records", response_model=LocalLifeRecordsResponse)
async def local_life_records(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalLifeRecordsResponse:
    if session is None:
        return LocalLifeRecordsResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            records = await LifeRecordService(session).list_active(
                user_id=resolved_user_id or 0,
                limit=DEBUG_LIST_LIMIT,
            )
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_life_records_database_fallback", extra={"_error": str(exc)})
        return LocalLifeRecordsResponse(user_id=user_id, items=[])
    return LocalLifeRecordsResponse(
        user_id=resolved_user_id,
        items=[
            LocalLifeRecordItem(
                id=item.id,
                record_type=item.record_type,
                content=item.content,
                amount=str(item.amount) if item.amount is not None else None,
                currency=item.currency,
                recorded_at=item.recorded_at.isoformat(),
                status=item.status,
            )
            for item in records
        ],
    )


@router.get("/subscriptions", response_model=LocalSubscriptionsResponse)
async def local_subscriptions(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalSubscriptionsResponse:
    if session is None:
        return LocalSubscriptionsResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            subscriptions = await BriefingService(session).list_active(
                user_id=resolved_user_id or 0,
                limit=DEBUG_LIST_LIMIT,
            )
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_subscriptions_database_fallback", extra={"_error": str(exc)})
        return LocalSubscriptionsResponse(user_id=user_id, items=[])
    return LocalSubscriptionsResponse(
        user_id=resolved_user_id,
        items=[
            LocalSubscriptionItem(
                id=item.id,
                subscription_type=item.subscription_type,
                schedule_rule=item.schedule_rule,
                preferences=item.preferences,
                next_push_at=item.next_push_at.isoformat() if item.next_push_at else None,
                status=item.status,
            )
            for item in subscriptions
        ],
    )


@router.get("/message-logs", response_model=LocalMessageLogsResponse)
async def local_message_logs(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalMessageLogsResponse:
    if session is None:
        return LocalMessageLogsResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            logs = await MessageLogRepository(session).list_recent(
                user_id=resolved_user_id,
                limit=DEBUG_LIST_LIMIT,
            )
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_message_logs_database_fallback", extra={"_error": str(exc)})
        return LocalMessageLogsResponse(user_id=user_id, items=[])
    return LocalMessageLogsResponse(
        user_id=resolved_user_id,
        items=[
            LocalMessageLogItem(
                id=item.id,
                direction=item.direction,
                message_type=item.message_type,
                content_summary=item.content_summary,
                agent_intent=item.agent_intent,
                tool_name=item.tool_name,
                tool_status=item.tool_status,
                llm_provider=item.llm_provider,
                llm_latency_ms=item.llm_latency_ms,
                status=item.status,
                created_at=item.created_at.isoformat(),
            )
            for item in logs
        ],
    )


@router.get("/memory-events", response_model=LocalMemoryEventsResponse)
async def local_memory_events(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalMemoryEventsResponse:
    if session is None:
        return LocalMemoryEventsResponse(user_id=None, items=[])
    try:
        async with session.begin():
            resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
            query = (
                select(AgentMemoryEvent)
                .order_by(AgentMemoryEvent.id.desc())
                .limit(DEBUG_LIST_LIMIT)
            )
            if resolved_user_id is not None:
                query = query.where(AgentMemoryEvent.user_id == resolved_user_id)
            result = await session.execute(query)
            events = list(result.scalars().all())
    except Exception as exc:
        # Keep the debug page usable even when local DB is not running.
        logger.warning("local_memory_events_database_fallback", extra={"_error": str(exc)})
        return LocalMemoryEventsResponse(user_id=user_id, items=[])
    return LocalMemoryEventsResponse(
        user_id=resolved_user_id,
        items=[
            LocalMemoryEventItem(
                id=item.id,
                event_type=item.event_type,
                provider_memory_id=item.provider_memory_id,
                query_text=item.query_text,
                content=item.content,
                status=item.status,
                error_message=item.error_message,
                latency_ms=item.latency_ms,
                created_at=item.created_at.isoformat(),
            )
            for item in events
        ],
    )


@router.get("/briefing/preview", response_model=LocalBriefingPreviewResponse)
async def local_briefing_preview(
    _: None = ADMIN_DEPENDENCY,
    settings: Settings = SETTINGS_DEPENDENCY,
) -> LocalBriefingPreviewResponse:
    rss_urls = split_rss_urls(settings.briefing_rss_urls)
    if not rss_urls:
        return LocalBriefingPreviewResponse(status="no_sources", source_count=0, items=[])
    articles = await fetch_rss_articles(
        rss_urls=rss_urls,
        limit=DEBUG_LIST_LIMIT,
        timeout_seconds=settings.briefing_rss_timeout_seconds,
    )
    return LocalBriefingPreviewResponse(
        status="success",
        source_count=len(rss_urls),
        items=[
            LocalBriefingArticleItem(title=item.title, link=item.link, source=item.source)
            for item in articles
        ],
    )


@router.delete("/memories/{memory_id}", response_model=LocalReminderMutationResponse)
async def local_delete_memory(
    memory_id: int,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalReminderMutationResponse:
    if session is None:
        return LocalReminderMutationResponse(
            status="database_unavailable",
            message="数据库不可用。",
            user_id=None,
        )
    async with session.begin():
        user_id = await _resolve_debug_user_id(session=session, user_id=None)
        result = await MemoryService(session).delete_by_id(
            user_id=user_id or 0,
            profile_id=memory_id,
        )
    return LocalReminderMutationResponse(
        status=result.status,
        message=result.message,
        user_id=user_id,
        reminder_id=result.profile.id if result.profile else None,
    )


@router.post("/reminders/{reminder_id}/complete", response_model=LocalReminderMutationResponse)
async def local_complete_reminder(
    reminder_id: int,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalReminderMutationResponse:
    return await _mutate_reminder(reminder_id=reminder_id, session=session, action="complete")


@router.delete("/reminders/{reminder_id}", response_model=LocalReminderMutationResponse)
async def local_delete_reminder(
    reminder_id: int,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalReminderMutationResponse:
    return await _mutate_reminder(reminder_id=reminder_id, session=session, action="delete")


@router.post("/reminders/{reminder_id}/trigger-now", response_model=LocalReminderMutationResponse)
async def local_trigger_reminder_now(
    reminder_id: int,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalReminderMutationResponse:
    if session is None:
        return LocalReminderMutationResponse(
            status="database_unavailable",
            message="数据库不可用。",
            user_id=None,
        )
    async with session.begin():
        user_id = await _resolve_debug_user_id(session=session, user_id=None)
        reminder = await ReminderService(session).repository.get_active(
            reminder_id=reminder_id,
            user_id=user_id or 0,
        )
        if reminder is None:
            return LocalReminderMutationResponse(
                status="not_found",
                message="待办事项不存在或已经处理。",
                user_id=user_id,
            )
        await ScheduledJobRepository(session).force_due_reminder_job(reminder=reminder)
    return LocalReminderMutationResponse(
        status="queued",
        message="待办事项已加入立即触发队列。",
        user_id=user_id,
        reminder_id=reminder_id,
    )


@router.get("/scheduled-jobs", response_model=LocalScheduledJobsResponse)
async def local_scheduled_jobs(
    user_id: int | None = None,
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalScheduledJobsResponse:
    if session is None:
        return LocalScheduledJobsResponse(user_id=None, items=[])
    async with session.begin():
        resolved_user_id = await _resolve_debug_user_id(session=session, user_id=user_id)
        jobs = await ScheduledJobRepository(session).list_recent(
            user_id=resolved_user_id,
            limit=DEBUG_LIST_LIMIT,
        )
    return LocalScheduledJobsResponse(
        user_id=resolved_user_id,
        items=[
            LocalScheduledJobItem(
                id=item.id,
                job_type=item.job_type,
                ref_type=item.ref_type,
                ref_id=item.ref_id,
                next_run_at=item.next_run_at.isoformat(),
                status=item.status,
                retry_count=item.retry_count,
            )
            for item in jobs
        ],
    )


@router.post("/scheduler/run-once", response_model=LocalSchedulerRunResponse)
async def local_scheduler_run_once(
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalSchedulerRunResponse:
    if session is None:
        return LocalSchedulerRunResponse(
            status="database_unavailable",
            scanned=0,
            succeeded=0,
            failed=0,
            skipped=0,
        )
    async with session.begin():
        result = await SchedulerService(session, worker_id="local-debug").run_once()
    return LocalSchedulerRunResponse(status="success", **result.__dict__)


@router.get("/stats", response_model=LocalStatsResponse)
async def local_stats(
    _: None = ADMIN_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalStatsResponse:
    if session is None:
        return LocalStatsResponse(
            users=0,
            reminders_active=0,
            memories_active=0,
            life_records_active=0,
            subscriptions_active=0,
            scheduled_jobs_pending=0,
            message_logs=0,
        )
    async with session.begin():
        return LocalStatsResponse(
            users=await _count(session, select(func.count()).select_from(User)),
            reminders_active=await _count(
                session,
                select(func.count()).select_from(Reminder).where(Reminder.status == "active"),
            ),
            memories_active=await _count(
                session,
                select(func.count()).select_from(UserProfile).where(UserProfile.status == "active"),
            ),
            life_records_active=await _count(
                session,
                select(func.count()).select_from(LifeRecord).where(LifeRecord.status == "active"),
            ),
            subscriptions_active=await _count(
                session,
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.status == "active"),
            ),
            scheduled_jobs_pending=await _count(
                session,
                select(func.count())
                .select_from(ScheduledJob)
                .where(ScheduledJob.status == "pending"),
            ),
            message_logs=await _count(session, select(func.count()).select_from(MessageLog)),
        )


@asynccontextmanager
async def _session_transaction(session: AsyncSession | None) -> AsyncIterator[None]:
    if session is None:
        yield
        return
    async with session.begin():
        yield


async def _resolve_debug_user_id(
    *,
    session: AsyncSession | None,
    user_id: int | None,
) -> int | None:
    if user_id is not None or session is None:
        return user_id
    # Use one stable local user so the debug UI can create/query to-dos immediately.
    user = await UserRepository(session).get_or_create_wechat_user("local-debug-user")
    return user.id


async def _mutate_reminder(
    *,
    reminder_id: int,
    session: AsyncSession | None,
    action: str,
) -> LocalReminderMutationResponse:
    if session is None:
        return LocalReminderMutationResponse(
            status="database_unavailable",
            message="数据库不可用。",
            user_id=None,
        )
    async with session.begin():
        user_id = await _resolve_debug_user_id(session=session, user_id=None)
        repository = ReminderService(session).repository
        if action == "complete":
            reminder = await repository.mark_completed(
                reminder_id=reminder_id,
                user_id=user_id or 0,
            )
            status = "completed"
            message = "待办事项已完成。"
        else:
            reminder = await repository.soft_delete(reminder_id=reminder_id, user_id=user_id or 0)
            status = "deleted"
            message = "待办事项已删除。"
        if reminder is not None:
            await ScheduledJobRepository(session).cancel_pending_by_ref(
                job_type="reminder_due",
                ref_type="reminder",
                ref_id=reminder.id,
            )
    if reminder is None:
        return LocalReminderMutationResponse(
            status="not_found",
            message="待办事项不存在或已经处理。",
            user_id=user_id,
        )
    return LocalReminderMutationResponse(
        status=status,
        message=message,
        user_id=user_id,
        reminder_id=reminder.id,
    )


def _tool_log_fields(tool_result: dict[str, Any] | None) -> tuple[str | None, str | None]:
    if not tool_result:
        return None, None
    return tool_result.get("tool"), tool_result.get("status")


def _is_confirmation_message(message: str) -> bool:
    return message.strip() in {"确认", "对", "是", "是的", "好的", "没错", "可以"}


async def _resolve_confirmation_message(*, session: AsyncSession, user_id: int | None) -> str:
    logs = await MessageLogRepository(session).list_recent(user_id=user_id, limit=10)
    for item in logs:
        if item.direction != "in" or not item.content:
            continue
        if _is_confirmation_message(item.content):
            continue
        return item.content
    return "确认"


def build_local_agent_service(
    *,
    settings: Settings,
    session: AsyncSession | None,
) -> LocalAgentService:
    # Assemble the same Agent dependencies for debug and beta chat entry points.
    return LocalAgentService(
        DeepSeekProvider(settings),
        reminder_service=ReminderService(session) if session is not None else None,
        memory_service=(
            AgentMemoryService(settings, session=session) if session is not None else None
        ),
        life_record_service=LifeRecordService(session) if session is not None else None,
        briefing_service=BriefingService(session) if session is not None else None,
        market_service=MarketService(),
        commodity_service=CommodityService(),
        web_search_service=WebSearchService(
            provider=settings.web_search_provider,
            tavily_api_key=settings.tavily_api_key,
            google_api_key=settings.google_search_api_key,
            google_cx=settings.google_search_cx,
            timeout_seconds=settings.web_search_timeout_seconds,
        ),
    )


async def _count(session: AsyncSession, query) -> int:
    result = await session.execute(query)
    return int(result.scalar_one())
