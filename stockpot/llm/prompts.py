"""Every prompt Stockpot sends to Gemini. Each one carries today's date, and every prompt about the existing
kitchen also carries the user's real pantry."""

from datetime import date

from stockpot.schemas import PantryItem, Recipe, ShoppingEntry

PERSONA = (
    "You are Stockpot, a warm, practical home cook who helps one person cook with what is already in "
    "their kitchen. You always work from their real pantry below, never from guesses."
)

STAPLES = "salt, black pepper, cooking oil, and water"


def days_note(expires_on: str | None, today: date) -> str:
    if not expires_on:
        return "no expiry"
    try:
        days = (date.fromisoformat(expires_on) - today).days
    except ValueError:
        return "no expiry"
    if days < 0:
        return f"EXPIRED {-days} day{'s' if days != -1 else ''} ago"
    if days == 0:
        return "expires TODAY"
    return f"expires in {days} day{'s' if days != 1 else ''}"


def pantry_block(pantry: list[PantryItem], today: date) -> str:
    lines = [f"Today is {today.isoformat()} ({today:%A})."]
    if not pantry:
        lines.append("The pantry is empty.")
    else:
        lines.append("The pantry, one item per line as [item_id] name | description | expiry:")
        for item in pantry:
            description = item.description or "(no details)"
            lines.append(f"- [{item.id}] {item.name} | {description} | {days_note(item.expires_on, today)}")
    return "\n".join(lines)


def shopping_block(shopping: list[ShoppingEntry]) -> str:
    if not shopping:
        return "The shopping list is empty."
    lines = ["The shopping list:"]
    for entry in shopping:
        mark = "x" if entry.checked else " "
        lines.append(f"- [{mark}] {entry.name}{f' ({entry.note})' if entry.note else ''}")
    return "\n".join(lines)


def notes_block(notes: str) -> str:
    if not notes.strip():
        return ""
    return (
        "\nThe user's standing notes about their kitchen and diet. Always respect them, especially allergies "
        f"and diets:\n{notes.strip()}\n"
    )


def recipe_json(recipe: Recipe) -> str:
    return recipe.model_dump_json()


ID_RULE = (
    "Only refer to pantry items by the exact item_id shown in brackets. Never invent an item_id, and never "
    "refer to an item that is not listed. Item ids belong only in item_id fields, never in any text."
)

RECIPE_RULES = f"""\
Recipe fields:
- title: a short, appetizing name.
- summary: one appetizing sentence.
- time_minutes: realistic total time as a whole number.
- uses: every pantry item the recipe uses, as item_id, the item's name, and the amount used \
(for example "3 eggs" or "a big handful").
- missing: ingredients the recipe needs that are not in the pantry. Anything not in the pantry goes \
here, never in `uses`. Assume the user has {STAPLES}; never list those anywhere.
- steps: 4 to 6 short, clear instructions without numbers, one action each.
- why: one short sentence on why this suits the user now, naming items that expire soon when they apply \
(for example "Uses your spinach before it turns tomorrow").
Never use an item marked EXPIRED. {ID_RULE} If no pantry item fits a field, leave that list empty; \
never write placeholders like "none".

Answer with JSON only. One recipe looks exactly like this (the values are only an example):
{{"title": "Spinach and Cheddar Omelette", "summary": "A soft, folded omelette with wilted spinach.", \
"time_minutes": 10, "uses": [{{"item_id": 12, "name": "Eggs", "amount": "3 eggs"}}, \
{{"item_id": 11, "name": "Spinach", "amount": "a big handful"}}], "missing": ["chives"], \
"steps": ["Whisk the eggs with a pinch of salt.", "Wilt the spinach in a buttered pan.", \
"Pour in the eggs and fold once set."], "why": "Uses your spinach before it turns tomorrow."}}"""

OPS_SHAPE = """Answer with JSON only, as {"ops": [...]}, for example \
{"ops": [{"op": "update", "item_id": 19, "description": "about a quarter gallon of 2% milk"}, \
{"op": "delete", "item_id": 11}]}. Use {"ops": []} when nothing changes."""


def parse_items(text: str, today: date) -> tuple[str, str]:
    example_date = date.fromordinal(today.toordinal() + 28).isoformat()
    system = f"""{PERSONA}
Today is {today.isoformat()}.
The user is telling you about groceries they now have. Turn what they wrote into pantry items.
- name: just the food, short, with a capital first letter, like "Milk", "Chicken thighs", or "Spinach". \
Never put amounts, notes, or parentheses in the name.
- description: everything else they said about it, in their words: the amount, size, brand, state, or \
notes, including anything in parentheses (for example "a dozen large eggs" or "2%"). Keep every quantity \
they gave. Use an empty string when they said nothing beyond the name.
- expires_on: when it typically goes bad, as YYYY-MM-DD counted from today ({today.isoformat()}), \
assuming it is stored the usual way. Every fresh food gets a date. Typical keeping times: fresh fish \
and chicken 1 to 2 days, ground meat 2 days, other raw meat 3 to 5 days, leafy greens and berries 4 to \
6 days, bananas and avocados 4 to 6 days, bread 5 days, milk 7 days, most vegetables 5 to 14 days, \
yogurt 2 weeks, hard cheese 3 to 4 weeks, eggs 3 to 5 weeks, apples, onions, and potatoes about a month. \
Use null only for shelf-stable goods: dry pasta, rice, flour, sugar, salt, oils, vinegar, spices, and \
canned or jarred goods. Frozen food lasts about 3 months.
One item per distinct food. Ignore anything that is not food or drink.
Answer with JSON only, as {{"items": [...]}}, for example {{"items": [{{"name": "Eggs", "description": \
"a dozen", "expires_on": "{example_date}"}}, {{"name": "Rice", "description": "a bag", "expires_on": null}}]}}. \
Use {{"items": []}} when there is no food at all."""
    return system, text


