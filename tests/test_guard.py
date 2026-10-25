"""What the LLM proposes is checked before it lands: foreign, missing, and malformed changes are refused."""

from contextlib import closing
from datetime import timedelta

import pytest
from conftest import TODAY

from stockpot import auth, db, guard, pantry
from stockpot.schemas import PantryOp, ParsedItem, Recipe, RecipeUse


@pytest.fixture
def conn(settings):
    db.init(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn:
        yield conn


@pytest.fixture
def kitchen(conn):
    """Two users with a few items each: (neal's id, tianyue's id, neal's items, tianyue's items)."""
    neal, tianyue = auth.create_user(conn, "neal", "password1"), auth.create_user(conn, "tianyue", "password1")
    mine = {name: pantry.insert(conn, neal.id, name, f"some {name.lower()}", None) for name in ("Milk", "Eggs", "Rice")}
    theirs = {"Tofu": pantry.insert(conn, tianyue.id, "Tofu", "a block", None)}
    return neal.id, tianyue.id, mine, theirs


def names(conn, user_id):
    return {row["name"]: row["description"] for row in pantry.rows(conn, user_id)}


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-30", TODAY + timedelta(days=6)),
        (" 2026-10-24 ", TODAY),
        ((TODAY - timedelta(days=30)).isoformat(), TODAY - timedelta(days=30)),
        ((TODAY - timedelta(days=31)).isoformat(), None),
        ((TODAY + timedelta(days=5 * 365 + 1)).isoformat(), None),
        ("next tuesday", None),
        ("", None),
        (None, None),
    ],
)
def test_only_believable_iso_dates_survive(value, expected):
    assert guard.clean_date(value, TODAY) == expected


def test_parsed_groceries_lose_blank_names_and_impossible_dates():
    items = [
        ParsedItem(name="  milk ", description="a   gallon", expires_on="2026-10-31"),
        ParsedItem(name="   ", description="nameless", expires_on=None),
        ParsedItem(name="Eggs", description="", expires_on="3026-01-01"),
    ]
    assert guard.clean_parsed(items, TODAY) == [("Milk", "a gallon", TODAY + timedelta(days=7)), ("Eggs", "", None)]


def test_valid_ops_apply_and_report_what_changed(conn, kitchen):
    neal, _, mine, _ = kitchen
    result = guard.apply_ops(
        conn,
        neal,
        [
            PantryOp(op="update", item_id=mine["Milk"], description="about half left"),
            PantryOp(op="delete", item_id=mine["Eggs"]),
        ],
        TODAY,
    )
    assert result["rejected"] == []
    assert [(c["action"], c["name"]) for c in result["changes"]] == [("updated", "Milk"), ("removed", "Eggs")]
    assert names(conn, neal) == {"Milk": "about half left", "Rice": "some rice"}


def test_ops_on_someone_elses_or_a_missing_item_are_refused_and_leave_both_pantries_alone(conn, kitchen):
    neal, tianyue, mine, theirs = kitchen
    before = names(conn, neal), names(conn, tianyue)
    result = guard.apply_ops(
        conn,
        neal,
        [PantryOp(op="delete", item_id=theirs["Tofu"]), PantryOp(op="update", item_id=9999, description="x")],
        TODAY,
    )
    assert result["changes"] == []
    assert [r["reason"] for r in result["rejected"]] == ["no such item in this pantry"] * 2
    assert (names(conn, neal), names(conn, tianyue)) == before


def test_malformed_ops_are_refused_while_the_valid_ones_in_the_batch_still_apply(conn, kitchen):
    neal, _, mine, _ = kitchen
    result = guard.apply_ops(
        conn,
        neal,
        [
            PantryOp(op="update", item_id=mine["Milk"]),
            PantryOp(op="update", item_id=mine["Milk"], description="   "),
            PantryOp(op="delete"),
            PantryOp(op="add", name="Bread"),
            PantryOp(op="delete", item_id=mine["Rice"]),
            PantryOp(op="update", item_id=mine["Rice"], description="came back"),
        ],
        TODAY,
    )
    assert [r["reason"] for r in result["rejected"]] == [
        "an update needs a new description",
        "an update needs a new description",
        "no such item in this pantry",
        "adding items isn't allowed here",
        "that item was already changed",
    ]
    assert [(c["action"], c["name"]) for c in result["changes"]] == [("removed", "Rice")]
    assert names(conn, neal) == {"Milk": "some milk", "Eggs": "some eggs"}


def test_ops_can_be_limited_to_the_items_a_recipe_used(conn, kitchen):
    neal, _, mine, _ = kitchen
    result = guard.apply_ops(
        conn,
        neal,
        [PantryOp(op="delete", item_id=mine["Eggs"]), PantryOp(op="delete", item_id=mine["Milk"])],
        TODAY,
        allowed={mine["Eggs"]},
    )
    assert [r["reason"] for r in result["rejected"]] == ["that item isn't part of this change"]
    assert set(names(conn, neal)) == {"Milk", "Rice"}


