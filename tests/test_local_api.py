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
    return Settings(
        deepseek_api_key="test-key",
        deepseek_model="deepseek-test",
        database_url=None,
        redis_url=None,
        _env_file=None,
    )


def _settings_with_admin_token() -> Settings:
    return Settings(
        deepseek_api_key="test-key",
        deepseek_model="deepseek-test",
        admin_token="secret",
        database_url=None,
        redis_url=None,
        _env_file=None,
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
    assert payload["intent"] == "create_reminder"
    assert payload["tool_result"]["tool"] == "create_reminder"
    assert payload["tool_result"]["status"] == "dry_run"


def test_local_api_requires_admin_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekProvider, "chat", _fake_chat)
    app.dependency_overrides[get_settings] = _settings_with_admin_token
    client = TestClient(app)

    missing = client.get("/api/local/deepseek/ping")
    ok = client.get("/api/local/deepseek/ping", headers={"x-admin-token": "secret"})
    app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 200


def test_local_scheduler_run_once_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.post("/api/local/scheduler/run-once")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "database_unavailable"


def test_local_scheduled_jobs_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/scheduled-jobs")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_local_memories_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/memories")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_local_life_records_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/life-records")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_local_subscriptions_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/subscriptions")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_local_message_logs_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/message-logs")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_local_stats_handles_missing_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/stats")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["users"] == 0


def test_local_briefing_preview_handles_missing_sources() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.get("/api/local/briefing/preview")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["status"] == "no_sources"
