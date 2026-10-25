"""The database creates itself on first start and keeps its data on every start after."""

import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from stockpot import db
from stockpot.main import create_app


def test_starting_without_a_database_file_creates_it_with_every_table(settings):
    assert not settings.db_path.exists()
    with TestClient(create_app(settings)):
        pass
    with closing(sqlite3.connect(settings.db_path)) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert {"users", "sessions", "items", "shopping_items", "chat_messages"} <= tables


def test_starting_again_on_an_existing_database_keeps_its_data(settings):
    account = {"username": "neal", "password": "password1"}
    with TestClient(create_app(settings)) as client:
        client.post("/api/auth/signup", json=account)
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/auth/login", json=account).is_success


def test_the_database_runs_in_wal_mode_with_foreign_keys_enforced(settings):
    db.init(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO items (user_id, name) VALUES (999, 'Milk')")


def test_a_failed_transaction_leaves_nothing_behind(settings):
    db.init(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn:
        with pytest.raises(RuntimeError), db.transaction(conn):
            conn.execute("INSERT INTO users (username, password_hash, salt) VALUES ('a', 'h', 's')")
            raise RuntimeError
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0


def test_the_pool_reuses_connections_and_never_hands_one_out_mid_transaction(settings):
    db.init(settings.db_path)
    pool = db.Pool(settings.db_path, size=1)
    with pool.connection() as first:
        first.execute("BEGIN")
        first.execute("INSERT INTO users (username, password_hash, salt) VALUES ('a', 'h', 's')")
    with pool.connection() as again:
        assert again is first
        assert not again.in_transaction
        assert again.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    pool.close()
