import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.local_agent import LocalAgentService
from app.config import Settings, get_settings
from app.dependencies import get_database_session
from app.repositories import UserRepository
from app.services.llm.deepseek import DeepSeekProvider, DeepSeekProviderError
from app.services.llm.types import LLMMessage
from app.services.reminders.service import ReminderService

router = APIRouter(prefix="/api/local", tags=["local"])
logger = logging.getLogger(__name__)
SETTINGS_DEPENDENCY = Depends(get_settings)
DATABASE_SESSION_DEPENDENCY = Depends(get_database_session)


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


class LocalReminderItem(BaseModel):
    id: int
    title: str
    scheduled_at: str | None
    status: str


class LocalRemindersResponse(BaseModel):
    user_id: int | None
    items: list[LocalReminderItem]


class LocalReminderMutationResponse(BaseModel):
    status: str
    message: str
    user_id: int | None
    reminder_id: int | None = None


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
    reminder_service = ReminderService(session) if session is not None else None
    service = LocalAgentService(DeepSeekProvider(settings), reminder_service=reminder_service)
    try:
        user_id, result = await _chat_with_optional_database(
            service=service,
            session=session,
            payload=payload,
        )
    except DeepSeekProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LocalChatResponse(
        content=result.content,
        intent=result.intent,
        model=result.model,
        provider=result.provider,
        latency_ms=result.latency_ms,
        user_id=user_id,
        tool_result=result.tool_result,
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
            result = await service.chat(payload.message, user_id=user_id)
            return user_id, result
    except DeepSeekProviderError:
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
            reminders = await ReminderService(session).list_active(user_id=resolved_user_id or 0)
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
    # Use one stable local user so the debug UI can create/query reminders immediately.
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
            message = "提醒已完成。"
        else:
            reminder = await repository.soft_delete(reminder_id=reminder_id, user_id=user_id or 0)
            status = "deleted"
            message = "提醒已删除。"
    if reminder is None:
        return LocalReminderMutationResponse(
            status="not_found",
            message="提醒不存在或已经处理。",
            user_id=user_id,
        )
    return LocalReminderMutationResponse(
        status=status,
        message=message,
        user_id=user_id,
        reminder_id=reminder.id,
    )
