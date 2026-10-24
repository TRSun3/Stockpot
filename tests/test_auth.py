"""Accounts: signing up, logging in and out, and keeping everyone else out."""

import sqlite3
from contextlib import closing

import pytest


def log_in(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password}).status_code


def test_signing_up_logs_the_new_account_in(client):
    response = client.post("/api/auth/signup", json={"username": "neal", "password": "password1"})
    assert response.status_code == 201
    cookie = response.headers["set-cookie"].lower()
    assert "stockpot_session=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/me").json() == {"username": "neal", "llm": "mock"}


def test_a_username_is_taken_regardless_of_case(client, neal):
    response = client.post("/api/auth/signup", json={"username": "NEAL", "password": "password2"})
    assert response.status_code == 409
    assert response.json() == {"error": "That username is taken."}


@pytest.mark.parametrize(
    "username, password",
    [
        ("", "password1"),
        ("ab", "password1"),
        ("x" * 33, "password1"),
        ("a space", "password1"),
        ("neal", "short"),
    ],
)
def test_signing_up_refuses_unreasonable_usernames_and_passwords(client, username, password):
    response = client.post("/api/auth/signup", json={"username": username, "password": password})
    assert response.status_code == 422
    assert response.json()["error"]


def test_logging_in_needs_the_right_password(client, neal):
    assert log_in(client, "neal", "wrong-one") == 401
    assert log_in(client, "nobody", "password1") == 401
    assert log_in(client, "Neal", "password1") == 200
    assert client.get("/api/me").json()["username"] == "neal"


def test_logging_out_ends_the_session_even_for_a_copied_cookie(neal):
    token = neal.cookies["stockpot_session"]
    assert neal.post("/api/auth/logout").status_code == 200
    assert neal.get("/api/me").status_code == 401
    neal.cookies.set("stockpot_session", token)
    assert neal.get("/api/me").status_code == 401


def test_protected_routes_answer_401_without_a_session(client):
    for method, path in [
        ("get", "/api/me"),
        ("get", "/api/items"),
        ("post", "/api/items"),
        ("get", "/api/items/expiring"),
        ("patch", "/api/items/1"),
        ("delete", "/api/items/1"),
        ("get", "/api/shopping"),
        ("post", "/api/shopping"),
    ]:
        response = client.request(method, path)
        assert response.status_code == 401, path
        assert response.json() == {"error": "Please log in."}


def test_two_accounts_stay_logged_in_side_by_side(neal, tianyue):
    assert neal.get("/api/me").json()["username"] == "neal"
    assert tianyue.get("/api/me").json()["username"] == "tianyue"


def test_passwords_are_stored_salted_and_hashed(neal, tianyue, settings):
    with closing(sqlite3.connect(settings.db_path)) as conn:
        rows = conn.execute("SELECT password_hash, salt FROM users").fetchall()
    assert all("password1" not in value for row in rows for value in row)
    assert rows[0] != rows[1]
