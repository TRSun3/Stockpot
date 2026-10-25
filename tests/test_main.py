"""What the app serves around the API routes: a health check, the frontend, compression, and errors as JSON."""

import re

from stockpot.main import STATIC


def test_the_health_check_answers_ok(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_the_root_serves_the_frontend_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "<title>Stockpot</title>" in response.text


def test_the_page_preloads_every_script_module_it_will_import(client):
    preloaded = set(re.findall(r'rel="modulepreload" href="/js/([\w.]+)"', client.get("/").text))
    assert preloaded == {path.name for path in (STATIC / "js").glob("*.js")} - {"app.js"}


def test_the_browser_rechecks_every_file_and_gets_a_304_when_it_is_unchanged(client):
    first = client.get("/js/chat.js")
    assert first.headers["cache-control"] == "no-cache"
    again = client.get("/js/chat.js", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304


def test_large_responses_are_gzipped_but_the_chat_stream_is_not(neal):
    assert neal.get("/css/base.css").headers["content-encoding"] == "gzip"
    with neal.stream("POST", "/api/chat", json={"message": "something cozy"}) as reply:
        assert "content-encoding" not in reply.headers
        assert '"type": "done"' in reply.read().decode()


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
    chunked = client.post("/api/auth/login", content=iter([b"{}"]), headers={"content-type": "application/json"})
    assert chunked.status_code == 411
