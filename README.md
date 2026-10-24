# Stockpot

*Cook with what you've got.*

Stockpot is a virtual kitchen. It keeps track of everything in your pantry and when it expires, keeps your shopping list, suggests recipes from what you actually have, and updates the pantry when you cook. An AI cook, powered by Google Gemini, works from your real kitchen rather than from guesses.

## Running It

Stockpot needs [uv](https://docs.astral.sh/uv/). uv fetches the pinned Python (3.14) on its own.

```bash
uv sync
cp .env.example .env
uv run uvicorn stockpot.main:app --reload
```

Then open http://localhost:8000.

Without a `GEMINI_API_KEY` in `.env`, Stockpot runs on a built-in mock AI so everything works offline.

## Testing

```bash
uv run pytest
uv run ruff check .
```

## Conventions

How the code is written and organized is in [AGENTS.md](AGENTS.md). Documentation lives in [docs/](docs/).

## License

GPL-3.0. See [LICENSE](LICENSE).