def test_an_add_needs_permission_a_name_and_a_new_food_and_keeps_only_a_believable_expiry(conn, kitchen):
    neal, _, _, _ = kitchen
    result = guard.apply_ops(
        conn,
        neal,
        [
            PantryOp(op="add", name="bread", description="a sourdough loaf", expires_on="2026-10-29"),
            PantryOp(op="add", name="  ", description="nameless"),
            PantryOp(op="add", name="Jam", expires_on="1999-01-01"),
            PantryOp(op="add", name="egg", description="a dozen"),
            PantryOp(op="add", name="Breads", description="another loaf"),
        ],
        TODAY,
        allow_add=True,
    )
    duplicate = "that's already in the pantry, so it should be updated instead"
    assert [r["reason"] for r in result["rejected"]] == ["an added item needs a name", duplicate, duplicate]
    added = {row["name"]: row["expires_on"] for row in pantry.rows(conn, neal)}
    assert (added["Bread"], added["Jam"]) == ("2026-10-29", None)
    assert names(conn, neal)["Eggs"] == "some eggs"


def test_a_food_thrown_out_can_be_added_back_fresh_in_the_same_batch(conn, kitchen):
    neal, _, mine, _ = kitchen
    result = guard.apply_ops(
        conn,
        neal,
        [PantryOp(op="delete", item_id=mine["Milk"]), PantryOp(op="add", name="Milk", description="a new gallon")],
        TODAY,
        allow_add=True,
    )
    assert result["rejected"] == []
    assert names(conn, neal)["Milk"] == "a new gallon"


def test_removing_one_of_two_copies_of_a_food_still_refuses_adding_it_again(conn, kitchen):
    neal, _, mine, _ = kitchen
    pantry.insert(conn, neal, "rice", "a second bag", None)
    result = guard.apply_ops(
        conn,
        neal,
        [PantryOp(op="delete", item_id=mine["Rice"]), PantryOp(op="add", name="Rice", description="a third bag")],
        TODAY,
        allow_add=True,
    )
    assert [r["reason"] for r in result["rejected"]] == [
        "that's already in the pantry, so it should be updated instead"
    ]
    assert [row["description"] for row in pantry.rows(conn, neal) if row["name"].lower() == "rice"] == ["a second bag"]


def test_a_failure_partway_through_leaves_the_pantry_exactly_as_it_was(conn, kitchen, monkeypatch):
    neal, _, mine, _ = kitchen
    before = names(conn, neal)
    monkeypatch.setattr(pantry, "delete", lambda *args: (_ for _ in ()).throw(RuntimeError("disk full")))
    with pytest.raises(RuntimeError):
        guard.apply_ops(
            conn,
            neal,
            [
                PantryOp(op="update", item_id=mine["Milk"], description="changed"),
                PantryOp(op="delete", item_id=mine["Eggs"]),
            ],
            TODAY,
        )
    assert names(conn, neal) == before


def test_a_recipe_only_claims_items_the_user_owns_and_the_rest_become_missing(conn, kitchen):
    neal, _, mine, theirs = kitchen
    owned = {row["id"]: row for row in pantry.rows(conn, neal)}
    recipe = Recipe(
        title=" Egg  Fried Rice ",
        summary="Crispy.",
        time_minutes=0,
        uses=[
            RecipeUse(item_id=mine["Eggs"], name="Huevos", amount="2"),
            RecipeUse(item_id=mine["Eggs"], name="Eggs", amount="2 more"),
            RecipeUse(item_id=theirs["Tofu"], name="Tofu", amount="a block"),
            RecipeUse(item_id=4242, name="Scallions", amount="2"),
        ],
        missing=["Soy sauce", "Tofu"],
        steps=["Fry.", "  ", "Eat."],
        why="Why not.",
    )
    cleaned = guard.clean_recipe(recipe, owned)
    assert cleaned.title == "Egg Fried Rice"
    assert cleaned.time_minutes == 1
    assert [(use.item_id, use.name) for use in cleaned.uses] == [(mine["Eggs"], "Eggs")]
    assert cleaned.missing == ["Soy sauce", "Tofu", "Scallions"]
    assert cleaned.steps == ["Fry.", "Eat."]


def test_a_recipe_without_a_title_or_steps_is_dropped(conn, kitchen):
    blank = Recipe(title=" ", summary="", time_minutes=5, uses=[], missing=[], steps=["Cook."], why="")
    stepless = blank.model_copy(update={"title": "Toast", "steps": [" "]})
    assert guard.clean_recipe(blank, {}) is None
    assert guard.clean_recipe(stepless, {}) is None
