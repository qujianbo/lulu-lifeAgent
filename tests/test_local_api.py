from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMResponse


async def _fake_chat(*args, **kwargs) -> LLMResponse:
    return LLMResponse(
        content="后端正常",
        model="deepseek-test",
        provider="deepseek",
        latency_ms=12,
        finish_reason="stop",
    )


def _settings_without_admin_token() -> Settings:
    return Settings(deepseek_api_key="test-key", deepseek_model="deepseek-test")


def _settings_with_admin_token() -> Settings:
    return Settings(
        deepseek_api_key="test-key",
        deepseek_model="deepseek-test",
        admin_token="secret",
    )


def test_deepseek_ping(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekProvider, "chat", _fake_chat)
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/deepseek/ping")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["content"] == "后端正常"


def test_local_chat_returns_agent_response(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekProvider, "chat", _fake_chat)
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.post("/api/local/chat", json={"message": "明早提醒我带身份证"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "后端正常"
    assert payload["intent"] == "create_reminder_candidate"


def test_local_api_requires_admin_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekProvider, "chat", _fake_chat)
    app.dependency_overrides[get_settings] = _settings_with_admin_token
    client = TestClient(app)

    missing = client.get("/api/local/deepseek/ping")
    ok = client.get("/api/local/deepseek/ping", headers={"x-admin-token": "secret"})
    app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 200
