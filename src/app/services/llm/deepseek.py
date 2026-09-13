import time

import httpx

from app.config import Settings
from app.services.llm.around import around_llm_call
from app.services.llm.types import LLMMessage, LLMResponse


class DeepSeekProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class DeepSeekProvider:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model or "deepseek-chat"
        self.timeout = settings.llm_timeout_seconds
        self.provider_name = "deepseek"
        self.max_attempts = settings.llm_max_attempts
        self.retry_base_seconds = settings.llm_retry_base_seconds
        self.retry_max_seconds = settings.llm_retry_max_seconds
        self.input_cost_per_million_usd = settings.deepseek_input_cost_per_million_usd
        self.output_cost_per_million_usd = settings.deepseek_output_cost_per_million_usd

    @around_llm_call
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        # Keep provider code isolated so later model fallback can be added cleanly.
        if not self.api_key:
            raise DeepSeekProviderError("DeepSeek API key is not configured")
        start = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        latency_ms = round((time.perf_counter() - start) * 1000)
        if not response.is_success:
            raise DeepSeekProviderError(
                f"DeepSeek request failed with status {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code in {408, 409, 429}
                or response.status_code >= 500,
            )

        data = response.json()
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekProviderError("DeepSeek response format is invalid") from exc

        usage = data.get("usage") or {}
        input_tokens = _non_negative_int(usage.get("prompt_tokens"))
        output_tokens = _non_negative_int(usage.get("completion_tokens"))
        total_tokens = _non_negative_int(usage.get("total_tokens"))
        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        estimated_cost_usd = (
            input_tokens * self.input_cost_per_million_usd
            + output_tokens * self.output_cost_per_million_usd
        ) / 1_000_000

        return LLMResponse(
            content=str(content or ""),
            model=str(data.get("model") or self.model),
            provider="deepseek",
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost_usd,
        )


def _non_negative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
