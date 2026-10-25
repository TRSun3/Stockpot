"""The shapes of request bodies and responses, and of what the LLM answers with."""

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, field_validator

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class Credentials(BaseModel):
    username: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$"),
    ]
    password: str = Field(min_length=6, max_length=128)


class ItemIn(BaseModel):
    name: Name
    description: Text = ""
    expires_on: date | None = None


class ItemPatch(BaseModel):
    """Only the fields present change. An explicit null `expires_on` clears the expiry."""

    name: Name | None = None
    description: Text | None = None
    expires_on: date | None = None

    def changes(self) -> dict:
        changes = self.model_dump(include=self.model_fields_set)
        return {key: value for key, value in changes.items() if value is not None or key == "expires_on"}


class ShoppingIn(BaseModel):
    name: Name
    note: Text = ""


class ShoppingPatch(BaseModel):
    name: Name | None = None
    note: Text | None = None
    checked: bool | None = None

    def changes(self) -> dict:
        return {
            key: value for key, value in self.model_dump(include=self.model_fields_set).items() if value is not None
        }


class TextIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


# What the LLM reads and writes. These stay free of length limits and other constraints
# because they double as Gemini response schemas; `guard` checks and trims what comes back.


class PantryItem(BaseModel):
    id: int
    name: str
    description: str
    expires_on: str | None


class ShoppingEntry(BaseModel):
    name: str
    note: str
    checked: bool


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ParsedItem(BaseModel):
    name: str
    description: str
    expires_on: str | None


class ParsedItems(BaseModel):
    items: list[ParsedItem]


class RecipeUse(BaseModel):
    item_id: int
    name: str
    amount: str


class Recipe(BaseModel):
    title: str
    summary: str
    time_minutes: int
    uses: list[RecipeUse]
    missing: list[str]
    steps: list[str]
    why: str


class Recipes(BaseModel):
    recipes: list[Recipe]


class PantryOp(BaseModel):
    """One proposed change. `add` needs a name; `update` needs an item and a new description or expiry."""

    op: Literal["add", "update", "delete"]
    item_id: int | None = None
    name: str | None = None
    description: str | None = None
    expires_on: str | None = None


class PantryOps(BaseModel):
    ops: list[PantryOp]


Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class SuggestIn(BaseModel):
    preferences: Short = ""


class PlanIn(BaseModel):
    dish: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

    @field_validator("dish")
    @classmethod
    def names_something(cls, dish: str) -> str:
        if not any(character.isalpha() for character in dish):
            raise ValueError("name a dish, like carbonara")
        return dish


class TweakIn(BaseModel):
    recipe: Recipe
    feedback: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class RecipeIn(BaseModel):
    recipe: Recipe


class MissingIn(BaseModel):
    names: list[Name] = Field(max_length=20)
    recipe_title: Short = ""


class NotesIn(BaseModel):
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ChatIn(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
