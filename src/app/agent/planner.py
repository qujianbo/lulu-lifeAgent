import json
from typing import Any

from pydantic import ValidationError

from app.agent.schemas import PlannerDecision, PlannerSchemaError, parse_planner_decision
from app.agent.tools.base import ToolArgumentError
from app.agent.tools.registry import ToolRegistry, UnknownToolError
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage

PLANNER_SYSTEM_PROMPT = """你是生活管家 Agent 的工具规划器。
你只负责理解用户目标并选择工具，不直接回答用户。

你必须只输出 JSON，不要 Markdown，不要解释。

可选 action：
- call_tool：需要调用工具。
- final_answer：普通问答，不需要工具。
- ask_clarification：确实缺少必要信息，需要追问。

决策规则：
- 实时行情、市场、大盘、股票、指数、板块问题，必须调用市场工具。
- “今天市场怎么样”“今天市场行情如何”“大盘怎么样”默认调用 market_overview，market 默认 A股。
- “查一下贵州茅台”“上证指数多少”“AAPL 现在多少钱”调用 market_quote。
- “热门板块”“热点概念”“强势行业”调用 market_hotspots。
- 待办、提醒、完成、删除待办调用 todo 工具。
- 记账、体重、运动、睡眠、喝水、备忘调用 memo 工具。
- 记住、偏好、个人信息、长期习惯调用 memory 工具。
- 科技、AI、人工智能、模型、芯片、机器人相关新闻调用 news_tech_ai。
- 国际大宗商品、原油、黄金、铜、矿业、能源相关新闻调用 news_commodities。
- 早报、简报、订阅资讯偏好调用 briefing_preview。
- 不要因为用户没有说工具名就追问；能默认就默认。
- 确实缺少必要信息时才 ask_clarification。
- 只能选择工具清单中存在的工具。

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
