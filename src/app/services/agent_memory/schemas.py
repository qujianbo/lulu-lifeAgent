from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MemoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)
    occurred_at: datetime


class MemoryItem(BaseModel):
    memory_id: str
    content: str
    score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemorySearchResult(BaseModel):
    items: list[MemoryItem] = Field(default_factory=list)
    provider: Literal["mem0"] = "mem0"
    latency_ms: int = 0
    status: Literal["succeeded", "skipped", "failed"] = "succeeded"
    error_message: str | None = None


class MemoryWriteResult(BaseModel):
    status: Literal["succeeded", "skipped", "failed"]
    items: list[MemoryItem] = Field(default_factory=list)
    provider: Literal["mem0"] = "mem0"
    latency_ms: int = 0
    error_message: str | None = None


class MemoryDeleteResult(BaseModel):
    status: Literal["deleted", "skipped", "not_found", "needs_confirmation", "failed"]
    message: str
    items: list[MemoryItem] = Field(default_factory=list)
    provider: Literal["mem0"] = "mem0"
    latency_ms: int = 0
    error_message: str | None = None
