import pytest

from app.agent.intent_classifier import (
    IntentClassificationError,
    LLMIntentClassifier,
    parse_intent_response,
)
from app.services.llm.types import LLMResponse


class RetryLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(
                content="不是 JSON",
                model="fake-model",
                provider="fake",
                latency_ms=1,
                finish_reason="stop",
            )
        return LLMResponse(
            content='{"intent":"briefing","confidence":0.8,"reason":"用户要资讯","slots":{}}',
            model="fake-model",
            provider="fake",
            latency_ms=1,
            finish_reason="stop",
        )


class BrokenLLM:
    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(
            content='{"intent":"bad_intent","confidence":0.8,"reason":"测试","slots":{}}',
            model="fake-model",
            provider="fake",
            latency_ms=1,
            finish_reason="stop",
        )


def test_parse_intent_response_accepts_json_fence() -> None:
    result = parse_intent_response(
        '```json\n{"intent":"general_qa","confidence":1,"reason":"普通问题","slots":{}}\n```'
    )

    assert result.intent == "general_qa"
    assert result.confidence == 1


async def test_classifier_retries_invalid_model_output() -> None:
    llm = RetryLLM()
    classifier = LLMIntentClassifier(llm, max_attempts=2)

    result = await classifier.classify("今天有什么科技新闻")

    assert llm.calls == 2
    assert result.intent == "briefing"


async def test_classifier_raises_after_retry_exhausted() -> None:
    classifier = LLMIntentClassifier(BrokenLLM(), max_attempts=2)

    with pytest.raises(IntentClassificationError):
        await classifier.classify("测试")
