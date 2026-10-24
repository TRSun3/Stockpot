"""Google Gemini through the `google-genai` SDK: structured JSON for data, streaming for chat."""

import logging
from collections.abc import Iterator
from datetime import date

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from stockpot.llm import prompts
from stockpot.llm.base import LLM, LLMError
from stockpot.schemas import (
    ChatTurn,
    PantryItem,
    PantryOp,
    PantryOps,
    ParsedItem,
    ParsedItems,
    Recipe,
    Recipes,
    ShoppingEntry,
)

TIMEOUT_MS = 45_000
CHAT_HISTORY = 20

log = logging.getLogger("uvicorn.error")


class Gemini(LLM):
    name = "gemini"

    def __init__(self, api_key: str, model: str, client=None):
        self.model = model
        self.client = client or genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))

    def structured[T: BaseModel](self, system: str, user: str, schema: type[T], temperature: float = 0.4) -> T:
        """One request whose answer must parse as `schema`."""
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=temperature,
        )
        try:
            response = self.client.models.generate_content(model=self.model, contents=user, config=config)
        except errors.APIError as error:
            log.warning("Gemini request failed: %s %s", error.code, error.status)
            raise LLMError(f"Gemini request failed ({error.code}).") from error
        except Exception as error:
            log.warning("Gemini request failed: %s", type(error).__name__)
            raise LLMError("Gemini could not be reached.") from error
        if isinstance(response.parsed, schema):
            return response.parsed
        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as error:
            raise LLMError("Gemini answered in an unexpected shape.") from error

    def parse_items(self, text: str, today: date) -> list[ParsedItem]:
        return self.structured(*prompts.parse_items(text, today), ParsedItems, temperature=0.2).items

    def suggest_recipes(
        self, pantry: list[PantryItem], today: date, preferences: str = "", notes: str = ""
    ) -> list[Recipe]:
        return self.structured(*prompts.suggest_recipes(pantry, today, preferences, notes), Recipes, 0.8).recipes

    def plan_recipe(self, dish: str, pantry: list[PantryItem], today: date, notes: str = "") -> Recipe:
        return self.structured(*prompts.plan_recipe(dish, pantry, today, notes), Recipe)

    def tweak_recipe(
        self, recipe: Recipe, feedback: str, pantry: list[PantryItem], today: date, notes: str = ""
    ) -> Recipe:
        return self.structured(*prompts.tweak_recipe(recipe, feedback, pantry, today, notes), Recipe)

    def apply_cooking(self, recipe: Recipe, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        return self.structured(*prompts.apply_cooking(recipe, pantry, today), PantryOps, 0.1).ops

    def adjust_pantry(self, instruction: str, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        return self.structured(*prompts.adjust_pantry(instruction, pantry, today), PantryOps, 0.1).ops

    def chat(
        self,
        history: list[ChatTurn],
        message: str,
        pantry: list[PantryItem],
        shopping: list[ShoppingEntry],
        today: date,
        notes: str = "",
    ) -> Iterator[str]:
        contents = [
            types.Content(role="model" if turn.role == "assistant" else "user", parts=[types.Part(text=turn.content)])
            for turn in history[-CHAT_HISTORY:]
        ]
        contents.append(types.Content(role="user", parts=[types.Part(text=message)]))
        config = types.GenerateContentConfig(
            system_instruction=prompts.chat_system(pantry, shopping, today, notes), temperature=0.8
        )
        try:
            for chunk in self.client.models.generate_content_stream(model=self.model, contents=contents, config=config):
                if chunk.text:
                    yield chunk.text
        except errors.APIError as error:
            log.warning("Gemini chat failed: %s %s", error.code, error.status)
            raise LLMError(f"Gemini chat failed ({error.code}).") from error
        except Exception as error:
            log.warning("Gemini chat failed: %s", type(error).__name__)
            raise LLMError("Gemini could not be reached.") from error
