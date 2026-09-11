from datetime import UTC, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.planner import PlannerError
from app.api.local import (
    LocalChatRequest,
    LocalChatResponse,
    _chat_with_optional_database,
    build_local_agent_service,
)
from app.config import Settings, get_settings
from app.dependencies import get_database_session
from app.models import BetaFeedback, BetaUser
from app.observability import LangSmithMonitor
from app.repositories import (
    ConversationRepository,
    InAppNotificationRepository,
    LifeRecordRepository,
    ReminderRepository,
    SubscriptionRepository,
)
from app.services.beta_auth import BETA_SESSION_COOKIE, BetaAuthService
from app.services.llm.deepseek import DeepSeekProviderError
from app.services.notifications import EmailNotificationService
from app.services.reminders.service import ReminderService

router = APIRouter(prefix="/api/beta", tags=["beta"])
SETTINGS_DEPENDENCY = Depends(get_settings)
DATABASE_SESSION_DEPENDENCY = Depends(get_database_session)


class BetaChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class BetaFeedbackRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="general", max_length=64)
    page_url: str | None = Field(default=None, max_length=1000)
    context: dict[str, Any] | None = None
    trace_id: str | None = Field(default=None, max_length=128)
    satisfied: bool | None = None


class BetaFeedbackResponse(BaseModel):
    id: int
    status: str


class ReminderPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    scheduled_at: datetime | None = None
    status: str | None = Field(default=None, pattern="^(active|completed)$")


class NotificationSettingsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    email_enabled: bool = True
    email_reminder_enabled: bool = True
    email_daily_briefing_enabled: bool = True
    email_daily_briefing_time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


