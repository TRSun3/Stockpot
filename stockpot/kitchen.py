"""Changing the kitchen in plain words: groceries typed as a sentence, pantry adjustments, and unpacking the
shopping bags. The LLM proposes; `guard` decides what actually changes.

Anything added under the name of something already in the pantry is folded into that item rather than added
twice."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from fastapi import APIRouter, HTTPException

from stockpot import db, guard, pantry, shopping
from stockpot.auth import Conn, CurrentUser
from stockpot.deps import Model, Today
from stockpot.llm import LLM, LLMError
from stockpot.schemas import ItemIn, TextIn

router = APIRouter(prefix="/api")

log = logging.getLogger("uvicorn.error")

# A grocery to add: (name, description, expiry).
Grocery = tuple[str, str, date | None]


@dataclass
class Addition:
    """What adding groceries does to one food: a new item, or an existing one (`item_id`) folded into.

    `description` and `expires_on` are the result. For an existing item, `had` and `had_expiry` are what it
    said when the plan was made, and `bought` and `bought_expiry` are what was added, so the plan can be
    redone if the item changes before it is applied.
    """

    item_id: int | None
    name: str
    description: str
    expires_on: date | None
    had: str = ""
    had_expiry: date | None = None
    bought: list[str] = field(default_factory=list)
    bought_expiry: date | None = None


def expiry_of(row: sqlite3.Row) -> date | None:
    return date.fromisoformat(row["expires_on"]) if row["expires_on"] else None


def sooner(first: date | None, second: date | None) -> date | None:
    """The earlier of two expiry dates, where None means no expiry."""
    dates = [value for value in (first, second) if value]
    return min(dates) if dates else None


def joined(*descriptions: str) -> str:
    return ", plus ".join(text for text in descriptions if text)


def merged_descriptions(llm: LLM, rows: list[sqlite3.Row], bought: dict[int, list[str]], today: date) -> dict[int, str]:
    """Each existing item's description rewritten by the LLM to cover what was there plus what was bought.

    Uses `adjust_pantry`, the same call as a plain-words update. If the LLM fails or skips an item, its
    descriptions are joined instead, so nothing anyone wrote is lost.
    """
    lines = "\n".join(
        f"- {row['name']}: {', '.join(text for text in bought[row['id']] if text) or 'some more'}" for row in rows
    )
    instruction = (
        "I just bought more of these, which are already in my pantry. Rewrite each one's description so it "
        "covers what I had and what I bought, adding the amounts up where you can (6 plus a dozen is 18). "
        f"Don't change any expiry.\n{lines}"
    )
    try:
        ops = llm.adjust_pantry(instruction, pantry.as_llm(rows), today)
    except LLMError as error:
        log.warning("Merging descriptions fell back to joining them: %s", error)
        ops = []
    except Exception:
        log.exception("Merging descriptions failed; joining them instead")
        ops = []
    rewritten: dict[int, str] = {}
    for op in ops:
        if op.op == "update" and op.item_id in bought and op.item_id not in rewritten:
            if text := guard.clean_text(op.description, 500):
                rewritten[op.item_id] = text
    for row in rows:
        rewritten.setdefault(row["id"], joined(row["description"], *bought[row["id"]]))
    return rewritten


def plan_additions(
    conn: sqlite3.Connection, user_id: int, groceries: list[Grocery], today: date, llm: LLM
) -> list[Addition]:
    """What adding these groceries does, without changing anything yet.

    A grocery already in the pantry folds into that item, keeping the sooner expiry. Several of one new food
    become a single new item. The LLM is only asked when something folds into an existing item.
    """
    owned = {pantry.food_key(row["name"]): row for row in pantry.rows(conn, user_id)}
    planned: dict[str, Addition] = {}
    for name, description, expires_on in groceries:
        key = pantry.food_key(name)
        if (entry := planned.get(key)) is not None:
            if entry.item_id is None:
                entry.description = joined(entry.description, description)
            else:
                entry.bought.append(description)
                entry.bought_expiry = sooner(entry.bought_expiry, expires_on)
            entry.expires_on = sooner(entry.expires_on, expires_on)
        elif (row := owned.get(key)) is not None:
            planned[key] = Addition(
                row["id"],
                row["name"],
                row["description"],
                sooner(expiry_of(row), expires_on),
                had=row["description"],
                had_expiry=expiry_of(row),
                bought=[description],
                bought_expiry=expires_on,
            )
        else:
            planned[key] = Addition(None, name, description, expires_on)
    bought = {entry.item_id: entry.bought for entry in planned.values() if entry.item_id is not None}
    if bought:
        rows = [row for row in owned.values() if row["id"] in bought]
        rewritten = merged_descriptions(llm, rows, bought, today)
        for entry in planned.values():
            if entry.item_id in rewritten:
                entry.description = rewritten[entry.item_id]
    return list(planned.values())


def apply_additions(conn: sqlite3.Connection, user_id: int, additions: list[Addition]) -> list[int]:
    """Inserts the new items and updates the existing ones; returns the id of every item touched, in order.

    Runs inside the caller's transaction, after the LLM has answered, and checks the pantry again first. An item
    edited since the plan was made keeps that edit, with what was bought joined on. A food that another request
    added meanwhile is joined the same way rather than added twice, and an item removed since comes back as just
    what was bought.
    """
    foods = {pantry.food_key(row["name"]): row for row in pantry.rows(conn, user_id)}
    ids = []
    for entry in additions:
        current = pantry.row(conn, user_id, entry.item_id) if entry.item_id is not None else None
        if current is not None and (current["description"], expiry_of(current)) == (entry.had, entry.had_expiry):
            description, expires_on = entry.description, entry.expires_on
        else:
            # What this request brought, joined onto whatever the pantry holds for the food right now.
            brought = entry.bought if entry.item_id is not None else [entry.description]
            brought_expiry = entry.bought_expiry if entry.item_id is not None else entry.expires_on
            current = current or foods.get(pantry.food_key(entry.name))
            if current is None:
                item_id = pantry.insert(conn, user_id, entry.name, joined(*brought), brought_expiry)
                foods[pantry.food_key(entry.name)] = pantry.row(conn, user_id, item_id)
                ids.append(item_id)
                continue
            description = joined(current["description"], *brought)
            expires_on = sooner(expiry_of(current), brought_expiry)
        pantry.update(conn, user_id, current["id"], {"description": description, "expires_on": expires_on})
        ids.append(current["id"])
    return ids


def added(conn: sqlite3.Connection, user_id: int, ids: list[int], today: date) -> list[dict]:
    """The items as they are now, skipping any another request removed in the meantime."""
    rows = [pantry.row(conn, user_id, item_id) for item_id in ids]
    return [pantry.to_json(row, today) for row in rows if row is not None]


@router.post("/items", status_code=201)
def add_item(body: ItemIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Adds one item by hand, or folds it into the item of the same name already in the pantry."""
    additions = plan_additions(conn, user.id, [(body.name, body.description, body.expires_on)], today, llm)
    with db.transaction(conn):
        ids = apply_additions(conn, user.id, additions)
    return pantry.to_json(pantry.found(conn, user.id, ids[0]), today)


