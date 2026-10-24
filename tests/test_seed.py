"""The seed creates two demo kitchens that tell a story, and running it again resets them cleanly."""

from contextlib import closing

from conftest import TODAY

from stockpot import db, seed


def log_in(client, username):
    return client.post("/api/auth/login", json={"username": username, "password": seed.PASSWORD})


def run_seed(settings):
    db.init(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn:
        seed.seed(conn, TODAY)


def test_each_demo_account_gets_a_realistic_kitchen_with_something_to_use_soon(client, settings):
    run_seed(settings)
    for username in seed.KITCHENS:
        assert log_in(client, username).status_code == 200
        items = client.get("/api/items").json()
        statuses = [item["status"] for item in items]
        assert 12 <= len(items) <= 18
        assert statuses.count("expired") in (1, 2)
        assert sum(status in ("today", "soon") for status in statuses) >= 3
        assert client.get("/api/shopping").json()


def test_the_two_demo_kitchens_are_different(client, settings):
    run_seed(settings)
    kitchens = []
    for username in seed.KITCHENS:
        log_in(client, username)
        kitchens.append({item["name"] for item in client.get("/api/items").json()})
    assert kitchens[0] != kitchens[1]


def test_seeding_again_resets_the_demo_accounts_and_leaves_others_alone(client, settings, make_user):
    run_seed(settings)
    log_in(client, "neal")
    client.post("/api/items", json={"name": "Leftover pizza"})
    other = make_user("someone")
    other.post("/api/items", json={"name": "Their own milk"})
    run_seed(settings)
    log_in(client, "neal")
    assert "Leftover pizza" not in {item["name"] for item in client.get("/api/items").json()}
    assert log_in(other, "someone").status_code == 401
    other.post("/api/auth/login", json={"username": "someone", "password": "password1"})
    assert [item["name"] for item in other.get("/api/items").json()] == ["Their own milk"]
