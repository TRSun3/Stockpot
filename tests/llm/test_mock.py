"""The mock answers plausibly from the real pantry, and the same way every time."""

from datetime import timedelta

from conftest import TODAY

from stockpot.llm.mock import LIBRARY, Mock
from stockpot.schemas import PantryItem, Recipe, RecipeUse

mock = Mock(delay=0)


def item(id, name, description="", days=None):
    expires_on = None if days is None else (TODAY + timedelta(days=days)).isoformat()
    return PantryItem(id=id, name=name, description=description, expires_on=expires_on)


KITCHEN = [
    item(1, "Eggs", "a dozen eggs", 14),
    item(2, "Spinach", "a bag of spinach", 1),
    item(3, "Cheddar", "a block", 20),
    item(4, "Pasta", "a box of penne"),
    item(5, "Tomatoes", "4 vine tomatoes", 3),
    item(6, "Garlic", "a head", 40),
    item(7, "Milk", "half a gallon of 2% milk", -2),
]


def test_parsing_splits_a_sentence_into_items_and_keeps_the_quantities():
    items = mock.parse_items("I bought a dozen eggs, half gallon of milk and 3 bananas", TODAY)
    assert [(i.name, i.description) for i in items] == [
        ("Eggs", "a dozen eggs"),
        ("Milk", "half gallon of milk"),
        ("Bananas", "3 bananas"),
    ]


def test_parsing_estimates_expiry_from_what_a_food_is_and_how_it_is_kept():
    items = mock.parse_items(
        "chicken thighs, spinach, rice, a can of beans, frozen chicken, chicken broth, kumquats", TODAY
    )
    days = [None if i.expires_on is None else (i.expires_on, TODAY) for i in items]
    offsets = [None if d is None else (TODAY.fromisoformat(d[0]) - TODAY).days for d in days]
    assert offsets == [2, 5, None, None, 90, None, 7]


def test_recipes_favor_what_expires_soonest_and_only_use_real_unexpired_items():
    recipes = mock.suggest_recipes(KITCHEN, TODAY)
    assert recipes and len(recipes) <= 4
    assert any(use.item_id == 2 for use in recipes[0].uses)
    assert "spinach" in recipes[0].why.lower() and "tomorrow" in recipes[0].why
    ids = {i.id for i in KITCHEN}
    for recipe in recipes:
        assert {use.item_id for use in recipe.uses} <= ids - {7}
        assert len(recipe.missing) <= 2


def test_preferences_steer_the_suggestions():
    assert mock.suggest_recipes(KITCHEN, TODAY, "something vegetarian") != mock.suggest_recipes(KITCHEN, TODAY, "")
    quick = mock.suggest_recipes(KITCHEN, TODAY, "I'm exhausted, need something quick")[0]
    assert quick.time_minutes <= 20


def test_an_empty_pantry_gets_no_suggestions():
    assert mock.suggest_recipes([], TODAY) == []


def test_every_library_recipe_is_complete():
    titles = [recipe.title for recipe in LIBRARY]
    assert len(titles) == len(set(titles)) >= 15
    for recipe in LIBRARY:
        assert recipe.steps and recipe.ingredients and recipe.minutes > 0


def test_asking_for_a_known_dish_shows_what_is_missing():
    carbonara = mock.plan_recipe("Can I make carbonara?", KITCHEN, TODAY)
    assert carbonara.title == "Spaghetti Carbonara"
    assert {use.name for use in carbonara.uses} == {"Pasta", "Eggs"}
    assert carbonara.missing == ["bacon", "parmesan"]
    assert "bacon" in carbonara.why


def test_tweaking_follows_the_feedback():
    recipe = mock.plan_recipe("creamy garlic chicken", [item(1, "Chicken thighs", days=2), item(2, "Garlic")], TODAY)
    tweaked = mock.tweak_recipe(recipe, "make it vegetarian and spicier, and quicker", KITCHEN, TODAY)
    assert tweaked.title.startswith("Vegetarian Spicy") or tweaked.title.startswith("Spicy Vegetarian")
    assert not any("chicken" in use.name.lower() for use in tweaked.uses)
    assert tweaked.time_minutes < recipe.time_minutes
    assert "chili flakes" in tweaked.missing
    assert tweaked.why.startswith("Tweaked for you")


def test_cooking_counts_down_countable_items_and_marks_the_rest_partly_used():
    recipe = Recipe(
        title="Omelette",
        summary="",
        time_minutes=10,
        uses=[
            RecipeUse(item_id=1, name="Eggs", amount="3 eggs"),
            RecipeUse(item_id=2, name="Spinach", amount="a big handful"),
            RecipeUse(item_id=3, name="Cheddar", amount="all of it"),
        ],
        missing=[],
        steps=["Cook."],
        why="",
    )
    ops = {op.item_id: op for op in mock.apply_cooking(recipe, KITCHEN, TODAY)}
    assert (ops[1].op, ops[1].description) == ("update", "9 eggs")
    assert (ops[2].op, ops[2].description) == ("update", "a bag of spinach — partly used")
    assert ops[3].op == "delete"
    assert set(ops) == {1, 2, 3}


def test_an_adjustment_carries_its_verb_across_and_names_items_precisely():
    pantry = [*KITCHEN, item(8, "Chicken thighs", "2 lbs", 2), item(9, "Chicken broth", "a carton")]
    ops = mock.adjust_pantry("I used half the milk and all the eggs, and froze the chicken thighs", pantry, TODAY)
    by_id = {op.item_id: op for op in ops}
    assert by_id[7].description == "half a gallon of 2% milk — about half left"
    assert by_id[1].op == "delete"
    assert by_id[8].expires_on == (TODAY + timedelta(days=90)).isoformat()
    assert 9 not in by_id