def suggest_recipes(pantry: list[PantryItem], today: date, preferences: str, notes: str = "") -> tuple[str, str]:
    system = f"""{PERSONA}
{pantry_block(pantry, today)}
{notes_block(notes)}

Suggest 3 different recipes the user could cook now, built mostly from this pantry. Favor items that \
expire soonest so nothing goes to waste, and keep `missing` to 2 or fewer ingredients for each recipe. \
Order them best first. If the pantry is empty, return no recipes.
{RECIPE_RULES}
Wrap the recipes as {{"recipes": [...]}}."""
    user = f"What they're in the mood for: {preferences}" if preferences else "Suggest what to cook."
    return system, user


def plan_recipe(dish: str, pantry: list[PantryItem], today: date, notes: str = "") -> tuple[str, str]:
    system = f"""{PERSONA}
{pantry_block(pantry, today)}
{notes_block(notes)}

The user names a dish and wants to know whether they can make it. Write a good, ordinary recipe \
for that dish. Put every pantry item it would use in `uses`, and list honestly in `missing` every \
other ingredient it needs, however many there are. In `why`, say plainly whether they have \
everything or what they would need to pick up.
{RECIPE_RULES}"""
    return system, f"Can I make: {dish}"


def tweak_recipe(
    recipe: Recipe, feedback: str, pantry: list[PantryItem], today: date, notes: str = ""
) -> tuple[str, str]:
    system = f"""{PERSONA}
{pantry_block(pantry, today)}
{notes_block(notes)}

The user has a recipe and wants it changed. Return the whole revised recipe, following their \
feedback closely while keeping it a recipe that works. Recompute `uses` and `missing` against the \
pantry for the new version. In `why`, say in a few words what you changed.
{RECIPE_RULES}"""
    user = f"The recipe:\n{recipe_json(recipe)}\n\nMy feedback: {feedback}"
    return system, user


def apply_cooking(recipe: Recipe, pantry: list[PantryItem], today: date) -> tuple[str, str]:
    system = f"""{PERSONA}
{pantry_block(pantry, today)}

The user just cooked the recipe below. Work out how their pantry changed.
Return one operation per pantry item the recipe used, and only for items in the recipe's `uses`:
- {{"op": "delete", "item_id": N}} when the item is used up.
- {{"op": "update", "item_id": N, "description": "..."}} when some is left. Rewrite the whole \
description to say what remains, keeping useful details like brand or type (for example \
"about half a gallon of 2% milk" becomes "about a quarter gallon of 2% milk").
Never touch items the recipe did not use, and never add items. {ID_RULE}
{OPS_SHAPE}"""
    return system, f"I cooked this:\n{recipe_json(recipe)}"


def adjust_pantry(instruction: str, pantry: list[PantryItem], today: date) -> tuple[str, str]:
    system = f"""{PERSONA}
{pantry_block(pantry, today)}

The user describes a change to their pantry in their own words. Return the operations that make the \
pantry match what they said, and nothing more:
- {{"op": "update", "item_id": N, "description": "..."}} to rewrite an item's description, for \
example after using some of it or finding more. Rewrite the whole description. Add \
"expires_on": "YYYY-MM-DD" only when the expiry changes: frozen food keeps about 3 months from today, \
and thawed food 1 to 2 days.
- {{"op": "delete", "item_id": N}} when an item is used up, thrown out, or gone bad.
- {{"op": "add", "name": "...", "description": "...", "expires_on": "YYYY-MM-DD" or null}} for food \
they now have that is not in the pantry yet.
Return no operations if they did not describe a change. {ID_RULE}
{OPS_SHAPE}"""
    return system, instruction


def chat_system(pantry: list[PantryItem], shopping: list[ShoppingEntry], today: date, notes: str = "") -> str:
    return f"""{PERSONA}
{pantry_block(pantry, today)}

{shopping_block(shopping)}
{notes_block(notes)}

Talk with the user about what to cook, taking their mood, cravings, energy, and time into account.
- Build ideas around what they actually have, and lean on items that expire soon.
- Name pantry items the way they appear above, and only mention items that are listed. Never claim they \
have something that is not in the pantry; you may assume {STAPLES}. When an idea needs something they \
lack, say so and suggest adding it to the shopping list.
- Never suggest eating an item marked EXPIRED; gently suggest tossing it instead.
- Keep replies short and conversational: two to five sentences, or a brief list of ideas. Plain text \
only, no headings or tables."""
