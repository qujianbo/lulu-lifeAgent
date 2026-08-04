import asyncio
import os
from datetime import datetime
from typing import Any

from app.config import Settings
from app.services.agent_memory.schemas import MemoryItem, MemoryMessage


class Mem0ClientError(RuntimeError):
    pass


class Mem0MemoryClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._memory: Any | None = None

    async def search(self, *, user_id: int, query: str, limit: int) -> list[MemoryItem]:
        memory = self._get_memory()
        result = await asyncio.to_thread(
            memory.search,
            query=query,
            filters={"user_id": _mem0_user_id(user_id)},
            top_k=limit,
        )
        return _items_from_response(result)

    async def add_conversation(
        self,
        *,
        user_id: int,
        messages: list[MemoryMessage],
    ) -> list[MemoryItem]:
        memory = self._get_memory()
        payload = [{"role": item.role, "content": item.content} for item in messages]
        result = await asyncio.to_thread(
            memory.add,
            payload,
            user_id=_mem0_user_id(user_id),
            metadata={"source": "life_agent_chat"},
        )
        return _items_from_response(result)

    async def list(self, *, user_id: int, limit: int) -> list[MemoryItem]:
        memory = self._get_memory()
        result = await asyncio.to_thread(
            memory.get_all,
            filters={"user_id": _mem0_user_id(user_id)},
            top_k=limit,
        )
        return _items_from_response(result)

    async def delete(self, *, memory_id: str) -> None:
        memory = self._get_memory()
        await asyncio.to_thread(memory.delete, memory_id)

    def _get_memory(self) -> Any:
        if self._memory is None:
            self._memory = self._build_memory()
        return self._memory

    def _build_memory(self) -> Any:
        try:
            from mem0 import Memory
        except ImportError as exc:
            raise Mem0ClientError("mem0ai is not installed") from exc

        _set_provider_env(self.settings)
        try:
            return Memory.from_config(_build_mem0_config(self.settings))
        except Exception as exc:
            raise Mem0ClientError(f"failed to initialize mem0: {exc}") from exc


def _build_mem0_config(settings: Settings) -> dict[str, Any]:
    config: dict[str, Any] = {
        "llm": {
            "provider": settings.mem0_llm_provider,
            "config": {
                "model": settings.mem0_llm_model,
                "api_key": settings.mem0_llm_api_key or settings.deepseek_api_key,
                "deepseek_base_url": settings.mem0_llm_base_url.rstrip("/"),
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": settings.qdrant_collection,
                "host": settings.qdrant_host,
                "port": settings.qdrant_port,
            },
        },
    }
    if settings.mem0_embedding_dims is not None:
        config["vector_store"]["config"]["embedding_model_dims"] = settings.mem0_embedding_dims
    if settings.mem0_embedder_provider:
        embedder_config: dict[str, Any] = {}
        if settings.mem0_embedder_model:
            embedder_config["model"] = settings.mem0_embedder_model
        if settings.mem0_embedder_api_key:
            embedder_config["api_key"] = settings.mem0_embedder_api_key
        if settings.mem0_embedding_dims is not None:
            embedder_config["embedding_dims"] = settings.mem0_embedding_dims
        config["embedder"] = {
            "provider": settings.mem0_embedder_provider,
            "config": embedder_config,
        }
    return config


def _set_provider_env(settings: Settings) -> None:
    # mem0 providers may read keys from environment during initialization.
    deepseek_key = settings.mem0_llm_api_key or settings.deepseek_api_key
    if deepseek_key:
        os.environ.setdefault("DEEPSEEK_API_KEY", deepseek_key)
    if settings.mem0_llm_base_url:
        os.environ.setdefault("DEEPSEEK_API_BASE", settings.mem0_llm_base_url.rstrip("/"))
    if settings.mem0_embedder_api_key and settings.mem0_embedder_provider == "openai":
        os.environ.setdefault("OPENAI_API_KEY", settings.mem0_embedder_api_key)


def _items_from_response(response: Any) -> list[MemoryItem]:
    if response is None:
        return []
    raw_items = response.get("results", response) if isinstance(response, dict) else response
    if not isinstance(raw_items, list):
        raw_items = [raw_items]
    items = []
    for raw in raw_items:
        item = _item_from_raw(raw)
        if item is not None:
            items.append(item)
    return items


def _item_from_raw(raw: Any) -> MemoryItem | None:
    if not isinstance(raw, dict):
        return None
    content = raw.get("memory") or raw.get("text") or raw.get("content") or raw.get("data")
    if not content:
        return None
    memory_id = str(raw.get("id") or raw.get("memory_id") or raw.get("vector_id") or "")
    if not memory_id:
        memory_id = str(abs(hash(str(content))))
    return MemoryItem(
        memory_id=memory_id,
        content=str(content),
        score=_float_or_none(raw.get("score")),
        metadata=_dict_or_empty(raw.get("metadata")),
        created_at=_datetime_or_none(raw.get("created_at")),
        updated_at=_datetime_or_none(raw.get("updated_at")),
    )


def _mem0_user_id(user_id: int) -> str:
    return str(user_id)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
