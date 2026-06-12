import json
from decimal import Decimal

from app.agent.graph import LifeAgentGraph
from app.agent.tools import builtin
from app.services.briefing.rss import BriefingArticle
from app.services.commodities import CommodityQuote, CommodityQuoteResult
from app.services.llm.types import LLMResponse
from app.services.markets import MarketHotspot, MarketQuote, MarketQuoteResult


class FakeLLM:
    async def chat(self, messages, *args, **kwargs) -> LLMResponse:
        if "工具规划器" in messages[0].content:
            payload = json.loads(messages[-1].content)
            user_message = payload["user_message"]
            decision = {
                "action": "final_answer",
                "tool_name": None,
                "arguments": {},
                "domain": "general_qa",
                "confidence": 0.99,
                "reason": "测试规划",
                "question": None,
            }
            if "提醒" in user_message or "待办" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="todo_create",
                    arguments={"raw_text": user_message},
                    domain="todo",
                )
            if "记住" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="memory_save",
                    arguments={"raw_text": user_message},
                    domain="memory",
                )
            if "忘掉" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="memory_delete",
                    arguments={"raw_text": user_message},
                    domain="memory",
                )
            if "记账" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="memo_create",
                    arguments={"raw_text": user_message},
                    domain="memo",
                )
            if "科技新闻" in user_message or "AI 资讯" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="news_tech_ai",
                    arguments={"limit": 5},
                    domain="news",
                )
            if "大宗商品" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="news_commodities",
                    arguments={"limit": 5},
                    domain="news",
                )
            if "订阅" in user_message or "简报" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="briefing_preview",
                    arguments={"raw_text": user_message},
                    domain="briefing",
                )
            if "市场行情" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="market_overview",
                    arguments={"market": "A股", "include_hotspots": True},
                    domain="market",
                )
            elif "板块" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="market_hotspots",
                    arguments={"market": "A股", "limit": 5},
                    domain="market",
                )
            elif "金价" in user_message or "黄金" in user_message:
                decision.update(
                    action="call_tool",
                    tool_name="commodity_quote",
                    arguments={
                        "query": "黄金" if "一克" in user_message else user_message,
                    },
                    domain="commodity",
                )
            elif any(word in user_message for word in ("股票", "证券", "AAPL", "指数")):
                decision.update(
                    action="call_tool",
                    tool_name="market_quote",
                    arguments={"query": user_message, "market": "auto"},
                    domain="market",
                )
            return LLMResponse(
                content=json.dumps(decision, ensure_ascii=False),
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
        timezone: str = "Asia/Shanghai",
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
            quotes=[_fake_quote()],
        )

    async def query_hotspots(self, *, limit: int = 5):
        return MarketQuoteResult(
            status="success",
            message="热门板块查询成功。",
            quotes=[],
            hotspots=[_fake_hotspot()],
        )

    async def query_market_overview(self, *, hotspot_limit: int = 3):
        return MarketQuoteResult(
            status="success",
            message="市场概览查询成功。",
            quotes=[_fake_quote()],
            hotspots=[_fake_hotspot()],
        )


class FakeCommodityService:
    def __init__(self) -> None:
        self.last_query: str | None = None

    async def query_from_text(self, text: str):
        self.last_query = text
        return CommodityQuoteResult(
            status="success",
            message="商品行情查询成功。",
            items=[
                CommodityQuote(
                    symbol="GC=F",
                    name="COMEX 黄金期货",
                    price=Decimal("4198.6"),
                    currency="USD",
                    unit="美元/盎司",
                    exchange="COMEX",
                    exchange_time="2026-06-12T01:35:00-04:00",
                )
            ],
        )


def _fake_quote() -> MarketQuote:
    return MarketQuote(
        symbol="000001.SS",
        name="上证指数",
        market="上交所",
        currency="CNY",
        price=Decimal("3888.88"),
        change=Decimal("12.34"),
        change_percent=Decimal("0.32"),
        exchange_time="2026-06-11T14:30:00+00:00",
    )


