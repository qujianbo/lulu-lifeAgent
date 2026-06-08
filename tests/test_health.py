from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_allows_unconfigured_external_services() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=None,
        redis_url=None,
        deepseek_api_key=None,
        wechat_app_id=None,
        wechat_token=None,
    )
    client = TestClient(app)
    response = client.get("/readyz")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert "database" in payload["checks"]
    assert "redis" in payload["checks"]
