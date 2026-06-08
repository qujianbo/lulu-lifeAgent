import time

import httpx

from app.config import Settings
from app.services.llm.types import LLMMessage, LLMResponse


class DeepSeekProviderError(RuntimeError):
    pass


class DeepSeekProvider:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model or "deepseek-chat"
        self.timeout = settings.llm_timeout_seconds

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
        latency_ms = round((time.perf_counter() - start) * 1000)
        if not response.is_success:
            raise DeepSeekProviderError(
                f"DeepSeek request failed with status {response.status_code}"
            )

        data = response.json()
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise DeepSeekProviderError("DeepSeek response format is invalid") from exc

        return LLMResponse(
            content=str(content or ""),
            model=str(data.get("model") or self.model),
            provider="deepseek",
            latency_ms=latency_ms,
            finish_reason=choice.get("finish_reason"),
        )
