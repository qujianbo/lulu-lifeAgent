from dataclasses import dataclass
from typing import Any

from app.agent.graph import LifeAgentGraph
from app.services.llm.deepseek import DeepSeekProvider
from app.services.reminders.service import ReminderService


@dataclass(frozen=True)
class LocalAgentResult:
    content: str
    model: str
    provider: str
    latency_ms: int
    intent: str
    tool_result: dict[str, Any] | None = None


class LocalAgentService:
    def __init__(
        self,
        llm: DeepSeekProvider,
        *,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self.graph = LifeAgentGraph(llm, reminder_service=reminder_service)

    async def chat(self, user_message: str, *, user_id: int | None = None) -> LocalAgentResult:
        # Local endpoint now goes through the same LangGraph skeleton used by Agent flows.
        state = await self.graph.ainvoke({"raw_message": user_message, "user_id": user_id})
        return LocalAgentResult(
            content=state.get("final_response", ""),
            model=state.get("model", "none"),
            provider=state.get("provider", "local"),
            latency_ms=state.get("latency_ms", 0),
            intent=state.get("intent", "unknown"),
            tool_result=state.get("tool_result"),
        )
