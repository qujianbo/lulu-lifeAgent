from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.agent.local_agent import LocalAgentService
from app.config import Settings, get_settings
from app.services.llm.deepseek import DeepSeekProvider, DeepSeekProviderError
from app.services.llm.types import LLMMessage

router = APIRouter(prefix="/api/local", tags=["local"])
SETTINGS_DEPENDENCY = Depends(get_settings)


class DeepSeekPingResponse(BaseModel):
    ok: bool
    model: str
    content: str
    latency_ms: int


class LocalChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class LocalChatResponse(BaseModel):
    content: str
    intent: str
    model: str
    provider: str
    latency_ms: int
    tool_result: dict[str, Any] | None = None


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
) -> LocalChatResponse:
    service = LocalAgentService(DeepSeekProvider(settings))
    try:
        result = await service.chat(payload.message)
    except DeepSeekProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return LocalChatResponse(
        content=result.content,
        intent=result.intent,
        model=result.model,
        provider=result.provider,
        latency_ms=result.latency_ms,
        tool_result=result.tool_result,
    )
