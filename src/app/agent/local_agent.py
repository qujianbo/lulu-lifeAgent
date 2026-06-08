from dataclasses import dataclass

from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage

SYSTEM_PROMPT = """你是露露生活管家 Agent。
当前处于本地后端联调阶段，先完成日常生活问答、提醒意图理解和资讯偏好沟通。
回答要简洁、可靠；如果用户要设置提醒，先复述识别到的时间和事项。"""


@dataclass(frozen=True)
class LocalAgentResult:
    content: str
    model: str
    provider: str
    latency_ms: int
    intent: str


class LocalAgentService:
    def __init__(self, llm: DeepSeekProvider) -> None:
        self.llm = llm

    async def chat(self, user_message: str) -> LocalAgentResult:
        # Minimal Agent path before LangGraph nodes and tools are wired in.
        response = await self.llm.chat(
            [
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=user_message),
            ],
            temperature=0.2,
            max_tokens=512,
        )
        return LocalAgentResult(
            content=response.content,
            model=response.model,
            provider=response.provider,
            latency_ms=response.latency_ms,
            intent=_infer_mvp_intent(user_message),
        )


def _infer_mvp_intent(user_message: str) -> str:
    # Lightweight local label for debugging before LangGraph intent routing exists.
    if any(keyword in user_message for keyword in ("提醒", "叫我", "闹钟", "待办")):
        return "create_reminder_candidate"
    if any(keyword in user_message for keyword in ("新闻", "资讯", "早报", "简报")):
        return "briefing_candidate"
    return "general_qa"
