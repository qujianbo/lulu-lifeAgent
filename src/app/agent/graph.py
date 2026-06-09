from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.intent import infer_intent
from app.agent.state import AgentState
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage

SYSTEM_PROMPT = """你是露露生活管家 Agent。
当前处于后端联调阶段，能力包括日常问答、提醒意图理解和资讯偏好沟通。
回答要简洁、可靠；涉及提醒时必须复述识别到的时间和事项。"""


class LifeAgentGraph:
    def __init__(self, llm: DeepSeekProvider) -> None:
        self.llm = llm
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
        if state.get("intent") in {"create_reminder", "query_reminder", "briefing"}:
            return "tool"
        return "compose"

    async def tool_executor(self, state: AgentState) -> AgentState:
        # Tools are dry-run in M4; M5 will replace these with real reminder services.
        intent = state.get("intent")
        message = state.get("sanitized_message", "")
        if intent == "create_reminder":
            return AgentState(
                slots=_extract_reminder_slots(message),
                tool_result={
                    "tool": "create_reminder",
                    "status": "dry_run",
                    "message": "提醒工具尚未落库，当前只返回识别结果。",
                },
            )
        if intent == "query_reminder":
            return AgentState(
                tool_result={
                    "tool": "query_reminder",
                    "status": "dry_run",
                    "message": "提醒查询工具将在 M5 接入数据库。",
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
