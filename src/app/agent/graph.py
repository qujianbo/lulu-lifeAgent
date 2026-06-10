from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.intent_classifier import LLMIntentClassifier
from app.agent.state import AgentState
from app.services.briefing import BriefingService
from app.services.life_records import LifeRecordService
from app.services.life_records.service import infer_record_type_for_query
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage
from app.services.memory import MemoryService, format_memories_for_prompt
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
        memory_service: MemoryService | None = None,
        life_record_service: LifeRecordService | None = None,
        briefing_service: BriefingService | None = None,
    ) -> None:
        self.llm = llm
        self.reminder_service = reminder_service
        self.memory_service = memory_service
        self.life_record_service = life_record_service
        self.briefing_service = briefing_service
        self.intent_classifier = LLMIntentClassifier(llm)
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
        user_id = state.get("user_id")
        context: dict[str, Any] = {"memory_loaded": False, "reminders_loaded": False}
        if self.memory_service is not None and user_id is not None:
            memories = await self.memory_service.list_active(user_id=user_id, limit=20)
            context["memory_loaded"] = True
            context["memories"] = _memory_items(memories)
            context["memory_prompt"] = format_memories_for_prompt(memories)
        return AgentState(context=context)

    async def intent_router(self, state: AgentState) -> AgentState:
        message = state.get("sanitized_message", "")
        if not message:
            return AgentState(intent="unknown", slots={})
        result = await self.intent_classifier.classify(message)
        return AgentState(
            intent=result.intent,
            intent_confidence=result.confidence,
            intent_reason=result.reason,
            slots=result.slots,
        )

    def route_after_intent(self, state: AgentState) -> str:
        if state.get("intent") in {
            "create_reminder",
            "query_reminder",
            "complete_reminder",
            "delete_reminder",
            "briefing",
            "create_life_record",
            "query_life_record",
            "memory_update",
            "memory_query",
            "memory_delete",
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
            user_id = state.get("user_id")
            if self.briefing_service is not None and user_id is not None:
                result = await self.briefing_service.handle_from_text(
                    user_id=user_id,
                    text=message,
                    memory_topics=_memory_topics(state),
                )
                return AgentState(tool_result=_briefing_tool_result(result))
            return AgentState(
                tool_result={
                    "tool": "briefing_subscription",
                    "status": "dry_run",
                    "message": "资讯订阅将在每日简报阶段接入。",
                }
            )
        if intent == "create_life_record":
            user_id = state.get("user_id")
            if self.life_record_service is not None and user_id is not None:
                result = await self.life_record_service.create_from_text(
                    user_id=user_id,
                    text=message,
                )
                return AgentState(tool_result=_life_record_create_tool_result(result))
            return AgentState(
                tool_result={
                    "tool": "create_life_record",
                    "status": "dry_run",
                    "message": "生活记录工具需要数据库连接。",
                }
            )
        if intent == "query_life_record":
            user_id = state.get("user_id")
            if self.life_record_service is not None and user_id is not None:
                records = await self.life_record_service.list_active(
                    user_id=user_id,
                    record_type=infer_record_type_for_query(message),
                )
                return AgentState(tool_result=_life_record_query_tool_result(records))
            return AgentState(
                tool_result={
                    "tool": "query_life_record",
                    "status": "dry_run",
                    "message": "生活记录查询工具需要数据库连接。",
                }
            )
        if intent == "memory_update":
            user_id = state.get("user_id")
            if self.memory_service is not None and user_id is not None:
                result = await self.memory_service.save_from_text(user_id=user_id, text=message)
                return AgentState(tool_result=_memory_save_tool_result(result))
            return AgentState(
                tool_result={
                    "tool": "memory_update",
                    "status": "dry_run",
                    "message": "记忆工具需要数据库连接。",
                }
            )
        if intent == "memory_query":
            user_id = state.get("user_id")
            if self.memory_service is not None and user_id is not None:
                memories = await self.memory_service.list_active(user_id=user_id)
                return AgentState(tool_result=_memory_query_tool_result(memories))
            return AgentState(
                tool_result={
                    "tool": "memory_query",
                    "status": "dry_run",
                    "message": "记忆查询工具需要数据库连接。",
                }
            )
        if intent == "memory_delete":
            user_id = state.get("user_id")
            if self.memory_service is not None and user_id is not None:
                result = await self.memory_service.delete_from_text(user_id=user_id, text=message)
                return AgentState(tool_result=_memory_delete_tool_result(result))
            return AgentState(
                tool_result={
                    "tool": "memory_delete",
                    "status": "dry_run",
                    "message": "记忆删除工具需要数据库连接。",
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
    context = state.get("context") or {}
    memories = context.get("memory_prompt", "无")
    return (
        f"用户消息：{message}\n"
        f"识别意图：{intent}\n"
        f"提取信息：{slots}\n"
        f"长期记忆：\n{memories}\n"
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
    return {
        "tool": "create_life_record",
        "status": result.status,
        "message": result.message,
        "needs_clarification": result.needs_clarification,
        "record": _life_record_items([record])[0] if record else None,
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
