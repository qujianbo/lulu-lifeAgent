from dataclasses import dataclass
from typing import Any

from app.agent.graph import LifeAgentGraph
from app.services.briefing import BriefingService
from app.services.life_records import LifeRecordService
from app.services.llm.deepseek import DeepSeekProvider
from app.services.memory import MemoryService
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
        memory_service: MemoryService | None = None,
        life_record_service: LifeRecordService | None = None,
        briefing_service: BriefingService | None = None,
    ) -> None:
        self.graph = LifeAgentGraph(
            llm,
            reminder_service=reminder_service,
            memory_service=memory_service,
            life_record_service=life_record_service,
            briefing_service=briefing_service,
        )

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
