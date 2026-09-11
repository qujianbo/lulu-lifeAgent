from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.main import app
from app.services.reminders.service import _extract_ordinal, _same_day_reschedule_time


def test_home_page_is_served() -> None:
    response = TestClient(app).get("/home")

    assert response.status_code == 200
    assert "今日待办" in response.text
    assert "/api/beta/home" in response.text
    assert "北京时间" in response.text


def test_prometheus_metrics_are_exposed() -> None:
    response = TestClient(app).get("/metrics")

    assert response.status_code == 200
    assert "life_agent_http_requests_total" in response.text
    assert "life_agent_llm_tokens_total" in response.text


def test_reminders_page_is_served() -> None:
    response = TestClient(app).get("/reminders")

    assert response.status_code == 200
    assert "提醒管理" in response.text
    assert "/api/beta/reminders" in response.text


def test_p0_apis_require_login() -> None:
    client = TestClient(app)

    for path in (
        "/api/beta/home",
        "/api/beta/reminders",
        "/api/beta/conversations",
        "/api/beta/notification-settings",
        "/api/beta/notifications",
    ):
        assert client.get(path).status_code in {401, 503}


def test_extract_chinese_and_numeric_ordinals() -> None:
    assert _extract_ordinal("完成第二条") == 2
    assert _extract_ordinal("删除第 3 条") == 3
    assert _extract_ordinal("完成那条") is None


def test_reschedule_time_uses_existing_day_in_shanghai() -> None:
    timezone = ZoneInfo("Asia/Shanghai")
    current = datetime.now(timezone) + timedelta(days=1)
    current = current.replace(hour=8, minute=0, second=0, microsecond=0)

    result = _same_day_reschedule_time(text="改到上午 9 点", current=current)

    assert result == current.replace(hour=9)
    assert result.tzinfo == timezone
