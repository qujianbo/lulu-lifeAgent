import json
from typing import Any

from pydantic import ValidationError

from app.agent.schemas import PlannerDecision, PlannerSchemaError, parse_planner_decision
from app.agent.tools.base import ToolArgumentError
from app.agent.tools.registry import ToolRegistry, UnknownToolError
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage

PLANNER_SYSTEM_PROMPT = """你是生活管家 Agent 的工具规划器。
你的职责是判断用户目标、选择最合适的工具，并生成结构化调用参数；你不直接回答用户。

你必须只输出 JSON，不要 Markdown，不要解释。

可选 action：
- call_tool：需要调用工具。
- final_answer：不需要工具即可可靠回答。
- ask_clarification：缺少关键参数，无法安全默认时才追问。

通用决策原则：
1. 优先理解用户意图，不要做机械关键词匹配。
2. 用户给出自然语言标的时，自动分析标的并调用工具；不要要求用户补证券代码、商品代码或工具名。
3. 对时间敏感、价格、行情、新闻、政策、产品、人物机构、最新事实等问题，
   必须调用工具或 web_search，不要凭模型记忆回答。
4. 专用工具优先于 web_search；专用工具覆盖不了时，再使用 web_search 兜底。
5. 能合理默认时直接默认；只有缺少关键参数且无法安全默认时才 ask_clarification。
6. 只能选择工具清单中存在的工具。
7. arguments 必须严格符合对应工具 schema。

工具选择规则：
- 市场整体、大盘、A股行情、今天市场怎么样：调用 market_overview，market 默认 A股。
- 个股、指数、ETF 基础行情：调用 market_quote；例如“贵州茅台”“上证指数”“AAPL”。
- 热门板块、热点概念、强势行业：调用 market_hotspots。
- 黄金、金价、白银、原油、油价、铜价等商品价格：调用 commodity_quote，并保留用户原始单位/币种口径。
- 待办、提醒、完成、删除待办：调用对应 todo 工具。
- 记账、体重、运动、睡眠、喝水、备忘：调用 memo 工具。
- 长期偏好、个人信息、长期习惯、要求你记住或忘掉的信息：调用 memory 工具。
- 科技、AI、人工智能、模型、芯片、机器人相关新闻：调用 news_tech_ai。
- 国际大宗商品、原油、黄金、铜、矿业、能源相关新闻：调用 news_commodities。
- 早报、简报、订阅资讯偏好：调用 briefing_preview。
- 其他需要外部资料的问题，包括最新资料、百科事实、人物机构、产品服务、
  政策规则、教程对比：调用 web_search。

JSON schema：
{
  "action": "call_tool",
  "tool_name": "market_overview",
  "arguments": {},
  "domain": "market",
  "confidence": 0.0,
  "reason": "一句简短中文理由",
  "question": null
}
"""


class PlannerError(RuntimeError):
    pass


class ToolCallingPlanner:
    def __init__(
        self,
        llm: DeepSeekProvider,
        registry: ToolRegistry,
        *,
        max_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.max_attempts = max_attempts

    async def plan(
        self,
        *,
        message: str,
        context: dict[str, Any],
        previous_error: str | None = None,
    ) -> PlannerDecision:
        last_error: Exception | None = None
        for _attempt in range(self.max_attempts):
            prompt = self._build_prompt(
                message=message,
                context=context,
                previous_error=previous_error or (str(last_error) if last_error else None),
            )
            try:
                response = await self.llm.chat(
                    [
                        LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                        LLMMessage(role="user", content=prompt),
                    ],
                    temperature=0,
                    max_tokens=600,
                )
                decision = parse_planner_decision(response.content)
                self._validate_decision(decision)
                return decision
            except Exception as exc:
                # Retry model, JSON, Pydantic and tool-schema failures.
                last_error = exc
        raise PlannerError("planner failed after retries") from last_error

    def _validate_decision(self, decision: PlannerDecision) -> None:
        if decision.action != "call_tool":
            return
        if not decision.tool_name:
            raise PlannerSchemaError("tool_name is required")
        try:
            tool = self.registry.get(decision.tool_name)
            tool.validate_arguments(decision.arguments)
        except (UnknownToolError, ToolArgumentError, ValidationError) as exc:
            raise PlannerSchemaError(str(exc)) from exc

    def _build_prompt(
        self,
        *,
        message: str,
        context: dict[str, Any],
        previous_error: str | None,
    ) -> str:
        payload = {
            "user_message": message,
            "memories": context.get("memories") or [],
            "tools": self.registry.descriptions_for_prompt(),
            "previous_error": previous_error,
        }
        return json.dumps(payload, ensure_ascii=False)
