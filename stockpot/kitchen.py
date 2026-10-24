"""Changing the kitchen in plain words: groceries typed as a sentence, pantry adjustments, and unpacking the
shopping bags. The LLM proposes; `guard` decides what actually changes."""

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


@router.post("/shopping/move-to-pantry")
def move_to_pantry(user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Moves every checked entry into the pantry, letting the LLM estimate each expiry."""
    checked = [entry for entry in shopping.rows(conn, user.id) if entry["checked"]]
    if not checked:
        raise HTTPException(400, "Check off what you bought first.")
    text = "\n".join(f"{entry['name']} ({entry['note']})" if entry["note"] else entry["name"] for entry in checked)
    parsed = guard.clean_parsed(llm.parse_items(text, today), today)
    if not parsed:
        parsed = [(entry["name"], entry["note"], None) for entry in checked]
    with db.transaction(conn):
        ids = [pantry.insert(conn, user.id, *item) for item in parsed]
        conn.executemany(
            "DELETE FROM shopping_items WHERE id = ? AND user_id = ?", [(entry["id"], user.id) for entry in checked]
        )
    return {"moved": [pantry.to_json(pantry.row(conn, user.id, item_id), today) for item_id in ids]}
