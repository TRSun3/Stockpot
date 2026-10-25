"""Recipes: suggestions from the pantry, "can I make this?", tweaks from feedback, cooking, and a recipe box."""

import json
import sqlite3

from fastapi import APIRouter, HTTPException

from stockpot import guard, pantry, preferences, shopping
from stockpot.auth import Conn, CurrentUser
from stockpot.deps import Model, RowId, Today
from stockpot.schemas import MissingIn, PlanIn, Recipe, RecipeIn, SuggestIn, TweakIn

SUGGESTIONS = 4

router = APIRouter(prefix="/api/recipes")


def owned(conn: sqlite3.Connection, user_id: int) -> dict[int, sqlite3.Row]:
    return {row["id"]: row for row in pantry.rows(conn, user_id)}


def usable(recipe: Recipe | None, conn: sqlite3.Connection, user_id: int) -> dict:
    """The answer checked against the pantry as it is now, which may have changed while the LLM worked."""
    cleaned = recipe and guard.clean_recipe(recipe, owned(conn, user_id))
    if cleaned is None:
        raise HTTPException(502, "The AI cook came back without a usable recipe. Please try again.")
    return cleaned.model_dump()


@router.post("/suggest")
def suggest(body: SuggestIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Recipes built mostly from the pantry, favoring what expires soonest and following `preferences`."""
    recipes = llm.suggest_recipes(
        pantry.for_llm(conn, user.id), today, body.preferences, preferences.notes(conn, user.id)
    )
    items = owned(conn, user.id)
    cleaned = [guard.clean_recipe(recipe, items) for recipe in recipes[:SUGGESTIONS]]
    return {"recipes": [recipe.model_dump() for recipe in cleaned if recipe]}


@router.post("/plan")
def plan(body: PlanIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """A recipe for a dish the user names, showing what they have and what they'd need to buy."""
    recipe = llm.plan_recipe(body.dish, pantry.for_llm(conn, user.id), today, preferences.notes(conn, user.id))
    return {"recipe": usable(recipe, conn, user.id)}


@router.post("/tweak")
def tweak(body: TweakIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """The recipe revised to follow the user's feedback, like "make it spicier" or "no oven"."""
    items = owned(conn, user.id)
    given = guard.clean_recipe(body.recipe, items)
    if given is None:
        raise HTTPException(422, "A recipe needs a title and at least one step.")
    recipe = llm.tweak_recipe(
        given, body.feedback, pantry.as_llm(list(items.values())), today, preferences.notes(conn, user.id)
    )
    return {"recipe": usable(recipe, conn, user.id)}


@router.post("/cooked")
def cooked(body: RecipeIn, user: CurrentUser, conn: Conn, today: Today, llm: Model) -> dict:
    """Updates the pantry after cooking: only the items the recipe used, and only ones the user owns."""
    items = owned(conn, user.id)
    recipe = guard.clean_recipe(body.recipe, items)
    if recipe is None:
        raise HTTPException(422, "A recipe needs a title and at least one step.")
    if not recipe.uses:
        raise HTTPException(404, "None of this recipe's ingredients are in your pantry.")
    ops = llm.apply_cooking(recipe, pantry.as_llm(list(items.values())), today)
    return guard.apply_ops(conn, user.id, ops, today, allowed={use.item_id for use in recipe.uses})


@router.post("/missing-to-shopping")
def missing_to_shopping(body: MissingIn, user: CurrentUser, conn: Conn) -> dict:
    """Adds ingredients to the shopping list, skipping any already waiting on it."""
    waiting = {entry["name"].lower() for entry in shopping.rows(conn, user.id) if not entry["checked"]}
    added, skipped = [], []
    note = f"for {body.recipe_title}" if body.recipe_title else ""
    for name in dict.fromkeys(body.names):
        if name.lower() in waiting:
            skipped.append(name)
            continue
        waiting.add(name.lower())
        if entry := shopping.row(conn, user.id, shopping.insert(conn, user.id, name, note)):
            added.append(shopping.to_json(entry))
    return {"added": added, "skipped": skipped}


@router.get("/saved")
def saved(user: CurrentUser, conn: Conn) -> list[dict]:
    rows = conn.execute(
        "SELECT id, recipe, created_at FROM saved_recipes WHERE user_id = ? ORDER BY id DESC", (user.id,)
    ).fetchall()
    return [{"id": row["id"], "recipe": json.loads(row["recipe"]), "saved_at": row["created_at"]} for row in rows]


@router.post("/saved", status_code=201)
def save(body: RecipeIn, user: CurrentUser, conn: Conn) -> dict:
    recipe = guard.clean_recipe(body.recipe, owned(conn, user.id))
    if recipe is None:
        raise HTTPException(422, "A recipe needs a title and at least one step.")
    cursor = conn.execute(
        "INSERT INTO saved_recipes (user_id, title, recipe) VALUES (?, ?, ?)",
        (user.id, recipe.title, recipe.model_dump_json()),
    )
    return {"id": cursor.lastrowid, "recipe": recipe.model_dump()}


@router.delete("/saved/{saved_id}")
def unsave(saved_id: RowId, user: CurrentUser, conn: Conn) -> dict:
    cursor = conn.execute("DELETE FROM saved_recipes WHERE id = ? AND user_id = ?", (saved_id, user.id))
    if cursor.rowcount != 1:
        raise HTTPException(404, "That recipe isn't in your recipe box.")
    return {"ok": True}