def _fake_hotspot() -> MarketHotspot:
    return MarketHotspot(
        board_type="行业板块",
        code="BK0001",
        name="半导体",
        price=Decimal("1000"),
        change_percent=Decimal("3.21"),
        main_net_inflow=Decimal("123456789"),
    )


async def test_agent_graph_routes_create_reminder() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "明早 8 点待办：带身份证"})

    assert result["intent"] == "todo_create"
    assert result["planner"]["tool_name"] == "todo_create"
    assert result["tool_result"]["tool"] == "todo_create"
    assert result["tool_result"]["status"] == "failed"
    assert result["tool_trace"][0]["tool_name"] == "todo_create"
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_routes_memory_update() -> None:
    graph = LifeAgentGraph(FakeLLM(), memory_service=FakeMemoryService())

    result = await graph.ainvoke({"raw_message": "记住我以后资讯更关注 AI 和财经", "user_id": 1})

    assert result["intent"] == "memory_save"
    assert result["planner"]["tool_name"] == "memory_save"
    assert result["tool_result"]["tool"] == "memory_save"
    assert result["tool_result"]["status"] == "saved"
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_routes_memory_delete() -> None:
    graph = LifeAgentGraph(FakeLLM(), memory_service=FakeMemoryService())

    result = await graph.ainvoke({"raw_message": "忘掉记忆 #1", "user_id": 1})

    assert result["intent"] == "memory_delete"
    assert result["planner"]["tool_name"] == "memory_delete"
    assert result["tool_result"]["tool"] == "memory_delete"
    assert result["tool_result"]["status"] == "deleted"


async def test_agent_graph_routes_life_record_create() -> None:
    graph = LifeAgentGraph(FakeLLM(), life_record_service=FakeLifeRecordService())

    result = await graph.ainvoke({"raw_message": "记账 午饭花了 35 元", "user_id": 1})

    assert result["intent"] == "memo_create"
    assert result["planner"]["tool_name"] == "memo_create"
    assert result["tool_result"]["tool"] == "memo_create"
    assert result["tool_result"]["status"] == "created"


async def test_agent_graph_routes_briefing() -> None:
    graph = LifeAgentGraph(FakeLLM(), briefing_service=FakeBriefingService())

    result = await graph.ainvoke({"raw_message": "每天早上订阅 AI 简报", "user_id": 1})

    assert result["intent"] == "briefing_preview"
    assert result["planner"]["tool_name"] == "briefing_preview"
    assert result["tool_result"]["tool"] == "briefing_preview"
    assert result["tool_result"]["status"] == "preview"


async def test_agent_graph_routes_tech_ai_news(monkeypatch) -> None:
    async def fake_fetch_rss_articles(*, rss_urls, limit=5, timeout_seconds=10):
        return [BriefingArticle(title="AI 模型更新", link="https://example.com/ai", source="rss")]

    monkeypatch.setattr(builtin, "fetch_rss_articles", fake_fetch_rss_articles)
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "今天有什么科技新闻", "user_id": 1})

    assert result["intent"] == "news_tech_ai"
    assert result["planner"]["tool_name"] == "news_tech_ai"
    assert result["tool_result"]["tool"] == "news_tech_ai"
    assert result["tool_result"]["status"] == "success"
    assert "科技 AI 资讯" in result["final_response"]
    assert "AI 模型更新" in result["final_response"]


async def test_agent_graph_routes_commodity_news(monkeypatch) -> None:
    async def fake_fetch_rss_articles(*, rss_urls, limit=5, timeout_seconds=10):
        return [BriefingArticle(title="Oil prices move higher", link=None, source="rss")]

    monkeypatch.setattr(builtin, "fetch_rss_articles", fake_fetch_rss_articles)
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "国际大宗商品有什么新闻", "user_id": 1})

    assert result["intent"] == "news_commodities"
    assert result["planner"]["tool_name"] == "news_commodities"
    assert result["tool_result"]["tool"] == "news_commodities"
    assert result["tool_result"]["status"] == "success"
    assert "国际大宗商品资讯" in result["final_response"]
    assert "Oil prices" in result["final_response"]


