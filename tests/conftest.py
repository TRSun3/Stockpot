"""Each test gets its own database file, a frozen today, and logged-in clients on demand."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from stockpot import config
from stockpot.llm.mock import Mock
from stockpot.main import create_app

TODAY = date(2026, 10, 24)


def pytest_addoption(parser):
    parser.addoption("--browser", action="store_true", help="also drive the running app in Chrome")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--browser"):
        return
    skip = pytest.mark.skip(reason="drives a real browser; runs only with --browser")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def settings(tmp_path):
    return config.Settings(
        db_path=tmp_path / "stockpot.db", llm="mock", gemini_api_key="", gemini_model="gemini-3.5-flash-lite"
    )


@pytest.fixture
def app(settings):
    app = create_app(settings, llm=Mock(delay=0))
    app.state.today = lambda: TODAY
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def make_user(app):
    """Signs up a new account and returns a client holding its session, like its own browser window."""
    clients = []

    def make(username: str, password: str = "password1") -> TestClient:
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        response = client.post("/api/auth/signup", json={"username": username, "password": password})
        assert response.status_code == 201, response.text
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def neal(make_user):
    return make_user("neal")


@pytest.fixture
def tianyue(make_user):
    return make_user("tianyue")