async def require_beta_user(
    session_token: Annotated[str | None, Cookie(alias=BETA_SESSION_COOKIE)] = None,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> BetaUser:
    # User-facing beta APIs must always run behind a valid login session.
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        user = await BetaAuthService(session).authenticate_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


BETA_USER_DEPENDENCY = Depends(require_beta_user)


@router.post("/chat", response_model=LocalChatResponse)
async def beta_chat(
    payload: BetaChatRequest,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> LocalChatResponse:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    service = build_local_agent_service(settings=settings, session=session)
    local_payload = LocalChatRequest(
        message=payload.message,
        user_id=beta_user.user_id,
        session_id=payload.session_id,
    )
    try:
        user_id, result = await _chat_with_optional_database(
            service=service,
            session=session,
            payload=local_payload,
            channel="beta_web",
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
        session_id=result.session_id,
        trace_id=result.trace_id,
    )


@router.post("/feedback", response_model=BetaFeedbackResponse)
async def beta_feedback(
    payload: BetaFeedbackRequest,
    request: Request,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    settings: Settings = SETTINGS_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> BetaFeedbackResponse:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    now = datetime.now(UTC)
    async with session.begin():
        item = BetaFeedback(
            user_id=beta_user.user_id,
            beta_user_id=beta_user.id,
            category=payload.category.strip() or "general",
            content=payload.content.strip(),
            page_url=payload.page_url,
            user_agent=request.headers.get("user-agent"),
            status="open",
            extra_metadata={
                **(payload.context or {}),
                "trace_id": payload.trace_id,
                "satisfied": payload.satisfied,
            },
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        await session.flush()
    if payload.satisfied is not None and payload.trace_id:
        LangSmithMonitor(settings).record_feedback(
            trace_id=payload.trace_id,
            key="user_satisfaction",
            score=payload.satisfied,
            comment=payload.content,
        )
    return BetaFeedbackResponse(id=item.id, status=item.status)


@router.get("/home")
async def beta_home(
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    reminders = await ReminderRepository(session).list_active(user_id=beta_user.user_id, limit=20)
    records = await LifeRecordRepository(session).list_active(user_id=beta_user.user_id, limit=5)
    subscriptions = await SubscriptionRepository(session).list_active(
        user_id=beta_user.user_id, limit=5
    )
    notifications = InAppNotificationRepository(session)
    now_local = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = now_local.date()
    today_items = [
        item
        for item in reminders
        if item.scheduled_at
        and item.scheduled_at.astimezone(ZoneInfo("Asia/Shanghai")).date() == today
    ][:5]
    upcoming = [item for item in reminders if item not in today_items][:5]
    return {
        "today": now_local.date().isoformat(),
        "today_reminders": [_reminder_item(item) for item in today_items],
        "upcoming_reminders": [_reminder_item(item) for item in upcoming],
        "recent_records": [_record_item(item) for item in records],
        "briefing": {
            "status": "ready" if subscriptions else "empty",
            "topics": _subscription_topics(subscriptions),
        },
        "unread_notifications": await notifications.unread_count(user_id=beta_user.user_id),
    }


@router.get("/reminders")
async def beta_reminders(
    status: str | None = None,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    items = await ReminderRepository(session).list_for_user(
        user_id=beta_user.user_id, status=status, limit=50
    )
    return {"items": [_reminder_item(item) for item in items]}


@router.patch("/reminders/{reminder_id}")
async def beta_update_reminder(
    reminder_id: int,
    payload: ReminderPatchRequest,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        service = ReminderService(session)
        if payload.status == "completed":
            result = await service.complete_from_text(
                user_id=beta_user.user_id, text=f"#{reminder_id}"
            )
            item = result.reminder
        else:
            item = await service.repository.update_active(
                reminder_id=reminder_id,
                user_id=beta_user.user_id,
                title=payload.title,
                scheduled_at=payload.scheduled_at,
            )
            if item is not None and payload.scheduled_at is not None:
                await service.scheduled_jobs.reschedule_reminder_job(reminder=item)
    if item is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    return _reminder_item(item)


@router.delete("/reminders/{reminder_id}")
async def beta_delete_reminder(
    reminder_id: int,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        result = await ReminderService(session).delete_from_text(
            user_id=beta_user.user_id, text=f"#{reminder_id}"
        )
    if result.reminder is None:
        raise HTTPException(status_code=404, detail="reminder not found")
    return {"ok": True}


@router.post("/conversations")
async def beta_create_conversation(
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        item = await ConversationRepository(session).get_or_create(user_id=beta_user.user_id)
    return _conversation_item(item)


@router.get("/conversations")
async def beta_conversations(
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    items = await ConversationRepository(session).list_for_user(user_id=beta_user.user_id)
    return {"items": [_conversation_item(item) for item in items]}


@router.get("/conversations/{conversation_uuid}/messages")
async def beta_conversation_messages(
    conversation_uuid: str,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    repository = ConversationRepository(session)
    conversation = await repository.get_by_uuid(
        conversation_uuid=conversation_uuid, user_id=beta_user.user_id
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    items = await repository.list_messages(
        conversation_id=conversation.id, user_id=beta_user.user_id, limit=80
    )
    return {
        "conversation": _conversation_item(conversation),
        "items": [
            {
                "id": item.id,
                "role": item.role,
                "content": item.content,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


@router.get("/notification-settings")
async def beta_notification_settings(
    settings: Settings = SETTINGS_DEPENDENCY,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    result = await EmailNotificationService(session, settings).get_user_email_settings(
        user_id=beta_user.user_id
    )
    result.pop("email_timezone", None)
    return result


@router.put("/notification-settings")
async def beta_update_notification_settings(
    payload: NotificationSettingsRequest,
    settings: Settings = SETTINGS_DEPENDENCY,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        await EmailNotificationService(session, settings).set_user_email(
            user_id=beta_user.user_id,
            email=payload.email,
            enabled=payload.email_enabled,
            reminder_enabled=payload.email_reminder_enabled,
            daily_briefing_enabled=payload.email_daily_briefing_enabled,
            daily_briefing_time=payload.email_daily_briefing_time,
        )
    return {"ok": True}


@router.post("/notification-settings/test")
async def beta_test_notification(
    settings: Settings = SETTINGS_DEPENDENCY,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    try:
        async with session.begin():
            await EmailNotificationService(session, settings).create_test_email_job(
                user_id=beta_user.user_id
            )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/notifications")
async def beta_notifications(
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    items = await InAppNotificationRepository(session).list_for_user(
        user_id=beta_user.user_id
    )
    return {
        "items": [
            {
                "id": item.id,
                "type": item.notification_type,
                "title": item.title,
                "content": item.content,
                "read": item.read_at is not None,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ]
    }


@router.post("/notifications/{notification_id}/read")
async def beta_read_notification(
    notification_id: int,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
    session: AsyncSession | None = DATABASE_SESSION_DEPENDENCY,
) -> dict[str, bool]:
    if session is None:
        raise HTTPException(status_code=503, detail="database is not configured")
    async with session.begin():
        item = await InAppNotificationRepository(session).mark_read(
            notification_id=notification_id, user_id=beta_user.user_id
        )
    if item is None:
        raise HTTPException(status_code=404, detail="notification not found")
    return {"ok": True}


def _reminder_item(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "title": item.title,
        "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
        "status": item.status,
        "last_triggered_at": (
            item.last_triggered_at.isoformat() if item.last_triggered_at else None
        ),
    }


def _record_item(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "record_type": item.record_type,
        "content": item.content,
        "amount": str(item.amount) if item.amount is not None else None,
        "currency": item.currency,
        "recorded_at": item.recorded_at.isoformat(),
    }


def _conversation_item(item) -> dict[str, Any]:
    return {
        "id": str(item.conversation_uuid),
        "title": item.title or "新对话",
        "last_message_at": item.last_message_at.isoformat() if item.last_message_at else None,
    }


def _subscription_topics(items) -> list[str]:
    topics: list[str] = []
    for item in items:
        for topic in (item.preferences or {}).get("topics", []):
            if topic not in topics:
                topics.append(topic)
    return topics
