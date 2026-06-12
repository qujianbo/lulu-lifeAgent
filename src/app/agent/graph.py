from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.graph import END, StateGraph

from app.agent.planner import ToolCallingPlanner
from app.agent.schemas import ToolCallTrace
from app.agent.state import AgentState
from app.agent.tools.base import ToolContext
from app.agent.tools.builtin import build_tool_registry
from app.services.briefing import BriefingService
from app.services.life_records import LifeRecordService
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage
from app.services.markets import MarketService
from app.services.memory import MemoryService, format_memories_for_prompt
from app.services.reminders.service import ReminderService

SYSTEM_PROMPT = """你是露露生活管家 Agent。
当前处于后端联调阶段，能力包括日常问答、待办事项、备忘录、证券基础信息和资讯偏好沟通。
回答要简洁、可靠。涉及工具结果时，只能基于工具返回的信息回复，不要编造事实。"""


class LifeAgentGraph:
    def __init__(
        self,
        llm: DeepSeekProvider,
        *,
        reminder_service: ReminderService | None = None,
        memory_service: MemoryService | None = None,
        life_record_service: LifeRecordService | None = None,
        briefing_service: BriefingService | None = None,
        market_service: MarketService | None = None,
    ) -> None:
        self.llm = llm
        self.reminder_service = reminder_service
        self.memory_service = memory_service
        self.life_record_service = life_record_service
        self.briefing_service = briefing_service
        self.market_service = market_service
        self.tool_registry = build_tool_registry(
            reminder_service=reminder_service,
            memory_service=memory_service,
            life_record_service=life_record_service,
            briefing_service=briefing_service,
            market_service=market_service,
        )
        self.planner_service = ToolCallingPlanner(llm, self.tool_registry)
        self.graph = self._build_graph()

    async def ainvoke(self, state: AgentState) -> AgentState:
        result = await self.graph.ainvoke(state)
        return AgentState(result)

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("input_guardrail", self.input_guardrail)
        graph.add_node("context_loader", self.context_loader)
        graph.add_node("planner", self.planner)
        graph.add_node("tool_executor", self.tool_executor)
        graph.add_node("response_composer", self.response_composer)

        graph.set_entry_point("input_guardrail")
        graph.add_edge("input_guardrail", "context_loader")
        graph.add_edge("context_loader", "planner")
        graph.add_conditional_edges(
            "planner",
            self.route_after_planner,
            {
                "tool": "tool_executor",
                "compose": "response_composer",
            },
        )
        graph.add_edge("tool_executor", "response_composer")
        graph.add_edge("response_composer", END)
        return graph.compile()

    async def input_guardrail(self, state: AgentState) -> AgentState:
        # Keep the MVP guardrail simple: trim text and reject empty messages.
        message = state.get("raw_message", "").strip()
        if not message:
            return AgentState(sanitized_message="", intent="unknown")
        return AgentState(sanitized_message=message[:2000])

    async def context_loader(self, state: AgentState) -> AgentState:
        user_id = state.get("user_id")
        context: dict[str, Any] = {"memory_loaded": False, "reminders_loaded": False}
        if self.memory_service is not None and user_id is not None:
            memories = await self.memory_service.list_active(user_id=user_id, limit=20)
            context["memory_loaded"] = True
            context["memories"] = _memory_items(memories)
            context["memory_prompt"] = format_memories_for_prompt(memories)
        return AgentState(context=context)

    async def planner(self, state: AgentState) -> AgentState:
        message = state.get("sanitized_message", "")
        if not message:
            return AgentState(intent="unknown", planner=None, tool_trace=[])
        decision = await self.planner_service.plan(
            message=message,
            context=state.get("context") or {},
        )
        planner_payload = decision.model_dump()
        return AgentState(
            intent=_intent_from_planner(planner_payload),
            intent_confidence=decision.confidence,
            intent_reason=decision.reason,
            planner=planner_payload,
            tool_trace=[],
        )

    def route_after_planner(self, state: AgentState) -> str:
        planner = state.get("planner") or {}
        if planner.get("action") == "call_tool":
            return "tool"
        return "compose"

    async def tool_executor(self, state: AgentState) -> AgentState:
        planner = state.get("planner") or {}
        tool_name = planner.get("tool_name")
        if not tool_name:
            return AgentState(tool_result=None, tool_trace=state.get("tool_trace") or [])

        started = perf_counter()
        tool = self.tool_registry.get(tool_name)
        arguments = planner.get("arguments") or {}
        validated_args = tool.validate_arguments(arguments)
        result = await tool.handler(validated_args, self._tool_context(state))
        latency_ms = int((perf_counter() - started) * 1000)
        trace = ToolCallTrace(
            tool_name=tool_name,
            arguments=validated_args.model_dump(),
            status=result.status,
            latency_ms=latency_ms,
            error_code=result.error_code,
            result=result.data,
        )
        return AgentState(
            tool_result=result.data,
            tool_trace=[*(state.get("tool_trace") or []), trace.model_dump()],
        )

    def _tool_context(self, state: AgentState) -> ToolContext:
        context = state.get("context") or {}
        return ToolContext(
            user_id=state.get("user_id"),
            session_id=None,
            now=datetime.now(UTC),
            timezone="Asia/Shanghai",
            memories=context.get("memories") or [],
        )

    async def response_composer(self, state: AgentState) -> AgentState:
        message = state.get("sanitized_message", "")
        intent = state.get("intent", "unknown")
        if not message:
            return AgentState(
                final_response="我没有收到有效内容，可以重新说一遍吗？",
                model="none",
                provider="local",
                latency_ms=0,
            )

        planner = state.get("planner") or {}
        if planner.get("action") == "ask_clarification":
            return AgentState(
                final_response=planner.get("question") or "我还需要一点信息才能继续。",
                intent=intent,
                model="none",
                provider="local",
                latency_ms=0,
            )

        direct_response = _direct_tool_response(state)
        if direct_response is not None:
            return AgentState(
                final_response=direct_response,
                intent=intent,
                model="none",
                provider="local",
                latency_ms=0,
            )

        response = await self.llm.chat(
            [
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=_build_user_prompt(state)),
            ],
            temperature=0.2,
            max_tokens=512,
        )
        return AgentState(
            final_response=response.content,
            intent=intent,
            model=response.model,
            provider=response.provider,
            latency_ms=response.latency_ms,
        )


