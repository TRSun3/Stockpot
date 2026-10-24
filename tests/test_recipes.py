"""Recipes: suggestions that favor what's expiring, "can I make this?", tweaks, cooking, and the recipe box."""

from datetime import timedelta

from conftest import TODAY

from stockpot.llm.mock import Mock
from stockpot.schemas import PantryOp, Recipe, RecipeUse


class Overreaching(Mock):
    """Cooks by deleting every item in the pantry, used or not."""

    def apply_cooking(self, recipe, pantry, today):
        return [PantryOp(op="delete", item_id=item.id) for item in pantry]


class Inventive(Mock):
    """Suggests a recipe that claims an item the user doesn't have."""

    def suggest_recipes(self, pantry, today, preferences="", notes=""):
        use = RecipeUse(item_id=9999, name="Truffles", amount="a few")
        return [Recipe(title="Truffle Eggs", summary="", time_minutes=5, uses=[use], missing=[], steps=["Go."], why="")]


def stock(client, items):
    """Adds (name, description, days until expiry or None) items and returns them by name."""
    added = {}
    for name, description, days in items:
        expires_on = None if days is None else (TODAY + timedelta(days=days)).isoformat()
        body = {"name": name, "description": description, "expires_on": expires_on}
        added[name] = client.post("/api/items", json=body).json()
    return added


KITCHEN = [
    ("Eggs", "a dozen eggs", 14),
    ("Spinach", "a bag of spinach", 1),
    ("Cheddar", "a block", 20),
    ("Pasta", "a box of penne", None),
    ("Tomatoes", "4 vine tomatoes", 4),
    ("Garlic", "a head", 40),
]


def test_suggestions_favor_what_expires_soonest_and_only_claim_real_items(neal):
    items = stock(neal, KITCHEN)
    recipes = neal.post("/api/recipes/suggest", json={}).json()["recipes"]
    assert recipes
    assert items["Spinach"]["id"] in {use["item_id"] for use in recipes[0]["uses"]}
    ids = {item["id"] for item in items.values()}
    for recipe in recipes:
        assert set(recipe) == {"title", "summary", "time_minutes", "uses", "missing", "steps", "why"}
        assert {use["item_id"] for use in recipe["uses"]} <= ids
        assert recipe["steps"] and len(recipe["missing"]) <= 2


def test_a_suggested_item_the_user_does_not_have_becomes_a_missing_ingredient(app, neal):
    stock(neal, KITCHEN)
    app.state.llm = Inventive()
    recipe = neal.post("/api/recipes/suggest", json={}).json()["recipes"][0]
    assert (recipe["uses"], recipe["missing"]) == ([], ["Truffles"])


def test_kitchen_notes_are_kept_and_steer_suggestions(neal):
    stock(neal, [*KITCHEN, ("Chicken thighs", "2 lbs", 1), ("Cream", "a pint", 5)])
    assert neal.get("/api/preferences").json() == {"notes": ""}
    meaty = neal.post("/api/recipes/suggest", json={}).json()["recipes"]
    assert any("Chicken" in recipe["title"] for recipe in meaty)
    assert neal.put("/api/preferences", json={"notes": "I'm vegetarian"}).json() == {"notes": "I'm vegetarian"}
    assert neal.get("/api/preferences").json() == {"notes": "I'm vegetarian"}
    veggie = neal.post("/api/recipes/suggest", json={}).json()["recipes"]
    assert veggie and not any("Chicken" in recipe["title"] for recipe in veggie)


def test_asking_for_a_dish_shows_what_is_there_and_what_is_missing(neal):
    stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "carbonara"}).json()["recipe"]
    assert recipe["title"] == "Spaghetti Carbonara"
    assert {use["name"] for use in recipe["uses"]} == {"Pasta", "Eggs"}
    assert recipe["missing"] == ["bacon", "parmesan"]


def test_a_tweaked_recipe_follows_the_feedback(neal):
    stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "omelette"}).json()["recipe"]
    tweaked = neal.post("/api/recipes/tweak", json={"recipe": recipe, "feedback": "make it spicier"}).json()["recipe"]
    assert tweaked["title"].startswith("Spicy")
    assert "Tweaked" in tweaked["why"]


def test_cooking_updates_the_items_the_recipe_used_and_says_what_changed(neal):
    items = stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "omelette"}).json()["recipe"]
    result = neal.post("/api/recipes/cooked", json={"recipe": recipe}).json()
    assert {change["name"] for change in result["changes"]} == {"Eggs", "Spinach", "Cheddar"}
    assert result["rejected"] == []
    eggs = neal.get(f"/api/items/{items['Eggs']['id']}").json()
    assert eggs["description"] == "9 eggs"
    assert neal.get(f"/api/items/{items['Garlic']['id']}").json() == items["Garlic"]


def test_cooking_never_touches_items_the_recipe_did_not_use(app, neal):
    items = stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "omelette"}).json()["recipe"]
    app.state.llm = Overreaching()
    result = neal.post("/api/recipes/cooked", json={"recipe": recipe}).json()
    assert {change["name"] for change in result["changes"]} == {"Eggs", "Spinach", "Cheddar"}
    assert {reject["reason"] for reject in result["rejected"]} == {"that item isn't part of this change"}
    assert {item["name"] for item in neal.get("/api/items").json()} == {"Pasta", "Tomatoes", "Garlic"}
    assert items


def test_cooking_with_another_accounts_items_is_refused(neal, tianyue):
    stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "omelette"}).json()["recipe"]
    response = tianyue.post("/api/recipes/cooked", json={"recipe": recipe})
    assert response.status_code == 404
    assert len(neal.get("/api/items").json()) == len(KITCHEN)


def test_missing_ingredients_join_the_shopping_list_once(neal):
    neal.post("/api/shopping", json={"name": "Bacon"})
    result = neal.post(
        "/api/recipes/missing-to-shopping",
        json={"names": ["bacon", "Parmesan", "Parmesan"], "recipe_title": "Spaghetti Carbonara"},
    ).json()
    assert [entry["name"] for entry in result["added"]] == ["Parmesan"]
    assert result["added"][0]["note"] == "for Spaghetti Carbonara"
    assert result["skipped"] == ["bacon"]
    assert [entry["name"] for entry in neal.get("/api/shopping").json()] == ["Bacon", "Parmesan"]


def test_the_recipe_box_keeps_recipes_for_their_owner_only(neal, tianyue):
    stock(neal, KITCHEN)
    recipe = neal.post("/api/recipes/plan", json={"dish": "omelette"}).json()["recipe"]
    saved = neal.post("/api/recipes/saved", json={"recipe": recipe}).json()
    assert [entry["recipe"]["title"] for entry in neal.get("/api/recipes/saved").json()] == [recipe["title"]]
    assert tianyue.get("/api/recipes/saved").json() == []
    assert tianyue.delete(f"/api/recipes/saved/{saved['id']}").status_code == 404
    assert neal.delete(f"/api/recipes/saved/{saved['id']}").status_code == 200
    assert neal.get("/api/recipes/saved").json() == []
