"""Changing the kitchen in plain words: groceries typed as a sentence, pantry adjustments, and unpacking the
shopping bags. The LLM proposes; `guard` decides what actually changes."""

from datetime import date

from fastapi import APIRouter, HTTPException

from stockpot import db, guard, pantry, shopping
from stockpot.auth import Conn, CurrentUser
from stockpot.deps import Model, Today
from stockpot.schemas import TextIn

router = APIRouter(prefix="/api")


@router.post("/items/parse", status_code=201)
def add_from_text(body: TextIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> list[dict]:
    """Adds every grocery described in `text`, each with an estimated expiry."""
    parsed = guard.clean_parsed(llm.parse_items(body.text, today), today)
    if not parsed:
        raise HTTPException(422, 'I couldn\'t find any groceries in that. Try something like "milk and a dozen eggs".')
    with db.transaction(conn):
        ids = [pantry.insert(conn, user.id, *item) for item in parsed]
    return [pantry.to_json(pantry.row(conn, user.id, item_id), today) for item_id in ids]


@router.post("/items/adjust")
def adjust_from_text(body: TextIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Changes the pantry to match an instruction like "I used half the milk and the eggs are gone"."""
    ops = llm.adjust_pantry(body.text, pantry.for_llm(conn, user.id), today)
    return guard.apply_ops(conn, user.id, ops, today, allow_add=True)


def matching(name: str, parsed: list[tuple[str, str, date | None]], taken: set[int]) -> int | None:
    """The parsed item that corresponds to a shopping entry's name, if one is left."""
    lowered = name.lower()
    for index, (parsed_name, _, _) in enumerate(parsed):
        other = parsed_name.lower()
        if index not in taken and (other in lowered or lowered in other):
            return index
    return None


@router.post("/shopping/move-to-pantry")
def move_to_pantry(user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Moves every checked entry into the pantry under its own name and note, with the LLM estimating expiry.

    An entry the LLM skips still moves, just without an expiry. The checked entries are claimed inside the
    transaction, so a double submit can't add them twice.
    """
    checked = [entry for entry in shopping.rows(conn, user.id) if entry["checked"]]
    if not checked:
        raise HTTPException(400, "Check off what you bought first.")
    names = "\n".join(entry["name"] for entry in checked)
    parsed = guard.clean_parsed(llm.parse_items(names, today), today)
    taken: set[int] = set()
    ids = []
    with db.transaction(conn):
        for entry in checked:
            claimed = conn.execute(
                "DELETE FROM shopping_items WHERE id = ? AND user_id = ? AND checked = 1", (entry["id"], user.id)
            ).rowcount
            if not claimed:
                continue
            index = matching(entry["name"], parsed, taken)
            expires_on, description = None, entry["note"]
            if index is not None:
                taken.add(index)
                expires_on = parsed[index][2]
                description = description or parsed[index][1]
            ids.append(pantry.insert(conn, user.id, entry["name"], description, expires_on))
    if not ids:
        raise HTTPException(409, "Those were already moved into your pantry.")
    return {"moved": [pantry.to_json(pantry.row(conn, user.id, item_id), today) for item_id in ids]}
