import json
from decimal import Decimal

from app.agent.graph import LifeAgentGraph
from app.services.llm.types import LLMResponse
from app.services.markets import MarketQuote, MarketQuoteResult


class FakeLLM:
    async def chat(self, messages, *args, **kwargs) -> LLMResponse:
        if "意图路由器" in messages[0].content:
            user_message = messages[-1].content
            intent = "general_qa"
            if "提醒" in user_message or "待办" in user_message:
                intent = "create_reminder"
            if "记住" in user_message:
                intent = "memory_update"
            if "忘掉" in user_message:
                intent = "memory_delete"
            if "记账" in user_message:
                intent = "create_life_record"
            if "科技新闻" in user_message:
                intent = "briefing"
            if (
                "股票" in user_message
                or "证券" in user_message
                or "AAPL" in user_message
                or "指数" in user_message
            ):
                intent = "stock_query"
            if user_message.strip() == "用户消息：":
                intent = "unknown"
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": intent,
                        "confidence": 0.99,
                        "reason": "测试分类",
                        "slots": {},
                    },
                    ensure_ascii=False,
                ),
                model="fake-model",
                provider="fake",
                latency_ms=1,
                finish_reason="stop",
            )
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


class FakeLifeRecordService:
    async def create_from_text(self, *, user_id: int, text: str):
        class Result:
            status = "created"
            message = "备忘录已保存。"
            needs_clarification = False
            record = None

        return Result()

    async def list_active(self, *, user_id: int, record_type: str | None = None, limit: int = 20):
        return []


class FakeBriefingService:
    async def handle_from_text(
        self,
        *,
        user_id: int,
        text: str,
        memory_topics=None,
    ):
        class Result:
            status = "preview"
            message = "当前先返回资讯偏好预览。"
            subscription = None
            preview_topics = ["AI"]

        return Result()


class FakeMarketService:
    async def query_from_text(self, text: str):
        return MarketQuoteResult(
            status="success",
            message="证券基础信息查询成功。",
            quotes=[
                MarketQuote(
                    symbol="000001.SS",
                    name="上证指数",
                    market="上交所",
                    currency="CNY",
                    price=Decimal("3888.88"),
                    change=Decimal("12.34"),
                    change_percent=Decimal("0.32"),
                    exchange_time="2026-06-11T14:30:00+00:00",
                )
            ],
        )


async def test_agent_graph_routes_create_reminder() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "明早 8 点待办：带身份证"})

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


async def test_agent_graph_routes_life_record_create() -> None:
    graph = LifeAgentGraph(FakeLLM(), life_record_service=FakeLifeRecordService())

    result = await graph.ainvoke({"raw_message": "记账 午饭花了 35 元", "user_id": 1})

    assert result["intent"] == "create_life_record"
    assert result["tool_result"]["tool"] == "create_life_record"
    assert result["tool_result"]["status"] == "created"


async def test_agent_graph_routes_briefing() -> None:
    graph = LifeAgentGraph(FakeLLM(), briefing_service=FakeBriefingService())

    result = await graph.ainvoke({"raw_message": "今天有什么科技新闻", "user_id": 1})

    assert result["intent"] == "briefing"
    assert result["tool_result"]["tool"] == "briefing_subscription"
    assert result["tool_result"]["status"] == "preview"


async def test_agent_graph_routes_stock_query_with_direct_response() -> None:
    graph = LifeAgentGraph(FakeLLM(), market_service=FakeMarketService())

    result = await graph.ainvoke({"raw_message": "查一下上证指数", "user_id": 1})

    assert result["intent"] == "stock_query"
    assert result["tool_result"]["tool"] == "stock_query"
    assert result["tool_result"]["status"] == "success"
    assert result["provider"] == "local"
    assert "上证指数" in result["final_response"]
    assert "确认" not in result["final_response"]


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
