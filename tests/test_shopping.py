"""The shopping list: adding, checking off, removing, and whose list it is."""


def add(client, name, note=""):
    response = client.post("/api/shopping", json={"name": name, "note": note})
    assert response.status_code == 201, response.text
    return response.json()


def test_an_added_entry_starts_unchecked(neal):
    entry = add(neal, "Lemons", "two")
    assert {k: entry[k] for k in ("name", "note", "checked")} == {
        "name": "Lemons",
        "note": "two",
        "checked": False,
    }


def test_checked_entries_sink_below_unchecked_ones(neal):
    lemons = add(neal, "Lemons")
    add(neal, "Eggs")
    add(neal, "Flour")
    assert neal.patch(f"/api/shopping/{lemons['id']}", json={"checked": True}).json()["checked"] is True
    assert [entry["name"] for entry in neal.get("/api/shopping").json()] == ["Eggs", "Flour", "Lemons"]
    neal.patch(f"/api/shopping/{lemons['id']}", json={"checked": False})
    assert [entry["name"] for entry in neal.get("/api/shopping").json()] == ["Lemons", "Eggs", "Flour"]


def test_editing_an_entry_changes_only_the_fields_sent(neal):
    entry = add(neal, "Lemons", "two")
    edited = neal.patch(f"/api/shopping/{entry['id']}", json={"note": "a bag"}).json()
    assert (edited["name"], edited["note"], edited["checked"]) == ("Lemons", "a bag", False)


def test_a_removed_entry_is_gone(neal):
    entry = add(neal, "Lemons")
    assert neal.delete(f"/api/shopping/{entry['id']}").status_code == 200
    assert neal.get("/api/shopping").json() == []
    assert neal.delete(f"/api/shopping/{entry['id']}").status_code == 404


def test_an_entry_needs_a_name(neal):
    assert neal.post("/api/shopping", json={"name": " "}).status_code == 422


def test_another_account_cannot_see_or_touch_an_entry(neal, tianyue):
    entry = add(neal, "Lemons")
    path = f"/api/shopping/{entry['id']}"
    assert tianyue.get("/api/shopping").json() == []
    assert tianyue.patch(path, json={"checked": True}).status_code == 404
    assert tianyue.delete(path).status_code == 404
    assert neal.get("/api/shopping").json() == [entry]
