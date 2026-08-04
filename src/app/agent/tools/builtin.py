from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.tools.base import AgentTool, ToolContext, ToolResult
from app.agent.tools.registry import ToolRegistry
from app.services.agent_memory import AgentMemoryService
from app.services.briefing import BriefingService
from app.services.briefing.rss import fetch_rss_articles
from app.services.commodities import CommodityService
from app.services.life_records import LifeRecordService
from app.services.life_records.service import infer_record_type_for_query
from app.services.markets import MarketService
from app.services.reminders.service import ReminderService
from app.services.web_search import WebSearchService

MarketName = Literal["A股", "港股", "美股", "auto"]
TECH_AI_RSS_URLS = [
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.artificialintelligence-news.com/feed/",
]
COMMODITY_RSS_URLS = [
    "https://oilprice.com/rss/main",
    "https://www.mining.com/feed/",
]


class RawTextArgs(BaseModel):
    raw_text: str = Field(min_length=1, max_length=2000)


class MarketOverviewArgs(BaseModel):
    market: MarketName = "A股"
    include_hotspots: bool = True


class MarketQuoteArgs(BaseModel):
    query: str = Field(min_length=1, max_length=80)
    market: MarketName = "auto"


class MarketHotspotsArgs(BaseModel):
    market: MarketName = "A股"
    limit: int = Field(default=5, ge=1, le=10)


class CommodityQuoteArgs(BaseModel):
    query: str = Field(min_length=1, max_length=80)


class TodoQueryArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)


class MemoQueryArgs(BaseModel):
    raw_text: str = Field(default="", max_length=2000)
    record_type: str | None = None
    limit: int = Field(default=20, ge=1, le=50)


class MemoryQueryArgs(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)


class MemoryDeleteArgs(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    memory_id: str | None = Field(default=None, max_length=128)


class BriefingPreviewArgs(BaseModel):
    raw_text: str = Field(min_length=1, max_length=2000)


class NewsArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=10)


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=10)


