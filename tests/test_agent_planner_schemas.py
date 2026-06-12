import json

import pytest
from pydantic import ValidationError

from app.agent.planner import PlannerError, ToolCallingPlanner
from app.agent.schemas import PlannerSchemaError, parse_planner_decision
from app.agent.tools.builtin import MarketQuoteArgs, build_tool_registry
from app.services.llm.types import LLMResponse


def test_parse_planner_decision_validates_action_fields() -> None:
    with pytest.raises(PlannerSchemaError):
        parse_planner_decision(
            json.dumps(
                {
                    "action": "call_tool",
                    "tool_name": None,
                    "arguments": {},
                    "domain": "market",
                    "confidence": 0.8,
                    "reason": "缺少工具名",
                }
            )
        )


def test_parse_planner_decision_rejects_invalid_confidence() -> None:
    with pytest.raises(PlannerSchemaError):
        parse_planner_decision(
            json.dumps(
                {
                    "action": "final_answer",
                    "tool_name": None,
                    "arguments": {},
                    "domain": "general",
                    "confidence": 1.5,
                    "reason": "置信度非法",
                }
            )
        )


def test_tool_args_model_validates_arguments() -> None:
    with pytest.raises(ValidationError):
        MarketQuoteArgs.model_validate({"query": "", "market": "auto"})


def test_tool_registry_contains_news_tools() -> None:
    registry = build_tool_registry()

    assert registry.has("news_tech_ai")
    assert registry.has("news_commodities")
    assert registry.has("commodity_quote")
    assert registry.has("web_search")


async def test_planner_rejects_unknown_tool_name() -> None:
    registry = build_tool_registry()
    planner = ToolCallingPlanner(FakePlannerLLM("not_a_tool"), registry, max_attempts=1)

    with pytest.raises(PlannerError):
        await planner.plan(message="今天市场行情如何", context={})


class FakePlannerLLM:
    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    async def chat(self, messages, *args, **kwargs) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(
                {
                    "action": "call_tool",
                    "tool_name": self.tool_name,
                    "arguments": {},
                    "domain": "market",
                    "confidence": 0.9,
                    "reason": "测试未知工具",
                },
                ensure_ascii=False,
            ),
            model="fake",
            provider="fake",
            latency_ms=1,
            finish_reason="stop",
        )