def test_an_adjustment_about_new_food_adds_it():
    ops = mock.adjust_pantry("picked up a loaf of sourdough", KITCHEN, TODAY)
    assert [(op.op, op.name) for op in ops] == [("add", "Sourdough")]


def test_chat_streams_a_reply_built_on_the_pantry():
    pieces = list(mock.chat([], "I'm exhausted and want something cozy", KITCHEN, [], TODAY))
    reply = "".join(pieces)
    assert len(pieces) > 5
    assert "long one" in reply
    assert any(name in reply.lower() for name in ("spinach", "eggs", "cheddar", "pasta", "tomatoes"))
    assert "milk is past its date" in reply


def test_chat_with_an_empty_pantry_asks_what_there_is():
    assert "empty" in "".join(mock.chat([], "hi", [], [], TODAY))


def test_the_same_question_always_gets_the_same_answer():
    for _ in range(3):
        assert mock.suggest_recipes(KITCHEN, TODAY, "cozy") == mock.suggest_recipes(KITCHEN, TODAY, "cozy")
        assert list(mock.chat([], "hello", KITCHEN, [], TODAY)) == list(mock.chat([], "hello", KITCHEN, [], TODAY))


def test_parentheses_hold_a_note_together_and_expiry_comes_from_the_food():
    items = mock.parse_items("Lemons (two, organic), Bread (for grilled cheese and tomato soup)", TODAY)
    assert [(i.name, i.description) for i in items] == [
        ("Lemons", "two, organic"),
        ("Bread", "for grilled cheese and tomato soup"),
    ]
    assert items[1].expires_on == (TODAY + timedelta(days=5)).isoformat()


def test_what_someone_cannot_eat_keeps_its_scope_and_covers_whole_food_families():
    pantry = [*KITCHEN, item(8, "Salmon", "2 fillets", 1), item(9, "Asparagus", "a bunch", 2), item(10, "Lemon", "", 9)]
    no_dairy = mock.suggest_recipes(pantry, TODAY, "no dairy but love eggs")
    assert no_dairy and any(use.name == "Eggs" for recipe in no_dairy for use in recipe.uses)
    assert not any(use.name == "Cheddar" for recipe in no_dairy for use in recipe.uses)
    titles = [recipe.title for recipe in mock.suggest_recipes(pantry, TODAY, "", "allergic to fish")]
    assert not any("Salmon" in title for title in titles)
    stovetop = [recipe.title for recipe in mock.suggest_recipes(pantry, TODAY, "", "No oven, just a stovetop.")]
    assert not any("Salmon" in title for title in stovetop)


def test_optional_extras_the_user_avoids_are_left_out():
    pantry = [*KITCHEN, item(8, "Butter", "a stick", 20)]
    omelette = mock.plan_recipe("omelette", pantry, TODAY, "no butter")
    assert "Butter" not in [use.name for use in omelette.uses]


def test_asking_for_it_milder_takes_heat_away():
    recipe = mock.tweak_recipe(mock.plan_recipe("omelette", KITCHEN, TODAY), "spicier", KITCHEN, TODAY)
    milder = mock.tweak_recipe(recipe, "make it less spicy", KITCHEN, TODAY)
    assert not milder.title.startswith("Spicy") and "chili flakes" not in milder.missing


def test_everyday_adjustments_read_the_way_people_mean_them():
    pantry = [*KITCHEN, item(8, "Chicken thighs", "2 lbs", 60)]
    thawed = {
        op.item_id: op for op in mock.adjust_pantry("I took the chicken thighs out of the freezer", pantry, TODAY)
    }
    assert thawed[8].op == "update" and thawed[8].expires_on == (TODAY + timedelta(days=2)).isoformat()
    half = mock.adjust_pantry("I finished half the milk", pantry, TODAY)
    assert [(op.op, op.item_id) for op in half] == [("update", 7)]
    bought = mock.adjust_pantry("I bought chocolate and milk", pantry, TODAY)
    assert all(op.op != "update" or "partly" not in (op.description or "") for op in bought)


def test_dishes_match_by_whole_words_and_never_use_expired_items():
    assert mock.plan_recipe("tea", KITCHEN, TODAY).title == "Tea"
    assert mock.plan_recipe("fruit salad", KITCHEN, TODAY).title == "Fruit salad"
    plan = mock.plan_recipe("milk pudding", KITCHEN, TODAY)
    assert 7 not in [use.item_id for use in plan.uses]


def test_cooking_counts_down_bare_numbers_and_never_subtracts_measures():
    pantry = [item(1, "Avocados", "2 ripe avocados", 2), item(2, "Tomatoes", "4 vine tomatoes", 3)]
    recipe = Recipe(
        title="Toast",
        summary="",
        time_minutes=5,
        uses=[
            RecipeUse(item_id=1, name="Avocados", amount="1"),
            RecipeUse(item_id=2, name="Tomatoes", amount="2 cups, halved"),
        ],
        missing=[],
        steps=["Go."],
        why="",
    )
    ops = {op.item_id: op for op in mock.apply_cooking(recipe, pantry, TODAY)}
    assert ops[1].description == "1 ripe avocado"
    assert ops[2].description == "4 vine tomatoes — partly used"
