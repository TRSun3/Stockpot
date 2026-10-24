"""The pantry: adding, editing, and discarding items, how fresh each one is, and whose they are."""

from datetime import timedelta

import pytest
from conftest import TODAY


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def add(client, name, expires_on=None, description=""):
    response = client.post(
        "/api/items", json={"name": name, "description": description, "expires_on": expires_on}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_an_added_item_keeps_its_name_description_and_expiry(neal):
    item = add(neal, "Milk", day(5), "about half a gallon of 2%")
    assert {k: item[k] for k in ("name", "description", "expires_on")} == {
        "name": "Milk",
        "description": "about half a gallon of 2%",
        "expires_on": day(5),
    }
    assert neal.get(f"/api/items/{item['id']}").json() == item


def test_the_pantry_lists_soonest_to_expire_first_and_undated_items_last(neal):
    for name, expires_on in [("Rice", None), ("Milk", day(5)), ("Chicken", day(1)), ("Beans", None)]:
        add(neal, name, expires_on)
    assert [item["name"] for item in neal.get("/api/items").json()] == ["Chicken", "Milk", "Beans", "Rice"]


@pytest.mark.parametrize(
    "offset, status, days_left",
    [
        (-2, "expired", -2),
        (0, "today", 0),
        (1, "soon", 1),
        (3, "soon", 3),
        (4, "fresh", 4),
        (None, "none", None),
    ],
)
def test_freshness_follows_the_days_left_until_expiry(neal, offset, status, days_left):
    item = add(neal, "Thing", None if offset is None else day(offset))
    assert (item["status"], item["days_left"]) == (status, days_left)


def test_use_soon_holds_expired_items_and_those_within_the_window_only(neal):
    for name, offset in [("Old", -3), ("Today", 0), ("Two", 2), ("Three", 3), ("Four", 4)]:
        add(neal, name, day(offset))
    add(neal, "Salt")
    assert [item["name"] for item in neal.get("/api/items/expiring").json()] == [
        "Old",
        "Today",
        "Two",
        "Three",
    ]
    assert [item["name"] for item in neal.get("/api/items/expiring?days=0").json()] == ["Old", "Today"]


def test_editing_changes_only_the_fields_sent_and_null_clears_the_expiry(neal):
    item = add(neal, "Milk", day(5), "a full gallon")
    edited = neal.patch(f"/api/items/{item['id']}", json={"description": "about half left"}).json()
    assert (edited["name"], edited["description"], edited["expires_on"]) == (
        "Milk",
        "about half left",
        day(5),
    )
    cleared = neal.patch(f"/api/items/{item['id']}", json={"expires_on": None}).json()
    assert (cleared["expires_on"], cleared["status"]) == (None, "none")


def test_a_discarded_item_is_gone(neal):
    item = add(neal, "Milk")
    assert neal.delete(f"/api/items/{item['id']}").status_code == 200
    assert neal.get(f"/api/items/{item['id']}").status_code == 404
    assert neal.delete(f"/api/items/{item['id']}").status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"name": ""}, {"name": "   "}, {"name": "x" * 81}, {"name": "Milk", "expires_on": "next week"}],
)
def test_items_need_a_name_and_a_real_date(neal, body):
    response = neal.post("/api/items", json=body)
    assert response.status_code == 422
    assert response.json()["error"]


def test_another_account_cannot_see_or_touch_an_item(neal, tianyue):
    item = add(neal, "Milk", day(2), "a full gallon")
    path = f"/api/items/{item['id']}"
    assert tianyue.get("/api/items").json() == []
    assert tianyue.get("/api/items/expiring").json() == []
    assert tianyue.get(path).status_code == 404
    assert tianyue.patch(path, json={"description": "gone"}).status_code == 404
    assert tianyue.delete(path).status_code == 404
    assert neal.get(path).json() == item
