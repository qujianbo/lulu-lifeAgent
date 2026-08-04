from app.config import Settings
from app.services.agent_memory import AgentMemoryService, MemoryItem, MemoryMessage


class FakeMemoryClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.deleted: list[str] = []

    async def search(self, *, user_id: int, query: str, limit: int):
        if self.fail:
            raise RuntimeError("search failed")
        return [MemoryItem(memory_id="mem_1", content=f"偏好：{query}", score=0.9)]

    async def add_conversation(self, *, user_id: int, messages: list[MemoryMessage]):
        if self.fail:
            raise RuntimeError("add failed")
        return [MemoryItem(memory_id="mem_2", content=messages[0].content)]

    async def list(self, *, user_id: int, limit: int):
        return [MemoryItem(memory_id="mem_3", content="用户关注 AI")]

    async def delete(self, *, memory_id: str):
        self.deleted.append(memory_id)


def _settings(*, enabled: bool = True, write_enabled: bool = True) -> Settings:
    return Settings(
        memory_enabled=enabled,
        memory_write_enabled=write_enabled,
        deepseek_api_key="test",
        mem0_embedder_provider="openai",
        mem0_embedder_api_key="test",
    )


async def test_memory_service_skips_when_disabled() -> None:
    service = AgentMemoryService(_settings(enabled=False), client=FakeMemoryClient())

    result = await service.search(user_id=1, query="金价")

    assert result.status == "skipped"
    assert result.items == []


async def test_memory_service_search_returns_items() -> None:
    service = AgentMemoryService(_settings(), client=FakeMemoryClient())

    result = await service.search(user_id=1, query="金价", limit=3)

    assert result.status == "succeeded"
    assert result.items[0].memory_id == "mem_1"
    assert "金价" in result.items[0].content


async def test_memory_service_add_manual_uses_client() -> None:
    service = AgentMemoryService(_settings(), client=FakeMemoryClient())

    result = await service.add_manual(user_id=1, content="以后金价用人民币每克")

    assert result.status == "succeeded"
    assert result.items[0].content == "以后金价用人民币每克"


async def test_memory_service_delete_by_query_deletes_single_match() -> None:
    client = FakeMemoryClient()
    service = AgentMemoryService(_settings(), client=client)

    result = await service.delete(user_id=1, query="黄金偏好")

    assert result.status == "deleted"
    assert client.deleted == ["mem_1"]


async def test_memory_service_returns_failed_on_client_error() -> None:
    service = AgentMemoryService(_settings(), client=FakeMemoryClient(fail=True))

    result = await service.search(user_id=1, query="金价")

    assert result.status == "failed"
    assert "search failed" in str(result.error_message)
