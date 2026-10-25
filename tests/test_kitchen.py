"""Changing the kitchen in plain words: typed groceries, pantry adjustments, and unpacking the shopping."""

from stockpot.llm import LLMError
from stockpot.llm.mock import Mock
from stockpot.schemas import PantryOp


class Failing(Mock):
    def parse_items(self, text, today):
        raise LLMError("timed out")

    def adjust_pantry(self, instruction, pantry, today):
        raise LLMError("timed out")


class Proposing(Mock):
    """Proposes exactly the ops it is given, whatever the instruction."""

    def __init__(self, ops):
        super().__init__(delay=0)
        self.ops = ops

    def adjust_pantry(self, instruction, pantry, today):
        return self.ops


def pantry_of(client):
    return {item["name"]: item for item in client.get("/api/items").json()}


def test_groceries_typed_as_a_sentence_become_items_with_sensible_expiries(neal):
    text = "just got back from the store: a dozen eggs, a bag of spinach, chicken thighs and some cheddar"
    response = neal.post("/api/items/parse", json={"text": text})
    assert response.status_code == 201
    added = {item["name"]: item for item in response.json()}
    assert set(added) == {"Eggs", "Spinach", "Chicken thighs", "Cheddar"}
    assert added["Eggs"]["description"] == "a dozen eggs"
    assert [added[name]["days_left"] for name in ("Chicken thighs", "Spinach", "Eggs")] == [2, 5, 21]
    assert set(pantry_of(neal)) == set(added)


def test_text_with_no_groceries_in_it_adds_nothing_and_says_so(neal):
    response = neal.post("/api/items/parse", json={"text": " , and . "})
    assert response.status_code == 422
    assert "groceries" in response.json()["error"]
    assert neal.get("/api/items").json() == []


def test_an_adjustment_in_plain_words_updates_removes_and_adds_items(neal):
    neal.post("/api/items/parse", json={"text": "half gallon of milk, 6 eggs, spinach"})
    result = neal.post(
        "/api/items/adjust", json={"text": "I used half the milk, the spinach went bad, and I bought a loaf of bread"}
    ).json()
    assert sorted((c["action"], c["name"]) for c in result["changes"]) == [
        ("added", "Bread"),
        ("removed", "Spinach"),
        ("updated", "Milk"),
    ]
    items = pantry_of(neal)
    assert set(items) == {"Milk", "Eggs", "Bread"}
    assert "half left" in items["Milk"]["description"]


def test_an_adjustment_cannot_reach_another_accounts_items_even_when_the_llm_names_them(app, neal, tianyue):
    tofu = tianyue.post("/api/items", json={"name": "Tofu", "description": "a block"}).json()
    app.state.llm = Proposing([PantryOp(op="delete", item_id=tofu["id"])])
    result = neal.post("/api/items/adjust", json={"text": "toss the tofu"}).json()
    assert result["changes"] == []
    assert result["rejected"][0]["reason"] == "no such item in this pantry"
    assert tianyue.get(f"/api/items/{tofu['id']}").status_code == 200


def test_checked_shopping_moves_into_the_pantry_and_off_the_list(neal):
    for name, note in [("Milk", "2%"), ("Spinach", ""), ("Lemons", "")]:
        neal.post("/api/shopping", json={"name": name, "note": note})
    entries = neal.get("/api/shopping").json()
    for entry in entries[:2]:
        neal.patch(f"/api/shopping/{entry['id']}", json={"checked": True})
    moved = neal.post("/api/shopping/move-to-pantry").json()["moved"]
    assert [item["name"] for item in moved] == ["Milk", "Spinach"]
    assert all(item["expires_on"] for item in moved)
    assert [entry["name"] for entry in neal.get("/api/shopping").json()] == ["Lemons"]
    assert set(pantry_of(neal)) == {"Milk", "Spinach"}


def test_moving_with_nothing_checked_is_refused(neal):
    neal.post("/api/shopping", json={"name": "Lemons"})
    response = neal.post("/api/shopping/move-to-pantry")
    assert response.status_code == 400
    assert neal.get("/api/items").json() == []


def test_an_llm_failure_answers_with_a_friendly_error_and_changes_nothing(app, neal):
    neal.post("/api/items", json={"name": "Milk"})
    neal.post("/api/shopping", json={"name": "Eggs"})
    entry = neal.get("/api/shopping").json()[0]
    neal.patch(f"/api/shopping/{entry['id']}", json={"checked": True})
    app.state.llm = Failing()
    for path, body in [("/api/items/parse", {"text": "eggs"}), ("/api/items/adjust", {"text": "used the milk"})]:
        response = neal.post(path, json=body)
        assert response.status_code == 502
        assert "try again" in response.json()["error"]
    assert neal.post("/api/shopping/move-to-pantry").status_code == 502
    assert list(pantry_of(neal)) == ["Milk"]
    assert neal.get("/api/shopping").json()[0]["checked"] is True


class Picky(Mock):
    """Parses only food it recognizes, the way Gemini ignores non-food."""

    def parse_items(self, text, today):
        return [item for item in super().parse_items(text, today) if item.name != "Paper towels"]


def test_moved_shopping_keeps_its_own_names_and_notes_even_when_notes_read_like_lists(app, neal):
    app.state.llm = Picky(delay=0)
    for name, note in [
        ("Spinach", "for Spinach and Cheddar Omelette"),
        ("Lemons", "two, organic"),
        ("Paper towels", ""),
    ]:
        entry = neal.post("/api/shopping", json={"name": name, "note": note}).json()
        neal.patch(f"/api/shopping/{entry['id']}", json={"checked": True})
    moved = neal.post("/api/shopping/move-to-pantry").json()["moved"]
    assert [(item["name"], item["description"]) for item in moved] == [
        ("Spinach", "for Spinach and Cheddar Omelette"),
        ("Lemons", "two, organic"),
        ("Paper towels", ""),
    ]
    assert moved[0]["days_left"] == 5 and moved[2]["expires_on"] is None
    assert neal.get("/api/shopping").json() == []
