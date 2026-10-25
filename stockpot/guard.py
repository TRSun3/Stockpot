"""Nothing the LLM says reaches the database unchecked. This module checks it, trims it, and applies it."""

import sqlite3
from datetime import date, timedelta

from stockpot import db, pantry
from stockpot.schemas import PantryOp, ParsedItem, Recipe, RecipeUse

OLDEST_DAYS = 30
FURTHEST_DAYS = 5 * 365
MOST_ITEMS = 50


def clean_date(value: str | None, today: date) -> date | None:
    """An ISO date within a believable window around today, or None for anything else."""
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value.strip())
    except ValueError:
        return None
    if not today - timedelta(days=OLDEST_DAYS) <= parsed <= today + timedelta(days=FURTHEST_DAYS):
        return None
    return parsed


def clean_text(value: str | None, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def clean_parsed(items: list[ParsedItem], today: date) -> list[tuple[str, str, date | None]]:
    """Parsed groceries as (name, description, expiry), dropping nameless ones and implausible dates."""
    cleaned = []
    for item in items[:MOST_ITEMS]:
        name = clean_text(item.name, 80)
        if name:
            cleaned.append(
                (name[:1].upper() + name[1:], clean_text(item.description, 500), clean_date(item.expires_on, today))
            )
    return cleaned


def clean_recipe(recipe: Recipe, items: dict[int, sqlite3.Row]) -> Recipe | None:
    """The recipe with every `uses` entry tied to a real item of this user's, or None if it is unusable.

    A use that names an item the user doesn't have becomes a missing ingredient instead.
    """
    title = clean_text(recipe.title, 120)
    steps = [text for step in recipe.steps[:20] if (text := clean_text(step, 500))]
    if not title or not steps:
        return None
    uses, missing, seen = [], [clean_text(name, 80) for name in recipe.missing[:20]], set()
    for use in recipe.uses[:30]:
        item = items.get(use.item_id)
        if item is None:
            if name := clean_text(use.name, 80):
                missing.append(name)
        elif use.item_id not in seen:
            seen.add(use.item_id)
            uses.append(RecipeUse(item_id=use.item_id, name=item["name"], amount=clean_text(use.amount, 80)))
    return Recipe(
        title=title,
        summary=clean_text(recipe.summary, 300),
        time_minutes=min(max(int(recipe.time_minutes), 1), 600),
        uses=uses,
        missing=list(dict.fromkeys(name for name in missing if name)),
        steps=steps,
        why=clean_text(recipe.why, 300),
    )


def check(op: PantryOp, owned: set[int], allowed: set[int] | None, allow_add: bool, today: date) -> str | None:
    """Why an op must be refused, or None when it is safe to apply."""
    if op.op == "add":
        if not allow_add:
            return "adding items isn't allowed here"
        return None if clean_text(op.name, 80) else "an added item needs a name"
    if op.item_id is None or op.item_id not in owned:
        return "no such item in this pantry"
    if allowed is not None and op.item_id not in allowed:
        return "that item isn't part of this change"
    if op.op == "update" and not clean_text(op.description, 500) and clean_date(op.expires_on, today) is None:
        return "an update needs a new description"
    return None


def describe(op: PantryOp) -> dict:
    return op.model_dump(exclude_none=True)


def apply_ops(
    conn: sqlite3.Connection,
    user_id: int,
    ops: list[PantryOp],
    today: date,
    *,
    allowed: set[int] | None = None,
    allow_add: bool = False,
) -> dict:
    """Applies every valid op in one transaction and reports each refused one with its reason.

    An op is refused when it names an item the user doesn't own, an item outside `allowed`, an item
    an earlier op already changed, or when it is malformed. Refused ops never stop the valid ones.
    """
    changes, rejected = [], []
    with db.transaction(conn):
        owned = {row["id"]: row for row in pantry.rows(conn, user_id)}
        owned_ids = set(owned)
        foods = {pantry.food_key(row["name"]) for row in owned.values()}
        touched: set[int] = set()
        for op in ops[:MOST_ITEMS]:
            reason = check(op, owned_ids, allowed, allow_add, today)
            if reason is None and op.item_id in touched:
                reason = "that item was already changed"
            if reason is None and op.op == "add" and pantry.food_key(clean_text(op.name, 80)) in foods:
                reason = "that's already in the pantry, so it should be updated instead"
            if reason:
                rejected.append({"op": describe(op), "reason": reason})
                continue
            if op.op == "add":
                name = clean_text(op.name, 80)
                name = name[:1].upper() + name[1:]
                description = clean_text(op.description, 500)
                item_id = pantry.insert(conn, user_id, name, description, clean_date(op.expires_on, today))
                foods.add(pantry.food_key(name))
                changes.append({"action": "added", "item_id": item_id, "name": name, "description": description})
                continue
            touched.add(op.item_id)
            item = owned[op.item_id]
            if op.op == "delete":
                pantry.delete(conn, user_id, op.item_id)
                foods.discard(pantry.food_key(item["name"]))
                changes.append({"action": "removed", "item_id": op.item_id, "name": item["name"]})
                continue
            update = {}
            if description := clean_text(op.description, 500):
                update["description"] = description
            if expires_on := clean_date(op.expires_on, today):
                update["expires_on"] = expires_on
            pantry.update(conn, user_id, op.item_id, update)
            changes.append(
                {
                    "action": "updated",
                    "item_id": op.item_id,
                    "name": item["name"],
                    "description": update.get("description", item["description"]),
                }
            )
    return {"changes": changes, "rejected": rejected}
