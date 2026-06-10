import json
from dataclasses import dataclass
from typing import Any

from app.agent.state import AgentIntent
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage

ALLOWED_INTENTS: set[str] = {
    "general_qa",
    "create_reminder",
    "query_reminder",
    "complete_reminder",
    "delete_reminder",
    "briefing",
    "create_life_record",
    "query_life_record",
    "memory_update",
    "memory_query",
    "memory_delete",
    "unknown",
}

INTENT_CLASSIFIER_PROMPT = """你是生活管家 Agent 的意图路由器。
你只负责判断用户意图和提取少量槽位，不回答用户问题。

允许的 intent：
- general_qa：普通问答、建议、闲聊、无法归入工具的生活问题
- create_reminder：创建提醒或待办
- query_reminder：查询提醒或待办
- complete_reminder：完成提醒或待办
- delete_reminder：删除、取消提醒或待办
- briefing：资讯、新闻、天气、早报、简报预览或订阅
- create_life_record：记账、收入、体重、运动、睡眠、喝水、普通生活记录
- query_life_record：查询、统计生活记录或消费记录
- memory_update：要求你记住偏好、个人信息、长期习惯
- memory_query：查询你记住了什么、用户偏好是什么
- memory_delete：删除、忘掉记忆或偏好
- unknown：空输入或完全无法判断

必须只输出 JSON，不要 Markdown，不要解释。
JSON schema：
{
  "intent": "create_reminder",
  "confidence": 0.0,
  "reason": "一句简短中文理由",
  "slots": {
    "time_text": null,
    "title": null,
    "record_type": null,
    "topics": [],
    "memory_key": null,
    "memory_value": null
  }
}
"""


class IntentClassificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class IntentClassificationResult:
    intent: AgentIntent
    confidence: float
    reason: str | None
    slots: dict[str, Any]


class LLMIntentClassifier:
    def __init__(self, llm: DeepSeekProvider, *, max_attempts: int = 3) -> None:
        self.llm = llm
        self.max_attempts = max_attempts

    async def classify(self, message: str) -> IntentClassificationResult:
        last_error: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                response = await self.llm.chat(
                    [
                        LLMMessage(role="system", content=INTENT_CLASSIFIER_PROMPT),
                        LLMMessage(role="user", content=f"用户消息：{message}"),
                    ],
                    temperature=0,
                    max_tokens=300,
                )
                return parse_intent_response(response.content)
            except Exception as exc:
                # Retry model or structure failures; final failure is surfaced to the API.
                last_error = exc
        raise IntentClassificationError(
            "intent classification failed after retries"
        ) from last_error


def parse_intent_response(content: str) -> IntentClassificationResult:
    payload = json.loads(_strip_json_fence(content))
    intent = payload.get("intent")
    if intent not in ALLOWED_INTENTS:
        raise IntentClassificationError(f"invalid intent: {intent}")
    confidence = float(payload.get("confidence", 0))
    slots = payload.get("slots") or {}
    if not isinstance(slots, dict):
        raise IntentClassificationError("slots must be an object")
    return IntentClassificationResult(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        reason=payload.get("reason"),
        slots=slots,
    )


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        text = text.removesuffix("```").strip()
    return text