def _build_user_prompt(state: AgentState) -> str:
    message = state.get("sanitized_message", "")
    planner = state.get("planner") or {}
    tool_result = state.get("tool_result")
    context = state.get("context") or {}
    memories = context.get("memory_prompt", "无")
    return (
        f"用户消息：{message}\n"
        f"Planner 决策：{planner}\n"
        f"长期记忆：\n{memories}\n"
        f"工具结果：{tool_result}\n"
        "请给用户一个自然、简洁的回复。不能添加工具结果之外的事实。"
    )


def _intent_from_planner(planner: dict[str, Any]) -> str:
    if planner.get("action") == "final_answer":
        return planner.get("domain") or "general"
    if planner.get("action") == "ask_clarification":
        return planner.get("domain") or "clarification"
    return planner.get("tool_name") or planner.get("domain") or "unknown"


def _direct_tool_response(state: AgentState) -> str | None:
    tool_result = state.get("tool_result") or {}
    if tool_result.get("tool") not in {"market_overview", "market_quote", "market_hotspots"}:
        return None
    status = tool_result.get("status")
    if status == "success":
        hotspots = tool_result.get("hotspots") or []
        items = tool_result.get("items") or []
        if hotspots and items:
            return _format_market_overview(items, hotspots)
        if hotspots:
            return _format_market_hotspots(hotspots)
        if not items:
            return "没有查到对应的证券行情。"
        return "\n".join(_format_market_quote(item) for item in items)
    if status == "needs_clarification":
        return "请告诉我要查询的股票、指数名称或代码；如果想看市场概览，也可以问“今天热门板块”。"
    if status == "not_found":
        return "没有查到对应的证券基础信息，请换一个更明确的名称或代码。"
    if status in {"unavailable", "failed"}:
        return "证券行情源暂时不可用，请稍后再试。"
    return None


