"""The shapes of request bodies and responses."""

from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

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
            key: value
            for key, value in self.model_dump(include=self.model_fields_set).items()
            if value is not None
        }
