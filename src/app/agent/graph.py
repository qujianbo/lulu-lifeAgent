from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.intent import infer_intent
from app.agent.state import AgentState
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage
from app.services.reminders.service import ReminderService

SYSTEM_PROMPT = """你是露露生活管家 Agent。
当前处于后端联调阶段，能力包括日常问答、提醒意图理解和资讯偏好沟通。
回答要简洁、可靠；涉及提醒时必须复述识别到的时间和事项。"""


class LifeAgentGraph:
    def __init__(
        self,
        llm: DeepSeekProvider,
        *,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self.llm = llm
        self.reminder_service = reminder_service
        self.graph = self._build_graph()

    async def ainvoke(self, state: AgentState) -> AgentState:
        result = await self.graph.ainvoke(state)
        return AgentState(result)

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("input_guardrail", self.input_guardrail)
        graph.add_node("context_loader", self.context_loader)
        graph.add_node("intent_router", self.intent_router)
        graph.add_node("tool_executor", self.tool_executor)
        graph.add_node("response_composer", self.response_composer)

        graph.set_entry_point("input_guardrail")
        graph.add_edge("input_guardrail", "context_loader")
        graph.add_edge("context_loader", "intent_router")
        graph.add_conditional_edges(
            "intent_router",
            self.route_after_intent,
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
        # Placeholder for memory, reminders and user profile loading in later stages.
        return AgentState(context={"memory_loaded": False, "reminders_loaded": False})

    async def intent_router(self, state: AgentState) -> AgentState:
        return AgentState(intent=infer_intent(state.get("sanitized_message", "")))

    def route_after_intent(self, state: AgentState) -> str:
        if state.get("intent") in {
            "create_reminder",
            "query_reminder",
            "complete_reminder",
            "delete_reminder",
            "briefing",
        }:
            return "tool"
        return "compose"

    async def tool_executor(self, state: AgentState) -> AgentState:
        intent = state.get("intent")
        message = state.get("sanitized_message", "")
        if intent == "create_reminder":
            user_id = state.get("user_id")
            if self.reminder_service is not None and user_id is not None:
                result = await self.reminder_service.create_from_text(user_id=user_id, text=message)
                return AgentState(
                    slots=_extract_reminder_slots(message),
                    tool_result=_reminder_create_tool_result(result),
                )
            return AgentState(
                slots=_extract_reminder_slots(message),
                tool_result={
                    "tool": "create_reminder",
                    "status": "dry_run",
                    "message": "提醒工具尚未落库，当前只返回识别结果。",
                },
            )
        if intent == "query_reminder":
            user_id = state.get("user_id")
            if self.reminder_service is not None and user_id is not None:
                reminders = await self.reminder_service.list_active(user_id=user_id)
                return AgentState(tool_result=_reminder_query_tool_result(reminders))
            return AgentState(
                tool_result={
                    "tool": "query_reminder",
                    "status": "dry_run",
                    "message": "提醒查询工具将在 M5 接入数据库。",
                }
            )
        if intent == "complete_reminder":
            user_id = state.get("user_id")
            if self.reminder_service is not None and user_id is not None:
                result = await self.reminder_service.complete_from_text(
                    user_id=user_id,
                    text=message,
                )
                return AgentState(
                    tool_result=_reminder_mutation_tool_result("complete_reminder", result)
                )
            return AgentState(
                tool_result={
                    "tool": "complete_reminder",
                    "status": "dry_run",
                    "message": "提醒完成工具需要数据库连接。",
                }
            )
        if intent == "delete_reminder":
            user_id = state.get("user_id")
            if self.reminder_service is not None and user_id is not None:
                result = await self.reminder_service.delete_from_text(user_id=user_id, text=message)
                return AgentState(
                    tool_result=_reminder_mutation_tool_result("delete_reminder", result)
                )
            return AgentState(
                tool_result={
                    "tool": "delete_reminder",
                    "status": "dry_run",
                    "message": "提醒删除工具需要数据库连接。",
                }
            )
        if intent == "briefing":
            return AgentState(
                tool_result={
                    "tool": "briefing_subscription",
                    "status": "dry_run",
                    "message": "资讯订阅将在每日简报阶段接入。",
                }
            )
        return AgentState(tool_result=None)

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
    intent = state.get("intent", "unknown")
    tool_result = state.get("tool_result")
    slots = state.get("slots") or {}
    return (
        f"用户消息：{message}\n"
        f"识别意图：{intent}\n"
        f"提取信息：{slots}\n"
        f"工具结果：{tool_result}\n"
        "请给用户一个自然、简洁的回复。"
    )


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