@router.post("/items/parse", status_code=201)
def add_from_text(body: TextIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> list[dict]:
    """Adds every grocery described in `text`, each with an estimated expiry."""
    parsed = guard.clean_parsed(llm.parse_items(body.text, today), today)
    if not parsed:
        raise HTTPException(422, 'I couldn\'t find any groceries in that. Try something like "milk and a dozen eggs".')
    additions = plan_additions(conn, user.id, parsed, today, llm)
    with db.transaction(conn):
        ids = apply_additions(conn, user.id, additions)
    return added(conn, user.id, ids, today)


@router.post("/items/adjust")
def adjust_from_text(body: TextIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Changes the pantry to match an instruction like "I used half the milk and the eggs are gone"."""
    ops = llm.adjust_pantry(body.text, pantry.for_llm(conn, user.id), today)
    return guard.apply_ops(conn, user.id, ops, today, allow_add=True)


def matching(name: str, parsed: list[Grocery], taken: set[int]) -> int | None:
    """The parsed item that corresponds to a shopping entry's name, if one is left: the same food if there is
    one, otherwise one whose name contains the other ("Lemons" and "Organic lemons")."""
    left = [index for index in range(len(parsed)) if index not in taken]
    key = pantry.food_key(name)
    for index in left:
        if pantry.food_key(parsed[index][0]) == key:
            return index
    lowered = name.lower()
    for index in left:
        other = parsed[index][0].lower()
        if other in lowered or lowered in other:
            return index
    return None


@router.post("/shopping/move-to-pantry")
def move_to_pantry(user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Moves every checked entry into the pantry under its own name and note, with the LLM estimating expiry.

    An entry the LLM skips still moves, just without an expiry. The checked entries are claimed inside the
    transaction, so a double submit can't add them twice, and a list that changed meanwhile moves nothing.
    """
    checked = [entry for entry in shopping.rows(conn, user.id) if entry["checked"]]
    if not checked:
        raise HTTPException(400, "Check off what you bought first.")
    names = "\n".join(entry["name"] for entry in checked)
    parsed = guard.clean_parsed(llm.parse_items(names, today), today)
    taken: set[int] = set()
    groceries = []
    for entry in checked:
        index = matching(entry["name"], parsed, taken)
        expires_on, description = None, entry["note"]
        if index is not None:
            taken.add(index)
            expires_on = parsed[index][2]
            description = description or parsed[index][1]
        groceries.append((entry["name"], description, expires_on))
    additions = plan_additions(conn, user.id, groceries, today, llm)
    with db.transaction(conn):
        claimed = sum(
            conn.execute(
                "DELETE FROM shopping_items WHERE id = ? AND user_id = ? AND checked = 1", (entry["id"], user.id)
            ).rowcount
            for entry in checked
        )
        if claimed == 0:
            raise HTTPException(409, "Those were already moved into your pantry.")
        if claimed != len(checked):
            raise HTTPException(409, "Your shopping list changed while moving. Please try again.")
        ids = apply_additions(conn, user.id, additions)
    return {"moved": added(conn, user.id, ids, today)}