async def test_agent_graph_routes_stock_query_with_direct_response() -> None:
    graph = LifeAgentGraph(FakeLLM(), market_service=FakeMarketService())

    result = await graph.ainvoke({"raw_message": "查一下上证指数", "user_id": 1})

    assert result["intent"] == "market_quote"
    assert result["planner"]["tool_name"] == "market_quote"
    assert result["tool_result"]["tool"] == "market_quote"
    assert result["tool_result"]["status"] == "success"
    assert result["provider"] == "local"
    assert "上证指数" in result["final_response"]
    assert "确认" not in result["final_response"]


async def test_agent_graph_routes_market_hotspots_with_direct_response() -> None:
    graph = LifeAgentGraph(FakeLLM(), market_service=FakeMarketService())

    result = await graph.ainvoke({"raw_message": "那今天的热门板块是哪些", "user_id": 1})

    assert result["intent"] == "market_hotspots"
    assert result["planner"]["tool_name"] == "market_hotspots"
    assert result["tool_result"]["tool"] == "market_hotspots"
    assert result["tool_result"]["status"] == "success"
    assert result["provider"] == "local"
    assert "今日热门板块" in result["final_response"]
    assert "半导体" in result["final_response"]


async def test_agent_graph_routes_market_overview_with_direct_response() -> None:
    graph = LifeAgentGraph(FakeLLM(), market_service=FakeMarketService())

    result = await graph.ainvoke({"raw_message": "今天市场行情如何", "user_id": 1})

    assert result["intent"] == "market_overview"
    assert result["planner"]["tool_name"] == "market_overview"
    assert result["tool_result"]["tool"] == "market_overview"
    assert result["tool_result"]["status"] == "success"
    assert result["provider"] == "local"
    assert "今天市场概览" in result["final_response"]
    assert "上证指数" in result["final_response"]
    assert "半导体" in result["final_response"]


async def test_agent_graph_routes_gold_price_without_symbol() -> None:
    graph = LifeAgentGraph(FakeLLM(), commodity_service=FakeCommodityService())

    result = await graph.ainvoke({"raw_message": "今日金价", "user_id": 1})

    assert result["intent"] == "commodity_quote"
    assert result["planner"]["tool_name"] == "commodity_quote"
    assert result["tool_result"]["tool"] == "commodity_quote"
    assert result["tool_result"]["status"] == "success"
    assert "COMEX 黄金期货" in result["final_response"]
    assert "美元/盎司" in result["final_response"]


async def test_agent_graph_passes_raw_commodity_message_to_tool() -> None:
    service = FakeCommodityService()
    graph = LifeAgentGraph(FakeLLM(), commodity_service=service)

    result = await graph.ainvoke({"raw_message": "黄金多少钱一克", "user_id": 1})

    assert result["planner"]["arguments"] == {"query": "黄金"}
    assert service.last_query == "黄金多少钱一克"
    assert result["tool_result"]["status"] == "success"


async def test_agent_graph_routes_general_qa_without_tool() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "怎么安排今天的工作？"})

    assert result["intent"] == "general_qa"
    assert result["planner"]["action"] == "final_answer"
    assert result.get("tool_result") is None
    assert result["final_response"] == "图回复正常"


async def test_agent_graph_handles_empty_message_locally() -> None:
    graph = LifeAgentGraph(FakeLLM())

    result = await graph.ainvoke({"raw_message": "   "})

    assert result["intent"] == "unknown"
    assert result["provider"] == "local"
    assert "有效内容" in result["final_response"]
