from typing import Any, TypedDict

AgentIntent = str


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: int | None
    public_user_id: int | None
    openid: str | None
    raw_message: str
    sanitized_message: str
    intent: str
    intent_confidence: float
    intent_reason: str | None
    slots: dict[str, Any]
    context: dict[str, Any]
    planner: dict[str, Any] | None
    planner_action: str
    tool_result: dict[str, Any] | None
    tool_trace: list[dict[str, Any]]
    tool_steps: int
    final_response: str
    model: str
    provider: str
    latency_ms: int
    llm_metrics: dict[str, int | float]
