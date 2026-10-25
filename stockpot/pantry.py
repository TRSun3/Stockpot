"""The pantry: each item is a name, a free-text description, and an expiry date."""

import sqlite3
from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from stockpot.auth import Conn, CurrentUser
from stockpot.deps import RowId, Today
from stockpot.schemas import ItemPatch, PantryItem

SOON_DAYS = 3

router = APIRouter(prefix="/api/items")


def freshness(expires_on: date | None, today: date) -> tuple[str, int | None]:
    """How fresh an item is, and how many days it has left (negative once it has expired)."""
    if expires_on is None:
        return "none", None
    days = (expires_on - today).days
    if days < 0:
        return "expired", days
    if days == 0:
        return "today", 0
    return ("soon" if days <= SOON_DAYS else "fresh"), days


def to_json(row: sqlite3.Row, today: date) -> dict:
    expires_on = date.fromisoformat(row["expires_on"]) if row["expires_on"] else None
    status, days_left = freshness(expires_on, today)
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "expires_on": row["expires_on"],
        "status": status,
        "days_left": days_left,
        "updated_at": row["updated_at"],
    }


def singular(word: str) -> str:
    """A word's singular stem, the same for both forms: "peaches" and "peach", "cookies" and "cookie"."""
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "i"
    if word.endswith(("ches", "shes", "sses", "xes", "zes", "oes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    if word.endswith("ie") and len(word) > 3:
        return word[:-1]
    if word.endswith("che"):
        return word[:-1]
    if word.endswith("y") and len(word) > 2 and word[-2] not in "aeiou":
        return word[:-1] + "i"
    return word


def food_key(name: str) -> str:
    """The name reduced so the same food matches however it is written: "Eggs", "egg", and " EGGS " all match."""
    words = [word.strip(".,;:!?'\"()") for word in name.lower().split()]
    words = [word for word in words if word]
    if not words:
        return " ".join(name.lower().split())
    return " ".join([*words[:-1], singular(words[-1])])


COLUMNS = "id, name, description, expires_on, updated_at"
ORDER = "ORDER BY expires_on IS NULL, expires_on, name COLLATE NOCASE, id"


def rows(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    """The user's items, soonest to expire first and items without an expiry last."""
    return conn.execute(f"SELECT {COLUMNS} FROM items WHERE user_id = ? {ORDER}", (user_id,)).fetchall()


def as_llm(items: list[sqlite3.Row]) -> list[PantryItem]:
    return [
        PantryItem(id=item["id"], name=item["name"], description=item["description"], expires_on=item["expires_on"])
        for item in items
    ]


def for_llm(conn: sqlite3.Connection, user_id: int) -> list[PantryItem]:
    return as_llm(rows(conn, user_id))


def row(conn: sqlite3.Connection, user_id: int, item_id: int) -> sqlite3.Row | None:
    return conn.execute(f"SELECT {COLUMNS} FROM items WHERE id = ? AND user_id = ?", (item_id, user_id)).fetchone()


def insert(conn: sqlite3.Connection, user_id: int, name: str, description: str, expires_on: date | None) -> int:
    cursor = conn.execute(
        "INSERT INTO items (user_id, name, description, expires_on) VALUES (?, ?, ?, ?)",
        (user_id, name, description, expires_on.isoformat() if expires_on else None),
    )
    return cursor.lastrowid


def update(conn: sqlite3.Connection, user_id: int, item_id: int, changes: dict) -> bool:
    """Sets the given columns on one of the user's items. False when the user has no such item."""
    columns = {key: changes[key] for key in ("name", "description", "expires_on") if key in changes}
    if "expires_on" in columns and columns["expires_on"] is not None:
        columns["expires_on"] = columns["expires_on"].isoformat()
    assignments = ", ".join(f"{column} = ?" for column in columns)
    cursor = conn.execute(
        f"UPDATE items SET {assignments}{', ' if columns else ''}updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?",
        (*columns.values(), item_id, user_id),
    )
    return cursor.rowcount == 1


def delete(conn: sqlite3.Connection, user_id: int, item_id: int) -> bool:
    cursor = conn.execute("DELETE FROM items WHERE id = ? AND user_id = ?", (item_id, user_id))
    return cursor.rowcount == 1


def found(conn: sqlite3.Connection, user_id: int, item_id: int) -> sqlite3.Row:
    item = row(conn, user_id, item_id)
    if item is None:
        raise HTTPException(404, "That item isn't in your pantry.")
    return item


@router.get("")
def list_items(user: CurrentUser, conn: Conn, today: Today) -> list[dict]:
    return [to_json(item, today) for item in rows(conn, user.id)]


@router.get("/expiring")
def expiring(
    user: CurrentUser, conn: Conn, today: Today, days: Annotated[int, Query(ge=0, le=60)] = SOON_DAYS
) -> list[dict]:
    """Items expiring within `days`, including those already past their date."""
    items = [to_json(item, today) for item in rows(conn, user.id)]
    return [item for item in items if item["days_left"] is not None and item["days_left"] <= days]


@router.get("/{item_id}")
def get_item(item_id: RowId, user: CurrentUser, conn: Conn, today: Today) -> dict:
    return to_json(found(conn, user.id, item_id), today)


@router.patch("/{item_id}")
def edit_item(item_id: RowId, body: ItemPatch, user: CurrentUser, conn: Conn, today: Today) -> dict:
    """Changes only the fields sent. Renaming an item to a different food that is already in the pantry is
    refused, since each food is kept once; an item keeping its own food can always be edited."""
    current = found(conn, user.id, item_id)
    changes = body.changes()
    if "name" in changes and (key := food_key(changes["name"])) != food_key(current["name"]):
        for other in rows(conn, user.id):
            if other["id"] != item_id and food_key(other["name"]) == key:
                raise HTTPException(409, f"{other['name']} is already in your pantry. Edit that one instead.")
    if not update(conn, user.id, item_id, changes):
        raise HTTPException(404, "That item isn't in your pantry.")
    return to_json(found(conn, user.id, item_id), today)


@router.delete("/{item_id}")
def discard_item(item_id: RowId, user: CurrentUser, conn: Conn) -> dict:
    if not delete(conn, user.id, item_id):
        raise HTTPException(404, "That item isn't in your pantry.")
    return {"ok": True}
