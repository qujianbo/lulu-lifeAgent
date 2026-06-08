from dataclasses import dataclass
from typing import Literal

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    provider: str
    latency_ms: int
    finish_reason: str | None = None
