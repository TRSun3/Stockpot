# Working on Stockpot

## Commands

- `uv sync` installs everything, including the dev tools.
- `uv run uvicorn stockpot.main:app --reload` serves the app at http://localhost:8000.
- `uv run pytest` runs the tests. Warnings are errors.
- `uv run ruff check .` and `uv run ruff format .` lint and format. Both must be clean before a commit.

Python and packages are managed with `uv` only: `uv add`, `uv add --dev`, `uv run`. No pip, poetry, conda, or bare venvs.

## Documentation

- All docs live in `docs/`, except `README.md` and this file. Each component has one doc named after it.
- Docs describe the code as it is now and change in the same commit as the code they describe.
- Decisions and the reasons behind them go in `docs/DECISIONS.md`. Verification runs and their results go in `docs/VERIFICATION.md`.

## Dependencies

- Runtime packages are `fastapi`, `uvicorn`, and `google-genai`. Everything else is the standard library.
- Dev-only packages are `pytest`, `httpx`, `ruff`, and `playwright`. Any new package needs a reason in `docs/DECISIONS.md`.
- The frontend is vanilla HTML, CSS, and JavaScript modules served as static files. No frameworks, bundlers, or Node toolchain.
- The only LLM provider is Google Gemini. The mock stands in for it when no key is configured.

## Style

- Comments say what something is or does, not its history. Rationale goes in `docs/`. Comments do not name people, conversations, or commits.
- Tests live in `tests/`, one file per module, never inline in the source.
- Test names are full sentences stating the claim. The set is small and each test earns its place.
- Every query on user data filters by `user_id`, and every SQL value is a parameter.
- User and LLM text reaches the page through `textContent` or escaping, never raw `innerHTML`.
- Prefer simple, obvious code over configuration knobs.

## Git

- Each commit is one reviewed, working phase of the work: tests and lint pass at every commit.
- Commit messages do not link back to the tool that wrote the code. Co-author trailers are fine.
