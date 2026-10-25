"""What the app serves before anyone logs in: a health check, the frontend, and errors as JSON."""


def test_the_health_check_answers_ok(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_the_root_serves_the_frontend_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Stockpot</title>" in response.text


def test_errors_come_back_as_json_with_a_message(client):
    response = client.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.json() == {"error": "Not Found"}


def test_an_unexpected_failure_still_answers_with_json(app):
    from fastapi.testclient import TestClient

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("kaboom")

    app.router.routes.insert(0, app.router.routes.pop())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/boom")
    assert response.status_code == 500
    assert "kaboom" not in response.text
    assert response.json()["error"]


def test_an_oversized_request_is_refused_before_it_is_read(client):
    response = client.post("/api/auth/login", content=b"x" * (300 * 1024), headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert response.json() == {"error": "That request is too large."}