def _format_market_quote(item: dict[str, Any]) -> str:
    name = item.get("name") or "证券"
    symbol = item.get("symbol") or "-"
    market = item.get("market") or "市场"
    currency = item.get("currency") or ""
    price = item.get("price") or "-"
    change = _format_signed(item.get("change"))
    change_percent = _format_signed(item.get("change_percent"), suffix="%")
    exchange_time = _format_exchange_time(item.get("exchange_time"))
    return (
        f"{name}（{symbol}，{market}）当前价格 {price} {currency}，"
        f"涨跌 {change}，涨跌幅 {change_percent}。更新时间：{exchange_time}。"
    )


def _format_market_hotspots(items: list[dict[str, Any]]) -> str:
    industry = [item for item in items if item.get("board_type") == "行业板块"]
    concept = [item for item in items if item.get("board_type") == "概念板块"]
    lines = ["今日热门板块："]
    if industry:
        lines.append("行业板块：" + "；".join(_format_hotspot_item(item) for item in industry))
    if concept:
        lines.append("概念板块：" + "；".join(_format_hotspot_item(item) for item in concept))
    return "\n".join(lines)


def _format_market_overview(
    quote_items: list[dict[str, Any]],
    hotspot_items: list[dict[str, Any]],
) -> str:
    quote_text = "；".join(_format_market_quote_brief(item) for item in quote_items)
    lines = [f"今天市场概览：{quote_text}。"]
    industry = [item for item in hotspot_items if item.get("board_type") == "行业板块"]
    concept = [item for item in hotspot_items if item.get("board_type") == "概念板块"]
    if industry:
        lines.append("强势行业：" + "；".join(_format_hotspot_item(item) for item in industry))
    if concept:
        lines.append("热门概念：" + "；".join(_format_hotspot_item(item) for item in concept))
    return "\n".join(lines)


def _format_market_quote_brief(item: dict[str, Any]) -> str:
    name = item.get("name") or "证券"
    price = item.get("price") or "-"
    change_percent = _format_signed(item.get("change_percent"), suffix="%")
    return f"{name} {price}（{change_percent}）"


def _format_hotspot_item(item: dict[str, Any]) -> str:
    name = item.get("name") or "-"
    change_percent = _format_signed(item.get("change_percent"), suffix="%")
    inflow = _format_money(item.get("main_net_inflow"))
    return f"{name} {change_percent}，主力净流入 {inflow}"


def _format_money(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(amount) >= 100000000:
        return f"{amount / 100000000:.2f} 亿"
    if abs(amount) >= 10000:
        return f"{amount / 10000:.2f} 万"
    return f"{amount:.2f}"


def _format_signed(value: Any, *, suffix: str = "") -> str:
    if value in (None, ""):
        return "-"
    text = str(value)
    if text.startswith("-"):
        return f"{text}{suffix}"
    return f"+{text}{suffix}"


def _format_exchange_time(value: Any) -> str:
    if not value:
        return "未知"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _extract_reminder_slots(message: str) -> dict[str, Any]:
    # Minimal slot extraction for debug output before date parsing is introduced.
    time_keywords = ["今天", "明天", "后天", "早上", "中午", "下午", "晚上", "点"]
    has_time_hint = any(keyword in message for keyword in time_keywords)
    return {
        "original_text": message,
        "has_time_hint": has_time_hint,
        "task_text": message,
    }


def _reminder_create_tool_result(result) -> dict[str, Any]:
    if result.needs_clarification:
        return {
            "tool": "create_reminder",
            "status": result.status,
            "message": result.message,
            "needs_clarification": True,
        }
    reminder = result.reminder
    return {
        "tool": "create_reminder",
        "status": result.status,
        "message": result.message,
        "reminder_id": reminder.id if reminder else None,
        "title": reminder.title if reminder else None,
        "scheduled_at": (
            reminder.scheduled_at.isoformat() if reminder and reminder.scheduled_at else None
        ),
    }


def _reminder_query_tool_result(reminders) -> dict[str, Any]:
    return {
        "tool": "query_reminder",
        "status": "success",
        "count": len(reminders),
        "items": [
            {
                "id": item.id,
                "title": item.title,
                "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
                "status": item.status,
            }
            for item in reminders
        ],
    }


def _reminder_mutation_tool_result(tool: str, result) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": tool,
        "status": result.status,
        "message": result.message,
        "needs_confirmation": result.needs_confirmation,
    }
    if result.reminder is not None:
        payload["reminder"] = {
            "id": result.reminder.id,
            "title": result.reminder.title,
            "status": result.reminder.status,
        }
    if result.candidates:
        payload["candidates"] = [
            {
                "id": item.id,
                "title": item.title,
                "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
            }
            for item in result.candidates
        ]
    return payload


