"""Kitchen notes: one free-text description of the user's diet, allergies, equipment, and household, which
every recipe and chat prompt respects."""

import sqlite3

from fastapi import APIRouter

from stockpot.auth import Conn, CurrentUser
from stockpot.schemas import NotesIn

router = APIRouter(prefix="/api/preferences")


def notes(conn: sqlite3.Connection, user_id: int) -> str:
    row = conn.execute("SELECT notes FROM preferences WHERE user_id = ?", (user_id,)).fetchone()
    return row["notes"] if row else ""


@router.get("")
def get_notes(user: CurrentUser, conn: Conn) -> dict:
    return {"notes": notes(conn, user.id)}


@router.put("")
def set_notes(body: NotesIn, user: CurrentUser, conn: Conn) -> dict:
    conn.execute(
        "INSERT INTO preferences (user_id, notes) VALUES (?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET notes = excluded.notes, updated_at = datetime('now')",
        (user.id, body.notes),
    )
    return {"notes": body.notes}
