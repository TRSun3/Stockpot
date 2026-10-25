"""What every LLM backend can do. Each method about the existing kitchen sees the real pantry, and every method
answers in Stockpot's own shapes."""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import date

from stockpot.schemas import ChatTurn, PantryItem, PantryOp, ParsedItem, Recipe, ShoppingEntry

UNAVAILABLE = "The AI cook couldn't answer just now. Nothing was changed; please try again in a moment."


BUSY = "Stockpot's AI is at its free-tier request limit for the moment. Give it a minute and try again."


class LLMError(Exception):
    """The backend failed or answered with something unusable. The message is safe to log."""

    @property
    def friendly(self) -> str:
        return UNAVAILABLE


class LLMBusy(LLMError):
    """The backend refused because of a rate limit or quota; waiting fixes it."""

    @property
    def friendly(self) -> str:
        return BUSY


class LLM(ABC):
    """`notes` is the user's standing description of their kitchen and diet, like "vegetarian, no oven"."""

    name: str

    @abstractmethod
    def parse_items(self, text: str, today: date) -> list[ParsedItem]:
        """Groceries described in plain language, each with an estimated expiry."""

    @abstractmethod
    def suggest_recipes(
        self, pantry: list[PantryItem], today: date, preferences: str = "", notes: str = ""
    ) -> list[Recipe]:
        """Recipes built mostly from the pantry, favoring what expires soonest."""

    @abstractmethod
    def plan_recipe(self, dish: str, pantry: list[PantryItem], today: date, notes: str = "") -> Recipe:
        """A recipe for a dish the user names, showing what the pantry covers and what is missing."""

    @abstractmethod
    def tweak_recipe(
        self, recipe: Recipe, feedback: str, pantry: list[PantryItem], today: date, notes: str = ""
    ) -> Recipe:
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
        notes: str = "",
    ) -> Iterator[str]:
        """The assistant's reply to `message`, streamed in pieces."""
