from fastapi.testclient import TestClient

from app.main import app


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readyz_allows_unconfigured_external_services() -> None:
    client = TestClient(app)
    response = client.get("/readyz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ready"] is True
    assert "database" in payload["checks"]
    assert "redis" in payload["checks"]

