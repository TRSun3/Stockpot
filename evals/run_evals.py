"""Runs every scenario in scenarios.json against an LLM backend and checks the raw answers programmatically.

    uv run python -m evals.run_evals                  # the backend .env selects
    uv run python -m evals.run_evals --backend gemini
    uv run python -m evals.run_evals --model gemini-3.5-flash-lite   # Gemini with another model
    uv run python -m evals.run_evals --only parse     # scenarios whose id contains "parse"

Scenarios marked `"stable": true` have passed on every backend tried; they are skipped unless `--all` is
given, to save time and free-tier quota. Prints a pass/fail table and a score, and exits non-zero when any
scenario fails.
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from stockpot import config
from stockpot.llm import LLM, LLMError
from stockpot.llm.gemini import Gemini
from stockpot.llm.mock import Mock
from stockpot.schemas import PantryItem, PantryOp, ParsedItem, Recipe

SCENARIOS = Path(__file__).with_name("scenarios.json")


def kitchen(rows: list[dict], today: date) -> list[PantryItem]:
    return [
        PantryItem(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            expires_on=None if row["days"] is None else (today + timedelta(days=row["days"])).isoformat(),
        )
        for row in rows
    ]


def ask(llm: LLM, scenario: dict, pantry: list[PantryItem], today: date):
    """Calls the scenario's method and returns its answer, with chat's stream joined into one string."""
    given = scenario["input"]
    match scenario["method"]:
        case "parse_items":
            text = given["repeat"] * given["times"] if "repeat" in given else given["text"]
            return llm.parse_items(text, today)
        case "suggest_recipes":
            return llm.suggest_recipes(pantry, today, given.get("preferences", ""), given.get("notes", ""))
        case "plan_recipe":
            return llm.plan_recipe(given["dish"], pantry, today, given.get("notes", ""))
        case "tweak_recipe":
            recipe = Recipe.model_validate(given["recipe"])
            return llm.tweak_recipe(recipe, given["feedback"], pantry, today, given.get("notes", ""))
        case "apply_cooking":
            return llm.apply_cooking(Recipe.model_validate(given["recipe"]), pantry, today)
        case "adjust_pantry":
            return llm.adjust_pantry(given["instruction"], pantry, today)
        case "chat":
            return "".join(llm.chat([], given["message"], pantry, [], today, given.get("notes", "")))
    raise ValueError(f"unknown method {scenario['method']}")


def recipes_of(answer) -> list[Recipe]:
    return answer if isinstance(answer, list) else [answer]


def days_until(value: str | None, today: date) -> int | None:
    return None if value is None else (date.fromisoformat(value) - today).days


def find(items: list[ParsedItem], word: str) -> ParsedItem | None:
    return next((item for item in items if word in item.name.lower()), None)


def op_for(ops: list[PantryOp], item_id: int) -> PantryOp | None:
    return next((op for op in ops if op.item_id == item_id), None)


# Each check takes (answer, its arguments, the scenario's context) and returns None to pass or a reason it failed.
Check = Callable[..., str | None]


def check_count(items, spec, ctx):
    if not spec["min"] <= len(items) <= spec["max"]:
        return f"{len(items)} items, expected {spec['min']} to {spec['max']}"


def check_names_include(items, spec, ctx):
    names = " | ".join(item.name.lower() for item in items)
    missing = [word for word in spec["words"] if word not in names]
    return f"no item named {missing} in {names}" if missing else None


def check_names_exclude(items, spec, ctx):
    bad = [item.name for item in items if any(word in item.name for word in spec["words"])]
    return f"names carry details: {bad}" if bad else None


def check_quantities_kept(items, spec, ctx):
    text = " | ".join(f"{item.name} {item.description}".lower() for item in items)
    lost = [word for word in spec["words"] if word not in text]
    return f"quantities lost: {lost}" if lost else None


def check_expiry_within(items, spec, ctx):
    item = find(items, spec["item"])
    if item is None:
        return f"no {spec['item']}"
    try:
        days = days_until(item.expires_on, ctx["today"])
    except ValueError:
        return f"{item.name} has an invalid date {item.expires_on!r}"
    if days is None or not spec["min"] <= days <= spec["max"]:
        return f"{item.name} expires in {days} days, expected {spec['min']} to {spec['max']}"


def check_long_or_no_expiry(items, spec, ctx):
    item = find(items, spec["item"])
    if item is None:
        return f"no {spec['item']}"
    days = days_until(item.expires_on, ctx["today"])
    if days is not None and days < spec["min"]:
        return f"{item.name} expires in {days} days; shelf-stable goods should keep {spec['min']}+"


def check_valid_items(items, spec, ctx):
    for item in items:
        if not item.name.strip():
            return "an item has no name"
        try:
            days_until(item.expires_on, ctx["today"])
        except ValueError:
            return f"{item.name} has an invalid date {item.expires_on!r}"


def check_recipe_count(answer, spec, ctx):
    count = len(recipes_of(answer))
    if not spec["min"] <= count <= spec["max"]:
        return f"{count} recipes, expected {spec['min']} to {spec['max']}"


def check_only_known_ids(answer, spec, ctx):
    known = {item.id for item in ctx["pantry"]}
    bad = [use.item_id for recipe in recipes_of(answer) for use in recipe.uses if use.item_id not in known]
    return f"uses unknown item ids {bad}" if bad else None


def check_some_recipe_uses(answer, spec, ctx):
    if not any(use.item_id == spec["item_id"] for recipe in recipes_of(answer) for use in recipe.uses):
        return f"no recipe uses item {spec['item_id']}"


def check_recipe_uses(answer, spec, ctx):
    used = {use.item_id for use in recipes_of(answer)[0].uses}
    missing = [item_id for item_id in spec["item_ids"] if item_id not in used]
    return f"doesn't use items {missing}" if missing else None


def check_never_uses(answer, spec, ctx):
    bad = [use.name for recipe in recipes_of(answer) for use in recipe.uses if use.item_id in spec["item_ids"]]
    return f"uses {bad}" if bad else None


def check_top_missing_at_most(answer, spec, ctx):
    for recipe in recipes_of(answer)[: spec["top"]]:
        if len(recipe.missing) > spec["max"]:
            return f"{recipe.title} is missing {len(recipe.missing)}: {recipe.missing}"


def check_recipes_complete(answer, spec, ctx):
    for recipe in recipes_of(answer):
        if not recipe.title.strip() or not recipe.steps or recipe.time_minutes <= 0:
            return f"incomplete recipe: {recipe.title!r}"


def check_first_recipe_minutes_at_most(answer, spec, ctx):
    recipes = recipes_of(answer)
    if recipes and recipes[0].time_minutes > spec["max"]:
        return f"{recipes[0].title} takes {recipes[0].time_minutes} minutes"


def check_title_contains(answer, spec, ctx):
    title = recipes_of(answer)[0].title.lower()
    if not any(word in title for word in spec["words"]):
        return f"title {title!r}"


def check_missing_includes(answer, spec, ctx):
    """Each word must appear in the missing list; "bacon|pancetta" accepts either."""
    missing = " | ".join(recipes_of(answer)[0].missing).lower()
    absent = [word for word in spec["words"] if not any(option in missing for option in word.split("|"))]
    return f"missing list {missing!r} lacks {absent}" if absent else None


def check_ops_only_recipe_items(ops, spec, ctx):
    allowed = {use["item_id"] for use in ctx["scenario"]["input"]["recipe"]["uses"]}
    bad = [op.item_id for op in ops if op.item_id not in allowed]
    return f"touches items outside the recipe: {bad}" if bad else None


def check_ops_only_items(ops, spec, ctx):
    bad = [op.item_id for op in ops if op.op != "add" and op.item_id not in spec["item_ids"]]
    return f"touches other items: {bad}" if bad else None


def check_ops_count(ops, spec, ctx):
    if not spec["min"] <= len(ops) <= spec["max"]:
        return f"{len(ops)} ops, expected {spec['min']} to {spec['max']}"


def check_no_adds(ops, spec, ctx):
    return "adds items" if any(op.op == "add" for op in ops) else None


def check_updates_have_descriptions(ops, spec, ctx):
    bad = [op.item_id for op in ops if op.op == "update" and not (op.description or "").strip()]
    return f"updates without a description: {bad}" if bad else None


def check_op_is(ops, spec, ctx):
    op = op_for(ops, spec["item_id"])
    if op is None or op.op != spec["op"]:
        return f"item {spec['item_id']}: expected {spec['op']}, got {op.op if op else 'nothing'}"
    lacking = [word for word in spec.get("description_has", []) if word not in (op.description or "")]
    return f"description {op.description!r} lacks {lacking}" if lacking else None


def check_op_expiry_at_least(ops, spec, ctx):
    op = op_for(ops, spec["item_id"])
    days = days_until(op.expires_on, ctx["today"]) if op and op.expires_on else None
    if days is None or days < spec["min"]:
        return f"item {spec['item_id']} now expires in {days} days"


def check_adds_include(ops, spec, ctx):
    added = " | ".join((op.name or "").lower() for op in ops if op.op == "add")
    missing = [word for word in spec["words"] if word not in added]
    return f"didn't add {missing} (added {added!r})" if missing else None


def check_reply_nonempty(reply, spec, ctx):
    return "empty reply" if not reply.strip() else None


def check_mentions_pantry_item(reply, spec, ctx):
    lowered = reply.lower()
    words = {word.rstrip("s") for item in ctx["pantry"] for word in item.name.lower().split() if len(word) > 3}
    return None if any(word in lowered for word in words) else "mentions nothing from the pantry"


def check_no_invented_items(reply, spec, ctx):
    claimed = [word for word in spec["words"] if word in reply.lower()]
    return f"claims the user has {claimed}" if claimed else None


def check_reply_words_at_most(reply, spec, ctx):
    count = len(reply.split())
    return f"{count} words" if count > spec["max"] else None


CHECKS: dict[str, Check] = {
    name.removeprefix("check_"): fn for name, fn in globals().items() if name.startswith("check_")
}


def run(llm: LLM, scenarios: list[dict], kitchens: dict, today: date) -> list[dict]:
    results = []
    for scenario in scenarios:
        pantry = kitchen(kitchens.get(scenario.get("kitchen", "empty"), []), today)
        ctx = {"today": today, "pantry": pantry, "scenario": scenario}
        started = time.perf_counter()
        failures = []
        try:
            answer = ask(llm, scenario, pantry, today)
        except (LLMError, ValueError) as error:
            failures.append(f"{type(error).__name__}: {error}")
        else:
            for spec in scenario["checks"]:
                try:
                    reason = CHECKS[spec["check"]](answer, spec, ctx)
                except Exception as error:  # noqa: BLE001 - a malformed answer fails the check, not the run
                    reason = f"{type(error).__name__}: {error}"
                if reason:
                    failures.append(f"{spec['check']}: {reason}")
        results.append({"id": scenario["id"], "seconds": time.perf_counter() - started, "failures": failures})
    return results


def report(results: list[dict], backend: str) -> int:
    width = max(len(result["id"]) for result in results)
    print(f"\nStockpot evals on the {backend} backend\n")
    print(f"{'scenario':<{width}}  result  seconds")
    for result in results:
        mark = "pass" if not result["failures"] else "FAIL"
        print(f"{result['id']:<{width}}  {mark:<6}  {result['seconds']:7.2f}")
        for failure in result["failures"]:
            print(f"{'':<{width}}    - {failure}")
    passed = sum(not result["failures"] for result in results)
    print(f"\nScore: {passed}/{len(results)} scenarios passed ({100 * passed / len(results):.0f}%)")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=["mock", "gemini"], help="defaults to the one .env selects")
    parser.add_argument("--only", default="", help="run only scenarios whose id contains this")
    parser.add_argument("--all", action="store_true", help="also run the scenarios marked stable")
    parser.add_argument("--model", help="a Gemini API model to use instead of GEMINI_MODEL; implies --backend gemini")
    args = parser.parse_args()
    settings = config.load()
    backend = "gemini" if args.model else args.backend or settings.backend
    model = args.model or settings.gemini_model
    if backend == "gemini":
        if not settings.gemini_api_key:
            sys.exit("GEMINI_API_KEY is not set in .env.")
        llm: LLM = Gemini(settings.gemini_api_key, model)
    else:
        llm = Mock(delay=0)
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = [
        scenario
        for scenario in data["scenarios"]
        if args.only in scenario["id"] and (args.all or not scenario.get("stable"))
    ]
    results = run(llm, scenarios, data["kitchens"], date.today())
    passed = report(results, backend if backend == "mock" else f"{backend} ({model})")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
