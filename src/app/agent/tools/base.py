from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from app.agent.schemas import ToolStatus


@dataclass(frozen=True)
class ToolContext:
    user_id: int | None
    session_id: str | None
    now: datetime
    timezone: str
    memories: list[dict[str, Any]]


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: ToolStatus
    content: str
    data: dict[str, Any]
    error_code: str | None = None


ToolHandler = Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler

    @property
    def args_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    def description_for_prompt(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "args_schema": self.args_schema,
        }

    def validate_arguments(self, arguments: dict[str, Any]) -> BaseModel:
        try:
            return self.args_model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolArgumentError(f"invalid arguments for {self.name}: {exc}") from exc


class ToolArgumentError(RuntimeError):
    pass


class ToolExecutionError(RuntimeError):
    pass
