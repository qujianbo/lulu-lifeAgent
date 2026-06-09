from fastapi.testclient import TestClient

from app.main import app


def test_debug_chat_page() -> None:
    client = TestClient(app)

    response = client.get("/debug/chat")

    assert response.status_code == 200
    assert "生活管家 Agent" in response.text
    assert "/api/local/chat" in response.text
