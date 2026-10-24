"""What every LLM backend can do. Each method sees the real pantry and answers in Stockpot's own shapes."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date

from stockpot.schemas import ChatTurn, PantryItem, PantryOp, ParsedItem, Recipe, ShoppingEntry


class LLMError(Exception):
    """The backend failed or answered with something unusable. The message is safe to log."""


class LLM(ABC):
    name: str

    @abstractmethod
    def parse_items(self, text: str, today: date) -> list[ParsedItem]:
        """Groceries described in plain language, each with an estimated expiry."""

    @abstractmethod
    def suggest_recipes(self, pantry: list[PantryItem], today: date, preferences: str = "") -> list[Recipe]:
        """Recipes built mostly from the pantry, favoring what expires soonest."""

    @abstractmethod
    def plan_recipe(self, dish: str, pantry: list[PantryItem], today: date) -> Recipe:
        """A recipe for a dish the user names, showing what the pantry covers and what is missing."""

    @abstractmethod
    def tweak_recipe(self, recipe: Recipe, feedback: str, pantry: list[PantryItem], today: date) -> Recipe:
        """The recipe revised to follow the user's feedback."""

    @abstractmethod
    def apply_cooking(self, recipe: Recipe, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        """How the pantry changes after cooking the recipe: updates and deletes of the items it used."""

    @abstractmethod
    def adjust_pantry(self, instruction: str, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        """How the pantry changes to match an instruction like "I used half the milk"."""

    @abstractmethod
    def chat(
        self,
        history: list[ChatTurn],
        message: str,
        pantry: list[PantryItem],
        shopping: list[ShoppingEntry],
        today: date,
    ) -> Iterator[str]:
        """The assistant's reply to `message`, streamed in pieces."""