def build_tool_registry(
    *,
    reminder_service: ReminderService | None = None,
    memory_service: AgentMemoryService | None = None,
    life_record_service: LifeRecordService | None = None,
    briefing_service: BriefingService | None = None,
    market_service: MarketService | None = None,
    commodity_service: CommodityService | None = None,
    web_search_service: WebSearchService | None = None,
) -> ToolRegistry:
    market = market_service or MarketService()
    commodity = commodity_service or CommodityService()
    web_search = web_search_service or WebSearchService()
    tools = [
        AgentTool(
            name="market_overview",
            description="当用户询问今天市场怎么样、大盘行情、A股市场、股市整体表现时使用。",
            args_model=MarketOverviewArgs,
            handler=lambda args, ctx: _market_overview(market, args, ctx),
        ),
        AgentTool(
            name="market_quote",
            description="查询股票、指数、ETF 的基础行情。用户给出证券名称、代码或简称时使用。",
            args_model=MarketQuoteArgs,
            handler=lambda args, ctx: _market_quote(market, args, ctx),
        ),
        AgentTool(
            name="market_hotspots",
            description="查询热门行业板块、热门概念板块、强势板块时使用。",
            args_model=MarketHotspotsArgs,
            handler=lambda args, ctx: _market_hotspots(market, args, ctx),
        ),
        AgentTool(
            name="commodity_quote",
            description="查询黄金、金价、白银、原油、油价等国际大宗商品实时行情。",
            args_model=CommodityQuoteArgs,
            handler=lambda args, ctx: _commodity_quote(commodity, args, ctx),
        ),
        AgentTool(
            name="todo_create",
            description="创建待办事项或提醒事项。用户要求提醒、待办、稍后处理时使用。",
            args_model=RawTextArgs,
            handler=lambda args, ctx: _todo_create(reminder_service, args, ctx),
        ),
        AgentTool(
            name="todo_query",
            description="查询用户当前待办事项、提醒列表时使用。",
            args_model=TodoQueryArgs,
            handler=lambda args, ctx: _todo_query(reminder_service, args, ctx),
        ),
        AgentTool(
            name="todo_complete",
            description="完成、标记已办某个待办事项时使用。",
            args_model=RawTextArgs,
            handler=lambda args, ctx: _todo_complete(reminder_service, args, ctx),
        ),
        AgentTool(
            name="todo_delete",
            description="删除、取消某个待办事项或提醒事项时使用。",
            args_model=RawTextArgs,
            handler=lambda args, ctx: _todo_delete(reminder_service, args, ctx),
        ),
        AgentTool(
            name="memo_create",
            description="创建备忘录，包括记账、体重、运动、睡眠、喝水、普通备忘。",
            args_model=RawTextArgs,
            handler=lambda args, ctx: _memo_create(life_record_service, args, ctx),
        ),
        AgentTool(
            name="memo_query",
            description="查询或统计备忘录、记账、体重、运动、睡眠等记录。",
            args_model=MemoQueryArgs,
            handler=lambda args, ctx: _memo_query(life_record_service, args, ctx),
        ),
        AgentTool(
            name="memory_save",
            description="保存长期偏好、个人信息、长期习惯或用户希望你记住的信息。",
            args_model=RawTextArgs,
            handler=lambda args, ctx: _memory_save(memory_service, args, ctx),
        ),
        AgentTool(
            name="memory_query",
            description="查询已经记住的长期偏好、个人信息或习惯。",
            args_model=MemoryQueryArgs,
            handler=lambda args, ctx: _memory_query(memory_service, args, ctx),
        ),
        AgentTool(
            name="memory_delete",
            description="删除或忘掉某条长期记忆、偏好或个人信息。",
            args_model=MemoryDeleteArgs,
            handler=lambda args, ctx: _memory_delete(memory_service, args, ctx),
        ),
        AgentTool(
            name="briefing_preview",
            description="生成资讯、新闻、早报、简报预览，或保存简报订阅偏好。",
            args_model=BriefingPreviewArgs,
            handler=lambda args, ctx: _briefing_preview(briefing_service, args, ctx),
        ),
        AgentTool(
            name="news_tech_ai",
            description="查询科技、AI、人工智能、模型、芯片、机器人等相关新闻。",
            args_model=NewsArgs,
            handler=_news_tech_ai,
        ),
        AgentTool(
            name="news_commodities",
            description="查询国际大宗商品相关新闻，包括原油、黄金、铜、矿业和能源。",
            args_model=NewsArgs,
            handler=_news_commodities,
        ),
        AgentTool(
            name="web_search",
            description=(
                "通用网页搜索兜底工具。用户询问当前事实、最新信息、未覆盖领域、"
                "百科知识、人物机构、产品服务或需要外部资料的问题时使用。"
            ),
            args_model=WebSearchArgs,
            handler=lambda args, ctx: _web_search(web_search, args, ctx),
        ),
    ]
    return ToolRegistry(tools)


async def _market_overview(
    service: MarketService,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    parsed = args if isinstance(args, MarketOverviewArgs) else MarketOverviewArgs()
    result = await service.query_market_overview(hotspot_limit=3 if parsed.include_hotspots else 0)
    data = _market_result_data("market_overview", result)
    return ToolResult("market_overview", _tool_status(result.status), result.message, data)


async def _market_quote(service: MarketService, args: BaseModel, ctx: ToolContext) -> ToolResult:
    parsed = args if isinstance(args, MarketQuoteArgs) else MarketQuoteArgs.model_validate(args)
    result = await service.query_from_text(parsed.query)
    data = _market_result_data("market_quote", result)
    return ToolResult("market_quote", _tool_status(result.status), result.message, data)


async def _market_hotspots(service: MarketService, args: BaseModel, ctx: ToolContext) -> ToolResult:
    parsed = (
        args if isinstance(args, MarketHotspotsArgs) else MarketHotspotsArgs.model_validate(args)
    )
    result = await service.query_hotspots(limit=parsed.limit)
    data = _market_result_data("market_hotspots", result)
    return ToolResult("market_hotspots", _tool_status(result.status), result.message, data)


async def _commodity_quote(
    service: CommodityService,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    parsed = (
        args if isinstance(args, CommodityQuoteArgs) else CommodityQuoteArgs.model_validate(args)
    )
    # 商品工具保留原始问法，避免模型规划时丢掉“每克”等单位信息。
    result = await service.query_from_text(ctx.raw_message or parsed.query)
    data = {
        "tool": "commodity_quote",
        "status": result.status,
        "message": result.message,
        "items": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "price": str(item.price) if item.price is not None else None,
                "currency": item.currency,
                "unit": item.unit,
                "exchange": item.exchange,
                "exchange_time": item.exchange_time,
            }
            for item in result.items
        ],
    }
    return ToolResult("commodity_quote", _tool_status(result.status), result.message, data)


