"""The mood chat streams its reply, remembers the conversation per account, and fails gracefully."""

import json

import pytest

from stockpot.llm import LLMError
from stockpot.llm.mock import Mock


class Stalling(Mock):
    """Says a little, then fails."""

    def __init__(self, before=(), error=None):
        super().__init__(delay=0)
        self.before = before
        self.error = error or LLMError("timed out")

    def chat(self, history, message, pantry, shopping, today, notes=""):
        yield from self.before
        raise self.error


class Recording(Mock):
    def __init__(self):
        super().__init__(delay=0)
        self.calls = []

    def chat(self, history, message, pantry, shopping, today, notes=""):
        self.calls.append((history, message, pantry, shopping, notes))
        yield "Noted."


def events(response):
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_a_reply_streams_in_pieces_built_on_the_pantry_and_both_messages_are_kept(neal):
    neal.post("/api/items", json={"name": "Spinach", "description": "a bag", "expires_on": "2026-10-25"})
    neal.post("/api/items", json={"name": "Eggs", "description": "6 eggs", "expires_on": "2026-11-10"})
    response = neal.post("/api/chat", json={"message": "Long day, I want something warm and comforting"})
    assert response.headers["content-type"].startswith("text/event-stream")
    stream = events(response)
    texts = [event["text"] for event in stream if event["type"] == "text"]
    assert len(texts) > 5 and stream[-1] == {"type": "done"}
    reply = "".join(texts)
    assert "spinach" in reply.lower()
    history = neal.get("/api/chat").json()
    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "Long day, I want something warm and comforting"),
        ("assistant", reply),
    ]


def test_the_llm_sees_the_history_pantry_shopping_list_and_notes(app, neal):
    app.state.llm = recording = Recording()
    neal.post("/api/items", json={"name": "Spinach"})
    neal.post("/api/shopping", json={"name": "Lemons", "note": "two"})
    neal.put("/api/preferences", json={"notes": "no oven"})
    neal.post("/api/chat", json={"message": "first"})
    neal.post("/api/chat", json={"message": "second"})
    history, message, pantry, shopping, notes = recording.calls[-1]
    assert [(turn.role, turn.content) for turn in history] == [("user", "first"), ("assistant", "Noted.")]
    assert message == "second"
    assert [item.name for item in pantry] == ["Spinach"]
    assert [(entry.name, entry.note) for entry in shopping] == [("Lemons", "two")]
    assert notes == "no oven"


def test_a_failed_reply_streams_an_error_and_leaves_no_half_conversation(app, neal):
    app.state.llm = Stalling()
    stream = events(neal.post("/api/chat", json={"message": "hello?"}))
    assert [event["type"] for event in stream] == ["error", "done"]
    assert "try again" in stream[0]["error"]
    assert neal.get("/api/chat").json() == []


@pytest.mark.parametrize("error", [LLMError("timed out"), RuntimeError("a bug")])
def test_a_reply_cut_off_partway_by_any_failure_keeps_what_was_said_and_ends_cleanly(app, neal, error):
    app.state.llm = Stalling(before=["Try ", "an omelette"], error=error)
    stream = events(neal.post("/api/chat", json={"message": "ideas?"}))
    assert [event["type"] for event in stream] == ["text", "text", "error", "done"]
    assert "try again" in stream[2]["error"]
    assert [m["content"] for m in neal.get("/api/chat").json()] == ["ideas?", "Try an omelette"]


def test_each_account_has_its_own_conversation_and_can_clear_it(neal, tianyue):
    neal.post("/api/chat", json={"message": "hi"})
    assert tianyue.get("/api/chat").json() == []
    tianyue.post("/api/chat", json={"message": "hello"})
    assert neal.delete("/api/chat").status_code == 200
    assert neal.get("/api/chat").json() == []
    assert len(tianyue.get("/api/chat").json()) == 2


def test_an_empty_message_is_refused(neal):
    assert neal.post("/api/chat", json={"message": "   "}).status_code == 422
