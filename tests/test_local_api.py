import json

from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.beta_auth import _cookie_secure
from app.api.local import _is_confirmation_message
from app.config import Settings, get_settings
from app.main import app
from app.services.llm.deepseek import DeepSeekProvider
from app.services.llm.types import LLMResponse


async def _fake_chat(self, messages, *args, **kwargs) -> LLMResponse:
    if "工具规划器" in messages[0].content:
        payload = json.loads(messages[-1].content)
        user_message = payload["user_message"]
        decision = {
            "action": "final_answer",
            "tool_name": None,
            "arguments": {},
            "domain": "general_qa",
            "confidence": 0.99,
            "reason": "测试规划",
            "question": None,
        }
        if "提醒" in user_message or "待办" in user_message:
            decision.update(
                action="call_tool",
                tool_name="todo_create",
                arguments={"raw_text": user_message},
                domain="todo",
            )
        return LLMResponse(
            content=json.dumps(decision, ensure_ascii=False),
            model="deepseek-test",
            provider="deepseek",
            latency_ms=12,
            finish_reason="stop",
        )
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

    response = client.post("/api/local/chat", json={"message": "明早待办：带身份证"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "后端正常"
    assert payload["intent"] == "todo_create"
    assert payload["planner"]["tool_name"] == "todo_create"
    assert payload["tool_result"]["tool"] == "todo_create"
    assert payload["tool_result"]["status"] == "failed"
    assert payload["tool_trace"][0]["tool_name"] == "todo_create"


def test_local_api_requires_admin_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(DeepSeekProvider, "chat", _fake_chat)
    app.dependency_overrides[get_settings] = _settings_with_admin_token
    client = TestClient(app)

    missing = client.get("/api/local/deepseek/ping")
    ok = client.get("/api/local/deepseek/ping", headers={"x-admin-token": "secret"})
    app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 200


def test_beta_login_requires_database() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    response = client.post(
        "/api/auth/login",
        json={"username": "tester", "password": "password123"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 503


def test_admin_beta_users_requires_admin_token() -> None:
    app.dependency_overrides[get_settings] = _settings_with_admin_token
    client = TestClient(app)

    missing = client.get("/api/admin/beta-users")
    ok = client.get("/api/admin/beta-users", headers={"x-admin-token": "secret"})
    app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 503


def test_admin_beta_feedback_requires_admin_token() -> None:
    app.dependency_overrides[get_settings] = _settings_with_admin_token
    client = TestClient(app)

    missing = client.get("/api/admin/beta-feedback")
    ok = client.get("/api/admin/beta-feedback", headers={"x-admin-token": "secret"})
    app.dependency_overrides.clear()

    assert missing.status_code == 401
    assert ok.status_code == 503


def test_beta_cookie_secure_follows_request_scheme() -> None:
    settings = Settings(public_base_url="https://luluservice.cn", _env_file=None)
    http_request = _request("http", "luluservice.cn", 8000)
    https_request = _request("https", "luluservice.cn", 443)
    forwarded_request = _request(
        "http",
        "127.0.0.1",
        8000,
        headers=[(b"x-forwarded-proto", b"https")],
    )

    assert not _cookie_secure(settings, http_request)
    assert _cookie_secure(settings, https_request)
    assert _cookie_secure(settings, forwarded_request)


def _request(
    scheme: str,
    host: str,
    port: int,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": scheme,
            "server": (host, port),
            "path": "/",
            "query_string": b"",
            "headers": headers or [],
        }
    )


def test_beta_pages_are_served() -> None:
    client = TestClient(app)

    login = client.get("/login")
    chat = client.get("/chat")
    admin = client.get("/admin/beta-users")

    assert login.status_code == 200
    assert "生活管家 Agent" in login.text
    assert chat.status_code == 200
    assert "/api/beta/chat" in chat.text
    assert admin.status_code == 200
    assert "内测用户管理" in admin.text


def test_beta_user_apis_require_database_before_auth() -> None:
    app.dependency_overrides[get_settings] = _settings_without_admin_token
    client = TestClient(app)

    chat = client.post("/api/beta/chat", json={"message": "你好"})
    feedback = client.post("/api/beta/feedback", json={"content": "不好用"})
    app.dependency_overrides.clear()

    assert chat.status_code == 503
    assert feedback.status_code == 503


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


def test_confirmation_message_detection() -> None:
    assert _is_confirmation_message("确认")
    assert _is_confirmation_message("好的")
    assert not _is_confirmation_message("确认查上证指数")
