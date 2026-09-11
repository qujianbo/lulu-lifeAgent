import httpx

import app.services.llm.deepseek as deepseek_module
from app.config import Settings
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMMessage


async def test_deepseek_provider_parses_token_usage(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-test",
                "choices": [
                    {"message": {"content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            },
        )

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=transport)

    monkeypatch.setattr(deepseek_module.httpx, "AsyncClient", MockAsyncClient)
    provider = DeepSeekProvider(
        Settings(
            deepseek_api_key="test-key",
            deepseek_model="deepseek-test",
            deepseek_input_cost_per_million_usd=1,
            deepseek_output_cost_per_million_usd=2,
            _env_file=None,
        )
    )

    response = await provider.chat([LLMMessage(role="user", content="hello")])

    assert response.input_tokens == 120
    assert response.output_tokens == 30
    assert response.total_tokens == 150
    assert response.metrics()["llm_calls"] == 1
    assert response.estimated_cost_usd == 0.00018


async def test_deepseek_provider_retries_retryable_status(monkeypatch) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 3},
            },
        )

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(transport=transport)

    monkeypatch.setattr(deepseek_module.httpx, "AsyncClient", MockAsyncClient)
    provider = DeepSeekProvider(
        Settings(
            deepseek_api_key="test-key",
            llm_max_attempts=2,
            llm_retry_base_seconds=0,
            llm_retry_max_seconds=0,
            _env_file=None,
        )
    )

    response = await provider.chat([LLMMessage(role="user", content="hello")])

    assert response.content == "ok"
    assert calls == 2
