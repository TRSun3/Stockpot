"""What the app serves before anyone logs in: a health check and the frontend."""

from fastapi.testclient import TestClient

from stockpot.main import app


def test_the_health_check_answers_ok():
    assert TestClient(app).get("/api/health").json() == {"ok": True}


def test_the_root_serves_the_frontend_page():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "<title>Stockpot</title>" in response.text
