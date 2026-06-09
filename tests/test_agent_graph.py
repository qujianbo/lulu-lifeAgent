from app.agent.graph import LifeAgentGraph
from app.services.llm.types import LLMResponse


class FakeLLM:
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(
            content="图回复正常",
            model="fake-model",
            provider="fake",
            latency_ms=3,
            finish_reason="stop",
        )


class FakeMemoryService:
    async def list_active(self, *, user_id: int, limit: int = 30):
        return []

    async def save_from_text(self, *, user_id: int, text: str):
        class Result:
            status = "saved"
            message = "我记住了。"
            needs_clarification = False
            profile = None

        return Result()

    async def delete_from_text(self, *, user_id: int, text: str):
        class Result:
            status = "deleted"
            message = "记忆已删除。"
            profile = None

        return Result()


async def test_agent_graph_routes_create_reminder() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "明早 8 点提醒我带身份证"})

    assert result["intent"] == "create_reminder"
    assert result["tool_result"]["tool"] == "create_reminder"
    assert result["tool_result"]["status"] == "dry_run"
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_routes_memory_update() -> None:
    graph = LifeAgentGraph(FakeLLM(), memory_service=FakeMemoryService())

    result = await graph.ainvoke({"raw_message": "记住我以后资讯更关注 AI 和财经", "user_id": 1})

    assert result["intent"] == "memory_update"
    assert result["tool_result"]["tool"] == "memory_update"
    assert result["tool_result"]["status"] == "saved"
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_routes_memory_delete() -> None:
    graph = LifeAgentGraph(FakeLLM(), memory_service=FakeMemoryService())

    result = await graph.ainvoke({"raw_message": "忘掉记忆 #1", "user_id": 1})

    assert result["intent"] == "memory_delete"
    assert result["tool_result"]["tool"] == "memory_delete"
    assert result["tool_result"]["status"] == "deleted"


async def test_agent_graph_routes_general_qa_without_tool() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "怎么安排今天的工作？"})

    assert result["intent"] == "general_qa"
    assert result.get("tool_result") is None
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_handles_empty_message_locally() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "   "})

    assert result["intent"] == "unknown"
    assert result["provider"] == "local"
    assert "有效内容" in result["final_response"]
