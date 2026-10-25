"""The mood chat: the user talks about what they feel like, and the reply streams back built on their kitchen."""

import json
import logging
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from stockpot import db, pantry, preferences, shopping
from stockpot.auth import Conn, CurrentUser
from stockpot.deps import Model, Today
from stockpot.llm import UNAVAILABLE, LLMError
from stockpot.schemas import ChatIn, ChatTurn, ShoppingEntry

HISTORY = 20

router = APIRouter(prefix="/api/chat")

log = logging.getLogger("uvicorn.error")


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

    Both messages are saved together once the reply ends, including a reply cut off partway. If the LLM
    never says anything, neither is saved, so a retry doesn't repeat the question.
    """
    turns = [ChatTurn(role=row["role"], content=row["content"]) for row in messages(conn, user.id, HISTORY)]
    kitchen = pantry.for_llm(conn, user.id)
    entries = [
        ShoppingEntry(name=row["name"], note=row["note"], checked=bool(row["checked"]))
        for row in shopping.rows(conn, user.id)
    ]
    notes = preferences.notes(conn, user.id)
    pool = request.app.state.pool

    def stream() -> Iterator[str]:
        pieces: list[str] = []
        try:
            try:
                for piece in llm.chat(turns, body.message, kitchen, entries, today, notes):
                    pieces.append(piece)
                    yield event({"type": "text", "text": piece})
            except LLMError as error:
                yield event({"type": "error", "error": error.friendly})
            except Exception:
                log.exception("Chat reply failed")
                yield event({"type": "error", "error": UNAVAILABLE})
        finally:
            reply = "".join(pieces).strip()
            if reply:
                try:
                    with pool.connection() as writer, db.transaction(writer):
                        writer.executemany(
                            "INSERT INTO chat_messages (user_id, role, content) VALUES (?, ?, ?)",
                            [(user.id, "user", body.message), (user.id, "assistant", reply)],
                        )
                except sqlite3.Error:
                    log.exception("Saving the chat failed")
        yield event({"type": "done"})

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@router.delete("")
def clear(user: CurrentUser, conn: Conn) -> dict:
    conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user.id,))
    return {"ok": True}
