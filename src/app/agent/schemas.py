import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

PlannerAction = Literal["call_tool", "final_answer", "ask_clarification"]
ToolStatus = Literal["success", "needs_clarification", "not_found", "failed", "dry_run"]


class PlannerDecision(BaseModel):
    action: PlannerAction
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    domain: str = "general"
    confidence: float = Field(ge=0, le=1)
    reason: str
    question: str | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "PlannerDecision":
        if self.action == "call_tool" and not self.tool_name:
            raise ValueError("tool_name is required when action is call_tool")
        if self.action != "call_tool" and self.tool_name is not None:
            raise ValueError("tool_name must be null unless action is call_tool")
        if self.action == "ask_clarification" and not self.question:
            raise ValueError("question is required when action is ask_clarification")
        return self


class ToolCallTrace(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus
    latency_ms: int = Field(ge=0)
    error_code: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


def strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text


def parse_planner_decision(content: str) -> PlannerDecision:
    try:
        payload = json.loads(strip_json_fence(content))
    except json.JSONDecodeError as exc:
        raise PlannerSchemaError(f"invalid planner json: {exc}") from exc
    try:
        return PlannerDecision.model_validate(payload)
    except ValidationError as exc:
        raise PlannerSchemaError(f"invalid planner schema: {exc}") from exc


class PlannerSchemaError(RuntimeError):
    pass
