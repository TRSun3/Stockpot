"""Every prompt tells the model today's date, the real pantry with its ids, and how fresh each item is."""

from conftest import TODAY

from stockpot.llm import prompts
from stockpot.schemas import PantryItem, ShoppingEntry

PANTRY = [
    PantryItem(id=3, name="Milk", description="half a gallon", expires_on="2026-10-22"),
    PantryItem(id=9, name="Rice", description="", expires_on=None),
    PantryItem(id=12, name="Spinach", description="a bag", expires_on="2026-10-24"),
]


def test_the_pantry_block_lists_each_item_with_its_id_and_freshness():
    block = prompts.pantry_block(PANTRY, TODAY)
    assert "Today is 2026-10-24 (Saturday)." in block
    assert "- [3] Milk | half a gallon | EXPIRED 2 days ago" in block
    assert "- [9] Rice | (no details) | no expiry" in block
    assert "- [12] Spinach | a bag | expires TODAY" in block


def test_an_empty_pantry_is_said_out_loud():
    assert "The pantry is empty." in prompts.pantry_block([], TODAY)


def test_every_pantry_prompt_carries_the_pantry_and_the_id_rule():
    recipe = prompts.Recipe(title="T", summary="", time_minutes=5, uses=[], missing=[], steps=["s"], why="")
    for system, _ in (
        prompts.suggest_recipes(PANTRY, TODAY, ""),
        prompts.plan_recipe("soup", PANTRY, TODAY),
        prompts.tweak_recipe(recipe, "spicier", PANTRY, TODAY),
        prompts.apply_cooking(recipe, PANTRY, TODAY),
        prompts.adjust_pantry("used the milk", PANTRY, TODAY),
    ):
        assert "[12] Spinach" in system
        assert "Never invent an item_id" in system


def test_the_chat_prompt_includes_the_shopping_list():
    system = prompts.chat_system(PANTRY, [ShoppingEntry(name="Lemons", note="two", checked=False)], TODAY)
    assert "- [ ] Lemons (two)" in system and "[3] Milk" in system
