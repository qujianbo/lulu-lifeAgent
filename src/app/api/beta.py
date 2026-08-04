from datetime import UTC, datetime
from typing import Annotated, Any

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
from app.services.beta_auth import BETA_SESSION_COOKIE, BetaAuthService
from app.services.llm.deepseek import DeepSeekProviderError

router = APIRouter(prefix="/api/beta", tags=["beta"])
SETTINGS_DEPENDENCY = Depends(get_settings)
DATABASE_SESSION_DEPENDENCY = Depends(get_database_session)


class BetaChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class BetaFeedbackRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    category: str = Field(default="general", max_length=64)
    page_url: str | None = Field(default=None, max_length=1000)
    context: dict[str, Any] | None = None


class BetaFeedbackResponse(BaseModel):
    id: int
    status: str


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
    local_payload = LocalChatRequest(message=payload.message, user_id=beta_user.user_id)
    try:
        user_id, result = await _chat_with_optional_database(
            service=service,
            session=session,
            payload=local_payload,
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


@router.post("/feedback", response_model=BetaFeedbackResponse)
async def beta_feedback(
    payload: BetaFeedbackRequest,
    request: Request,
    beta_user: BetaUser = BETA_USER_DEPENDENCY,
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
            extra_metadata=payload.context,
            created_at=now,
            updated_at=now,
        )
        session.add(item)
        await session.flush()
    return BetaFeedbackResponse(id=item.id, status=item.status)
