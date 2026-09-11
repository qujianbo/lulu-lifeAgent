from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.agent.graph import LifeAgentGraph
from app.observability import LangSmithMonitor
from app.services.agent_memory import AgentMemoryService
from app.services.briefing import BriefingService
from app.services.commodities import CommodityService
from app.services.life_records import LifeRecordService
from app.services.llm.deepseek import DeepSeekProvider
from app.services.markets import MarketService
from app.services.reminders.service import ReminderService
from app.services.web_search import WebSearchService


@dataclass(frozen=True)
class LocalAgentResult:
    content: str
    model: str
    provider: str
    latency_ms: int
    intent: str
    tool_result: dict[str, Any] | None = None
    planner: dict[str, Any] | None = None
    tool_trace: list[dict[str, Any]] | None = None
    memory_trace: dict[str, Any] | None = None
    session_id: str = ""
    trace_id: str | None = None


class LocalAgentService:
    def __init__(
        self,
        llm: DeepSeekProvider,
        *,
        reminder_service: ReminderService | None = None,
        memory_service: AgentMemoryService | None = None,
        life_record_service: LifeRecordService | None = None,
        briefing_service: BriefingService | None = None,
        market_service: MarketService | None = None,
        commodity_service: CommodityService | None = None,
        web_search_service: WebSearchService | None = None,
        monitor: LangSmithMonitor | None = None,
    ) -> None:
        self.graph = LifeAgentGraph(
            llm,
            reminder_service=reminder_service,
            memory_service=memory_service,
            life_record_service=life_record_service,
            briefing_service=briefing_service,
            market_service=market_service,
            commodity_service=commodity_service,
            web_search_service=web_search_service,
        )
        self.monitor = monitor

    async def chat(
        self,
        user_message: str,
        *,
        user_id: int | None = None,
        session_id: str | None = None,
        channel: str = "local",
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> LocalAgentResult:
        # Local endpoint now goes through the same LangGraph skeleton used by Agent flows.
        resolved_session_id = session_id or str(uuid4())
        input_state = {
            "raw_message": user_message,
            "user_id": user_id,
            "session_id": resolved_session_id,
            "context": {"conversation_history": conversation_history or []},
        }
        started = perf_counter()
        if self.monitor is not None:
            state, trace_id = await self.monitor.invoke(
                self.graph.ainvoke,
                input_state,
                session_id=resolved_session_id,
                channel=channel,
            )
        else:
            state = await self.graph.ainvoke(input_state)
            trace_id = None
        end_to_end_latency_ms = round((perf_counter() - started) * 1000)
        result = LocalAgentResult(
            content=state.get("final_response", ""),
            model=state.get("model", "none"),
            provider=state.get("provider", "local"),
            latency_ms=state.get("latency_ms", 0),
            intent=state.get("intent", "unknown"),
            tool_result=state.get("tool_result"),
            planner=state.get("planner"),
            tool_trace=state.get("tool_trace") or [],
            memory_trace=(state.get("context") or {}).get("memory_trace"),
            session_id=resolved_session_id,
            trace_id=trace_id,
        )
        if self.monitor is not None:
            self.monitor.record_deterministic_feedback(
                trace_id=trace_id,
                result=result,
                end_to_end_latency_ms=end_to_end_latency_ms,
            )
        return result
