# Decisions

Choices made where the brief was silent or where the project deviates from it, and why.

## Tooling

- **Python 3.14.** It has had a year of patch releases and every dependency ships prebuilt 3.14 wheels for Windows. 3.15 is too new to trust with compiled dependencies like `pydantic-core`. uv installs and pins it through `.python-version`, so no system Python is involved.
- **Playwright as a dev dependency.** The brief asks for every flow to be exercised in a real browser and for screenshots during polish. Playwright drives the Edge already installed on the machine (`channel="msedge"`), so it downloads no browser. Only scripts and tests import it; the app never does.
- **`httpx` stays as the `TestClient` transport.** Starlette 1.10 deprecates `httpx` in favor of `httpx2`, which the brief doesn't list. The tests silence exactly that one warning and treat all other warnings as errors. `httpx` is installed regardless, because `google-genai` depends on it.
- **Default model `gemini-3.8-flash`**, the current stable Flash model. It is one line in `.env`.

## Layout

- **Docs live in `docs/`**, including this file and `VERIFICATION.md`, rather than at the root as the brief sketches. This follows the conventions of the owner's other repositories. Only `README.md` and `AGENTS.md` sit at the root.
- **The brief itself is not tracked.** `STOCKPOT_BRIEF.md` is in `.gitignore`. The owner keeps it locally as the planning document.
