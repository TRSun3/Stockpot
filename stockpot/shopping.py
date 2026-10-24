"""The shopping list: things to buy, checked off in the store, then moved into the pantry."""

import sqlite3

from fastapi import APIRouter, HTTPException

from stockpot.auth import Conn, CurrentUser
from stockpot.schemas import ShoppingIn, ShoppingPatch

router = APIRouter(prefix="/api/shopping")

COLUMNS = "id, name, note, checked"


def to_json(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "name": row["name"], "note": row["note"], "checked": bool(row["checked"])}


def rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """The user's list, unchecked entries first, each group in the order it was added."""
    return conn.execute(
        f"SELECT {COLUMNS} FROM shopping_items WHERE user_id = ? ORDER BY checked, id", (user_id,)
    ).fetchall()


def row(conn: sqlite3.Connection, user_id: int, entry_id: int) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT {COLUMNS} FROM shopping_items WHERE id = ? AND user_id = ?", (entry_id, user_id)
    ).fetchone()


def insert(conn: sqlite3.Connection, user_id: int, name: str, note: str = "") -> int:
    cursor = conn.execute("INSERT INTO shopping_items (user_id, name, note) VALUES (?, ?, ?)", (user_id, name, note))
    return cursor.lastrowid


def found(conn: sqlite3.Connection, user_id: int, entry_id: int) -> sqlite3.Row:
    entry = row(conn, user_id, entry_id)
    if entry is None:
        raise HTTPException(404, "That isn't on your shopping list.")
    return entry


@router.get("")
def list_entries(user: CurrentUser, conn: Conn) -> list[dict]:
    return [to_json(entry) for entry in rows(conn, user.id)]


@router.post("", status_code=201)
def add_entry(body: ShoppingIn, user: CurrentUser, conn: Conn) -> dict:
    return to_json(row(conn, user.id, insert(conn, user.id, body.name, body.note)))


@router.patch("/{entry_id}")
def edit_entry(entry_id: int, body: ShoppingPatch, user: CurrentUser, conn: Conn) -> dict:
    found(conn, user.id, entry_id)
    changes = body.changes()
    if changes:
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE shopping_items SET {assignments} WHERE id = ? AND user_id = ?",
            (*changes.values(), entry_id, user.id),
        )
    return to_json(row(conn, user.id, entry_id))


@router.delete("/{entry_id}")
def remove_entry(entry_id: int, user: CurrentUser, conn: Conn) -> dict:
    cursor = conn.execute("DELETE FROM shopping_items WHERE id = ? AND user_id = ?", (entry_id, user.id))
    if cursor.rowcount != 1:
        raise HTTPException(404, "That isn't on your shopping list.")
    return {"ok": True}
