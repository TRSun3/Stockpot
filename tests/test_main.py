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
