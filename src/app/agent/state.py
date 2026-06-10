from typing import Any, Literal, TypedDict

AgentIntent = Literal[
    "general_qa",
    "create_reminder",
    "query_reminder",
    "complete_reminder",
    "delete_reminder",
    "briefing",
    "stock_query",
    "create_life_record",
    "query_life_record",
    "memory_update",
    "memory_query",
    "memory_delete",
    "unknown",
]


class AgentState(TypedDict, total=False):
    user_id: int | None
    public_user_id: int | None
    openid: str | None
    raw_message: str
    sanitized_message: str
    intent: AgentIntent
    intent_confidence: float
    intent_reason: str | None
    slots: dict[str, Any]
    context: dict[str, Any]
    tool_result: dict[str, Any] | None
    final_response: str
    model: str
    provider: str
    latency_ms: int
