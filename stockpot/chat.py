"""The mood chat: the user talks about what they feel like, and the reply streams back built on their kitchen."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stockpot import db, pantry, preferences, shopping
from stockpot.auth import Conn, CurrentUser
from stockpot.deps import Model, Today
from stockpot.llm import UNAVAILABLE, LLMError
from stockpot.schemas import ChatIn, ChatTurn, ShoppingEntry

HISTORY = 20

router = APIRouter(prefix="/api/chat")


def messages(conn: sqlite3.Connection, user_id: int, limit: int = 200) -> list[sqlite3.Row]:
    """The user's most recent messages, oldest first."""
    rows = conn.execute(
        "SELECT id, role, content, created_at FROM chat_messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return rows[::-1]


def event(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


@router.get("")
def history(user: CurrentUser, conn: Conn) -> list[dict]:
    return [dict(row) for row in messages(conn, user.id)]


@router.post("")
def send(body: ChatIn, request: Request, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> StreamingResponse:
    """Streams the reply as server-sent events: `text` pieces, then `done`, or an `error`.

    Both messages are saved once the reply finishes. If the LLM fails before saying anything, the user's
    message is removed again so a retry doesn't repeat it.
    """
    turns = [ChatTurn(role=row["role"], content=row["content"]) for row in messages(conn, user.id, HISTORY)]
    kitchen = pantry.for_llm(conn, user.id)
    entries = [
        ShoppingEntry(name=row["name"], note=row["note"], checked=bool(row["checked"]))
        for row in shopping.rows(conn, user.id)
    ]
    notes = preferences.notes(conn, user.id)
    asked = conn.execute(
        "INSERT INTO chat_messages (user_id, role, content) VALUES (?, 'user', ?)", (user.id, body.message)
    ).lastrowid
    db_path = request.app.state.settings.db_path

    def stream() -> Iterator[str]:
        pieces: list[str] = []
        try:
            try:
                for piece in llm.chat(turns, body.message, kitchen, entries, today, notes):
                    pieces.append(piece)
                    yield event({"type": "text", "text": piece})
            except LLMError:
                yield event({"type": "error", "error": UNAVAILABLE})
        finally:
            reply = "".join(pieces).strip()
            with closing(db.connect(db_path)) as writer:
                if reply:
                    writer.execute(
                        "INSERT INTO chat_messages (user_id, role, content) VALUES (?, 'assistant', ?)",
                        (user.id, reply),
                    )
                else:
                    writer.execute("DELETE FROM chat_messages WHERE id = ? AND user_id = ?", (asked, user.id))
        yield event({"type": "done"})

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.delete("")
def clear(user: CurrentUser, conn: Conn) -> dict:
    conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user.id,))
    return {"ok": True}