def _memory_items(memories) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "profile_key": item.profile_key,
            "profile_value": item.profile_value,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in memories
    ]


def _memory_save_tool_result(result) -> dict[str, Any]:
    profile = result.profile
    return {
        "tool": "memory_update",
        "status": result.status,
        "message": result.message,
        "needs_clarification": result.needs_clarification,
        "memory": _memory_items([profile])[0] if profile else None,
    }


def _memory_query_tool_result(memories) -> dict[str, Any]:
    return {
        "tool": "memory_query",
        "status": "success",
        "count": len(memories),
        "items": _memory_items(memories),
    }


def _memory_delete_tool_result(result) -> dict[str, Any]:
    profile = result.profile
    return {
        "tool": "memory_delete",
        "status": result.status,
        "message": result.message,
        "memory": _memory_items([profile])[0] if profile else None,
    }


def _life_record_items(records) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "memo_type": item.record_type,
            "record_type": item.record_type,
            "content": item.content,
            "amount": str(item.amount) if item.amount is not None else None,
            "currency": item.currency,
            "recorded_at": item.recorded_at.isoformat() if item.recorded_at else None,
            "status": item.status,
        }
        for item in records
    ]


def _life_record_create_tool_result(result) -> dict[str, Any]:
    record = result.record
    memo = _life_record_items([record])[0] if record else None
    return {
        "tool": "create_life_record",
        "status": result.status,
        "message": result.message,
        "needs_clarification": result.needs_clarification,
        "memo": memo,
        "record": memo,
    }


def _life_record_query_tool_result(records) -> dict[str, Any]:
    return {
        "tool": "query_life_record",
        "status": "success",
        "count": len(records),
        "items": _life_record_items(records),
    }


def _briefing_tool_result(result) -> dict[str, Any]:
    subscription = result.subscription
    return {
        "tool": "briefing_subscription",
        "status": result.status,
        "message": result.message,
        "preview_topics": result.preview_topics or [],
        "subscription": {
            "id": subscription.id,
            "subscription_type": subscription.subscription_type,
            "schedule_rule": subscription.schedule_rule,
            "next_push_at": subscription.next_push_at.isoformat()
            if subscription.next_push_at
            else None,
            "preferences": subscription.preferences,
        }
        if subscription
        else None,
    }


def _market_quote_tool_result(result) -> dict[str, Any]:
    return {
        "tool": "stock_query",
        "status": result.status,
        "message": result.message,
        "items": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "market": item.market,
                "currency": item.currency,
                "price": str(item.price) if item.price is not None else None,
                "change": str(item.change) if item.change is not None else None,
                "change_percent": (
                    str(item.change_percent) if item.change_percent is not None else None
                ),
                "exchange_time": item.exchange_time,
            }
            for item in result.quotes
        ],
        "hotspots": [
            {
                "board_type": item.board_type,
                "code": item.code,
                "name": item.name,
                "price": str(item.price) if item.price is not None else None,
                "change_percent": (
                    str(item.change_percent) if item.change_percent is not None else None
                ),
                "main_net_inflow": (
                    str(item.main_net_inflow) if item.main_net_inflow is not None else None
                ),
            }
            for item in result.hotspots or []
        ],
    }


def _memory_topics(state: AgentState) -> list[str] | None:
    context = state.get("context") or {}
    for item in context.get("memories") or []:
        if item.get("profile_key") == "briefing.topics":
            return [
                topic.strip()
                for topic in str(item.get("profile_value", "")).split(",")
                if topic.strip()
            ]
    return None