async def _web_search(
    service: WebSearchService,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    parsed = args if isinstance(args, WebSearchArgs) else WebSearchArgs.model_validate(args)
    result = await service.search(parsed.query, limit=parsed.limit)
    data = {
        "tool": "web_search",
        "status": result.status,
        "message": result.message,
        "query": result.query,
        "items": [
            {
                "title": item.title,
                "link": item.link,
                "snippet": item.snippet,
                "source": item.source,
            }
            for item in result.items
        ],
    }
    return ToolResult("web_search", _tool_status(result.status), result.message, data)


async def _todo_create(
    service: ReminderService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("todo_create", "待办事项工具需要数据库连接。")
    parsed = args if isinstance(args, RawTextArgs) else RawTextArgs.model_validate(args)
    result = await service.create_from_text(
        user_id=ctx.user_id,
        text=parsed.raw_text,
        timezone=ctx.timezone,
    )
    return ToolResult(
        "todo_create",
        _tool_status(result.status),
        result.message,
        _todo_create_data(result),
    )


async def _todo_query(
    service: ReminderService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("todo_query", "待办事项查询工具需要数据库连接。")
    parsed = args if isinstance(args, TodoQueryArgs) else TodoQueryArgs.model_validate(args)
    reminders = await service.list_active(user_id=ctx.user_id, limit=parsed.limit)
    data = {
        "tool": "todo_query",
        "status": "success",
        "count": len(reminders),
        "items": _todo_items(reminders),
    }
    return ToolResult("todo_query", "success", "待办事项查询成功。", data)


async def _todo_complete(
    service: ReminderService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("todo_complete", "待办事项完成工具需要数据库连接。")
    parsed = args if isinstance(args, RawTextArgs) else RawTextArgs.model_validate(args)
    result = await service.complete_from_text(user_id=ctx.user_id, text=parsed.raw_text)
    data = _todo_mutation_data("todo_complete", result)
    return ToolResult("todo_complete", _tool_status(result.status), result.message, data)


async def _todo_delete(
    service: ReminderService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("todo_delete", "待办事项删除工具需要数据库连接。")
    parsed = args if isinstance(args, RawTextArgs) else RawTextArgs.model_validate(args)
    result = await service.delete_from_text(user_id=ctx.user_id, text=parsed.raw_text)
    data = _todo_mutation_data("todo_delete", result)
    return ToolResult("todo_delete", _tool_status(result.status), result.message, data)


async def _memo_create(
    service: LifeRecordService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("memo_create", "备忘录工具需要数据库连接。")
    parsed = args if isinstance(args, RawTextArgs) else RawTextArgs.model_validate(args)
    result = await service.create_from_text(user_id=ctx.user_id, text=parsed.raw_text)
    data = {
        "tool": "memo_create",
        "status": result.status,
        "message": result.message,
        "record": _memo_item(result.record) if result.record else None,
    }
    return ToolResult("memo_create", _tool_status(result.status), result.message, data)


async def _memo_query(
    service: LifeRecordService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("memo_query", "备忘录查询工具需要数据库连接。")
    parsed = args if isinstance(args, MemoQueryArgs) else MemoQueryArgs.model_validate(args)
    record_type = parsed.record_type or infer_record_type_for_query(parsed.raw_text)
    records = await service.list_active(
        user_id=ctx.user_id,
        record_type=record_type,
        limit=parsed.limit,
    )
    data = {
        "tool": "memo_query",
        "status": "success",
        "count": len(records),
        "items": [_memo_item(item) for item in records],
    }
    return ToolResult("memo_query", "success", "备忘录查询成功。", data)


async def _memory_save(
    service: AgentMemoryService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("memory_save", "记忆工具需要数据库连接。")
    parsed = args if isinstance(args, RawTextArgs) else RawTextArgs.model_validate(args)
    result = await service.add_manual(user_id=ctx.user_id, content=parsed.raw_text)
    data = {
        "tool": "memory_save",
        "status": result.status,
        "message": "我记住了。" if result.status == "succeeded" else "记忆保存失败。",
        "items": [_memory_item(item) for item in result.items],
        "error_message": result.error_message,
    }
    return ToolResult("memory_save", _tool_status(result.status), data["message"], data)


async def _memory_query(
    service: AgentMemoryService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("memory_query", "记忆查询工具需要数据库连接。")
    parsed = args if isinstance(args, MemoryQueryArgs) else MemoryQueryArgs.model_validate(args)
    if parsed.query:
        result = await service.search(user_id=ctx.user_id, query=parsed.query, limit=parsed.limit)
    else:
        result = await service.list(user_id=ctx.user_id, limit=parsed.limit)
    data = {
        "tool": "memory_query",
        "status": result.status,
        "count": len(result.items),
        "items": [_memory_item(item) for item in result.items],
        "error_message": result.error_message,
    }
    return ToolResult("memory_query", _tool_status(result.status), "记忆查询完成。", data)


async def _memory_delete(
    service: AgentMemoryService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("memory_delete", "记忆删除工具需要数据库连接。")
    parsed = args if isinstance(args, MemoryDeleteArgs) else MemoryDeleteArgs.model_validate(args)
    result = await service.delete(
        user_id=ctx.user_id,
        query=parsed.query,
        memory_id=parsed.memory_id,
    )
    data = {
        "tool": "memory_delete",
        "status": result.status,
        "message": result.message,
        "items": [_memory_item(item) for item in result.items],
        "error_message": result.error_message,
    }
    return ToolResult("memory_delete", _tool_status(result.status), result.message, data)


async def _briefing_preview(
    service: BriefingService | None,
    args: BaseModel,
    ctx: ToolContext,
) -> ToolResult:
    if service is None or ctx.user_id is None:
        return _missing_database("briefing_preview", "资讯工具需要数据库连接。")
    parsed = (
        args
        if isinstance(args, BriefingPreviewArgs)
        else BriefingPreviewArgs.model_validate(args)
    )
    result = await service.handle_from_text(
        user_id=ctx.user_id,
        text=parsed.raw_text,
        memory_topics=_briefing_topics(ctx.memories),
        timezone=ctx.timezone,
    )
    subscription = result.subscription
    data = {
        "tool": "briefing_preview",
        "status": result.status,
        "message": result.message,
        "preview_topics": result.preview_topics or [],
        "subscription": {
            "id": subscription.id,
            "subscription_type": subscription.subscription_type,
            "schedule_rule": subscription.schedule_rule,
            "next_push_at": (
                subscription.next_push_at.isoformat() if subscription.next_push_at else None
            ),
            "preferences": subscription.preferences,
        }
        if subscription
        else None,
    }
    return ToolResult("briefing_preview", _tool_status(result.status), result.message, data)


async def _news_tech_ai(args: BaseModel, ctx: ToolContext) -> ToolResult:
    parsed = args if isinstance(args, NewsArgs) else NewsArgs.model_validate(args)
    articles = await fetch_rss_articles(rss_urls=TECH_AI_RSS_URLS, limit=parsed.limit)
    data = _news_data("news_tech_ai", "科技 AI 资讯获取成功。", articles)
    status = "success" if articles else "not_found"
    content = "科技 AI 资讯获取成功。" if articles else "暂时没有获取到科技 AI 资讯。"
    return ToolResult("news_tech_ai", status, content, data)


async def _news_commodities(args: BaseModel, ctx: ToolContext) -> ToolResult:
    parsed = args if isinstance(args, NewsArgs) else NewsArgs.model_validate(args)
    articles = await fetch_rss_articles(rss_urls=COMMODITY_RSS_URLS, limit=parsed.limit)
    data = _news_data("news_commodities", "国际大宗商品资讯获取成功。", articles)
    status = "success" if articles else "not_found"
    content = "国际大宗商品资讯获取成功。" if articles else "暂时没有获取到国际大宗商品资讯。"
    return ToolResult("news_commodities", status, content, data)


def _market_result_data(tool_name: str, result) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "status": result.status,
        "message": result.message,
        "items": [
            {
                "symbol": item.symbol,
                "name": item.name,
                "market": item.market,
                "currency": item.currency,
                "price": str(item.price) if item.price is not None else None,
                "change": str(item.change) if item.change is not None else None,
                "change_percent": (
                    str(item.change_percent) if item.change_percent is not None else None
                ),
                "exchange_time": item.exchange_time,
            }
            for item in result.quotes
        ],
        "hotspots": [
            {
                "board_type": item.board_type,
                "code": item.code,
                "name": item.name,
                "price": str(item.price) if item.price is not None else None,
                "change_percent": (
                    str(item.change_percent) if item.change_percent is not None else None
                ),
                "main_net_inflow": (
                    str(item.main_net_inflow) if item.main_net_inflow is not None else None
                ),
            }
            for item in result.hotspots or []
        ],
    }


def _news_data(tool_name: str, message: str, articles) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "status": "success" if articles else "not_found",
        "message": message,
        "items": [
            {
                "title": item.title,
                "link": item.link,
                "source": item.source,
            }
            for item in articles
        ],
    }


def _todo_create_data(result) -> dict[str, Any]:
    reminder = result.reminder
    return {
        "tool": "todo_create",
        "status": result.status,
        "message": result.message,
        "needs_clarification": result.needs_clarification,
        "reminder_id": reminder.id if reminder else None,
        "title": reminder.title if reminder else None,
        "scheduled_at": (
            reminder.scheduled_at.isoformat() if reminder and reminder.scheduled_at else None
        ),
    }


def _todo_mutation_data(tool_name: str, result) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tool": tool_name,
        "status": result.status,
        "message": result.message,
        "needs_confirmation": result.needs_confirmation,
    }
    if result.reminder is not None:
        payload["reminder"] = {
            "id": result.reminder.id,
            "title": result.reminder.title,
            "status": result.reminder.status,
        }
    if result.candidates:
        payload["candidates"] = _todo_items(result.candidates)
    return payload


def _todo_items(items) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "title": item.title,
            "scheduled_at": item.scheduled_at.isoformat() if item.scheduled_at else None,
            "status": item.status,
        }
        for item in items
    ]


def _memo_item(item) -> dict[str, Any]:
    return {
        "id": item.id,
        "record_type": item.record_type,
        "content": item.content,
        "amount": str(item.amount) if item.amount is not None else None,
        "currency": item.currency,
        "recorded_at": item.recorded_at.isoformat(),
        "status": item.status,
    }


def _memory_item(item) -> dict[str, Any]:
    return {
        "memory_id": item.memory_id,
        "content": item.content,
        "score": item.score,
        "metadata": item.metadata,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _briefing_topics(memories: list[dict[str, Any]]) -> list[str] | None:
    known_topics = ["AI", "科技", "财经", "商业", "体育", "娱乐", "国际", "国内", "健康", "天气"]
    matched: list[str] = []
    for item in memories:
        content = str(item.get("content", ""))
        for topic in known_topics:
            if topic.lower() in content.lower() and topic not in matched:
                matched.append(topic)
    return matched or None


def _missing_database(tool_name: str, message: str) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        status="failed",
        content=message,
        data={"tool": tool_name, "status": "failed", "message": message},
        error_code="database_unavailable",
    )


def _tool_status(
    status: str,
) -> Literal["success", "needs_clarification", "not_found", "failed", "dry_run"]:
    if status in {
        "success",
        "created",
        "saved",
        "succeeded",
        "deleted",
        "completed",
        "subscribed",
        "preview",
    }:
        return "success"
    if status in {"needs_clarification", "needs_confirmation"}:
        return "needs_clarification"
    if status == "not_found":
        return "not_found"
    if status in {"dry_run", "skipped"}:
        return "dry_run"
    return "failed"
