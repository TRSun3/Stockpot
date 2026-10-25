"""The Gemini backend, against a stand-in client: what it sends, what it accepts, and how it fails."""

from types import SimpleNamespace

import pytest
from conftest import TODAY
from google.genai import errors

from stockpot import config
from stockpot.llm import LLMBusy, LLMError, get_llm
from stockpot.llm.gemini import Gemini
from stockpot.llm.mock import Mock
from stockpot.schemas import ChatTurn, PantryItem, ParsedItems, Recipes

PANTRY = [PantryItem(id=41, name="Spinach", description="a bag", expires_on="2026-10-25")]


class Models:
    """Records each request and answers with whatever the test queued."""

    def __init__(self, answer=None, chunks=(), error=None):
        self.answer, self.chunks, self.error, self.requests = answer, chunks, error, []

    def generate_content(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.answer

    def generate_content_stream(self, **request):
        self.requests.append(request)
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield SimpleNamespace(text=chunk)


class Blocked:
    """An answer withheld by a safety filter: no parsed value, and reading its text fails."""

    parsed = None

    @property
    def text(self):
        raise ValueError("no candidates")


def gemini(**answers):
    models = Models(**answers)
    return Gemini("key", "gemini-test", client=SimpleNamespace(models=models)), models


def test_structured_answers_use_the_schema_and_carry_today_and_the_pantry():
    parsed = Recipes(recipes=[])
    llm, models = gemini(answer=SimpleNamespace(parsed=parsed, text=""))
    assert llm.suggest_recipes(PANTRY, TODAY, "cozy") == []
    request = models.requests[0]
    assert request["model"] == "gemini-test"
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].response_schema is Recipes
    system = request["config"].system_instruction
    assert "2026-10-24" in system and "[41] Spinach" in system and "expires in 1 day" in system
    assert "cozy" in request["contents"]


def test_an_answer_the_sdk_did_not_parse_is_read_from_its_text():
    text = '{"items": [{"name": "Milk", "description": "", "expires_on": null}]}'
    llm, _ = gemini(answer=SimpleNamespace(parsed=None, text=text))
    assert llm.parse_items("milk", TODAY) == ParsedItems.model_validate_json(text).items


@pytest.mark.parametrize(
    "answers",
    [
        {"answer": SimpleNamespace(parsed=None, text="not json")},
        {"answer": Blocked()},
        {"error": errors.APIError(503, {"error": {"message": "overloaded", "status": "UNAVAILABLE"}})},
        {"error": TimeoutError()},
    ],
)
def test_bad_answers_and_failed_requests_become_llm_errors(answers):
    llm, _ = gemini(**answers)
    with pytest.raises(LLMError):
        llm.parse_items("milk", TODAY)


def test_chat_streams_each_chunk_and_maps_the_history_onto_gemini_roles():
    llm, models = gemini(chunks=["Try ", "", "an omelette."])
    history = [ChatTurn(role="user", content="hi"), ChatTurn(role="assistant", content="hello!")]
    assert list(llm.chat(history, "I'm tired", PANTRY, [], TODAY)) == ["Try ", "an omelette."]
    contents = models.requests[0]["contents"]
    assert [(c.role, c.parts[0].text) for c in contents] == [("user", "hi"), ("model", "hello!"), ("user", "I'm tired")]


def test_a_chat_that_fails_midway_raises_an_llm_error():
    llm, _ = gemini(chunks=["Try ", ConnectionError()])
    with pytest.raises(LLMError):
        list(llm.chat([], "hi", PANTRY, [], TODAY))


def test_the_backend_is_gemini_only_with_a_key():
    base = config.Settings(db_path=TODAY, llm="gemini", gemini_api_key="", gemini_model="m")
    assert isinstance(get_llm(base), Mock)
    assert isinstance(get_llm(base.__class__(**{**base.__dict__, "gemini_api_key": "k"})), Gemini)


def test_a_rate_limit_is_reported_as_busy_so_the_user_knows_to_wait():
    limited = errors.APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})
    llm, _ = gemini(error=limited)
    with pytest.raises(LLMBusy):
        llm.parse_items("milk", TODAY)
    llm, _ = gemini(chunks=[limited])
    with pytest.raises(LLMBusy):
        list(llm.chat([], "hi", PANTRY, [], TODAY))
