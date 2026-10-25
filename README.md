# Stockpot

*Cook with what you've got.*

Stockpot is a virtual kitchen. It keeps track of everything in your pantry and when it expires, keeps your shopping list, suggests recipes from what you actually have, tells you whether you can make a dish, and updates the pantry when you cook. An AI cook, powered by Google Gemini, works from your real kitchen rather than from guesses.

## Running It

Stockpot needs [uv](https://docs.astral.sh/uv/). uv fetches the pinned Python (3.14) on its own.

```bash
uv sync
cp .env.example .env
uv run python -m stockpot.seed
uv run uvicorn stockpot.main:app --reload
```

Then open http://localhost:8000.

The seed creates two demo accounts with different, lived-in kitchens. Running it again resets them.

| Username | Password |
|---|---|
| `neal` | `stockpot` |
| `tianyue` | `stockpot` |

Log in as one in a normal window and the other in a private window to see two separate kitchens side by side.

Put a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) after `GEMINI_API_KEY=` in `.env` and restart. The free tier is enough, and with no billing set up it is never charged: past its limits the API refuses requests until the limit resets, and Stockpot says so. Without a key, or with `STOCKPOT_LLM=mock`, Stockpot runs on a built-in mock AI so everything works offline, and the page shows a "Mock AI" badge.

## What It Does

- **Pantry:** add groceries in your own words, one per line: type "a dozen eggs", press Enter, and it joins a short list to add together. Or add one item by hand. Every item gets an estimated expiry you can edit.
- **Use Soon:** everything expiring within three days, and anything already past its date.
- **Plain-words updates:** "I used half the milk and the spinach went bad" changes the pantry to match.
- **Shopping list:** check things off in the store, then move them all into the pantry in one click.
- **Recipes:** suggestions built from what you have and what's about to expire, "Can I make carbonara?", and tweaks like "make it vegetarian". Add what's missing to the shopping list, save recipes to a recipe box, and press "I cooked this" to update the pantry.
- **Chat:** tell the cook how you feel ("long day, want something cozy") and get ideas built on your kitchen.
- **Kitchen notes:** diets, allergies, and equipment the cook always keeps in mind.
- **Kitchen home:** click the pot for an animated kitchen. The note on the fridge is your shopping list, and the fridge, shelves, stove, recipe box, and chef hat each open their part of the app.

## Testing

```bash
uv run pytest
uv run pytest --browser
uv run ruff check .
uv run python -m evals.run_evals
uv run python -m bench.run_bench
```

`--browser` also runs the demo end to end in Google Chrome against a live server and saves screenshots to `screenshots/`. The evals check the AI's answers scenario by scenario, and the benchmarks time a live server. What was run before release and what it found is in [VERIFICATION.md](docs/VERIFICATION.md).

## The Components

| Component | Source | Docs |
|---|---|---|
| API | `stockpot/` | [API.md](docs/API.md) |
| Database | `stockpot/db.py` | [DATA.md](docs/DATA.md) |
| AI layer | `stockpot/llm/`, `stockpot/guard.py` | [LLM.md](docs/LLM.md) |
| Frontend | `static/` | [FRONTEND.md](docs/FRONTEND.md) |
| Evals | `evals/` | [EVALS.md](docs/EVALS.md) |
| Benchmarks | `bench/` | [BENCH.md](docs/BENCH.md) |

## Conventions

How the code is written and organized is in [AGENTS.md](AGENTS.md). Decisions and their reasons are in [DECISIONS.md](docs/DECISIONS.md).

## License

GPL-3.0. See [LICENSE](LICENSE).
