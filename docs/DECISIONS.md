# Decisions

Choices made where the brief was silent or where the project deviates from it, and why.

## Tooling

- **Python 3.14.** It has had a year of patch releases and every dependency ships prebuilt 3.14 wheels for Windows. 3.15 is too new to trust with compiled dependencies like `pydantic-core`. uv installs and pins it through `.python-version`, so no system Python is involved.
- **Playwright as a dev dependency.** The brief asks for every flow to be exercised in a real browser and for screenshots during polish. Playwright drives the Google Chrome already installed on the machine (`channel="chrome"`), so it downloads no browser. Chrome is the browser the owner uses. Only scripts and tests import it; the app never does.
- **`httpx` stays as the `TestClient` transport.** Starlette 1.10 deprecates `httpx` in favor of `httpx2`, which the brief doesn't list. The tests silence exactly that one warning and treat all other warnings as errors. `httpx` is installed regardless, because `google-genai` depends on it.
- **Default model `gemini-3.5-flash-lite`.** It is free, passes every eval scenario, and is the fastest model measured on the free tier: about 3 s to suggest three recipes, 1 to 2 s for every other AI action, and under 1 s to start a chat reply. `gemini-3.8-flash` took 43 to 48 s per request on the free tier, too slow for a demo. `gemma-4-26b-a4b-it` passed too, but took 12 to 20 s to suggest recipes and needed its own handling: its default thinking ran past a minute, and its JSON mode sometimes ran on into pages of padding. The model is one line in `.env`.
- **One known warning from `google-genai` on Python 3.14.** Importing the SDK touches `typing._UnionGenericAlias`, which Python plans to remove in 3.17. It works on 3.14, and the tests silence exactly that message. Newer SDK releases will need to fix it before Python 3.17 is an option.
- **Lines are 120 characters.** Recipe steps and chat phrasings are prose, and 120 keeps them on one line.

## The AI Layer

- **Partial application of LLM changes.** The brief offered all-or-nothing or valid-only for a batch with a bad op. Stockpot applies the valid ops in one transaction and reports each refused op with its reason. If one hallucinated item id blocked a whole cooking update, the user would have to fix the pantry by hand, and the refused op is shown either way.
- **An update may change only the expiry.** The brief calls an update without a description malformed. Stockpot also accepts an update whose only change is a valid new expiry, because "I froze the chicken" or "I took it out of the freezer" changes when food goes bad, not what it is. An update with neither is still refused.
- **Parsing groceries doesn't see the pantry.** The brief's prompt rule asks for the pantry in every system prompt, but `parse_items(text, today)` describes food that isn't in the pantry yet, so its prompt carries only today's date.
- **Moving shopping into the pantry keeps the user's own names and notes.** The LLM only estimates each entry's expiry from its name. Passing notes through the parser split notes like "for Spinach and Cheddar Omelette" into extra items, and an entry the LLM dropped (like paper towels) vanished from both lists.
- **Cooking may only touch the recipe's own items.** `apply_ops` takes the set of item ids the recipe used and refuses changes to anything else, in addition to refusing foreign or missing ids.
- **The pantry holds each food once.** Adding six eggs to a dozen should give one entry, not two. Names match ignoring case, spacing, and plurals. The LLM writes the combined description, because only it can add up "6 left" and "a dozen", and it does so through `adjust_pantry` rather than a new prompt. That costs one extra call, about 2 s on Gemini, and only when something matches. If the call fails, the descriptions are joined rather than the add failing. The merged item keeps the sooner expiry, so Use Soon still warns before the older batch turns, at the cost of the newer batch looking older than it is. The owner chose both.
- **Recipe uses that name unknown items become missing ingredients** rather than errors. Fixing the answer keeps a useful recipe on screen.
- **Parsed dates outside 30 days ago to 5 years ahead become "no expiry"**, rather than dropping the item.
- **Kitchen notes are one free-text field**, not a form of diet checkboxes. That matches the brief's free-text item model, and the LLM reads "vegetarian, allergic to peanuts, no oven, cooking for two" as easily as it reads a pantry description. The brief listed per-user preferences as a nice-to-have; they are built now because every recipe flow benefits.
- **A recipe box of saved recipes.** Recipes are generated fresh each time, so a liked one would otherwise be lost. A saved recipe is stored whole, and checking it against today's pantry runs it through `plan` again.
- **Chat streams as server-sent events over a POST**, read with `fetch` rather than `EventSource` (which can't POST). An `error` event can arrive partway without breaking the stream format.
- **Beyond the brief's interface:** `plan_recipe` ("Can I make carbonara?"), `tweak_recipe` (revising a suggestion from feedback), and `adjust_pantry` with `add` ops ("I bought more eggs"). The owner asked for knowing what can be made, adjusting generated recipes, and correcting the pantry in plain words.

## Performance

- **The LLM answer is the cost; the server is not.** Every pantry and shopping route finishes in 1 to 3 ms, even with 500 items, while a Gemini call takes 1 to 3 s, almost all of it spent writing the answer. Prompts stay as rich as the evals need, and server work is kept simple rather than clever.
- **No thinking budget.** `gemini-3.5-flash-lite` spends no thinking tokens on Stockpot's requests, so turning thinking off would change nothing.
- **Recipes go back to Gemini as compact JSON.** Indentation was about a quarter of the characters and told the model nothing.
- **The pantry is read once before an LLM call and again after it.** The second read checks the answer against the pantry as it is when the answer arrives, since the user may have removed something in the seconds the LLM took.
- **Gzip through Starlette's own middleware**, for responses over 1 KB. It cuts the page from about 82 KB to 25 KB and adds no dependency. Starlette leaves `text/event-stream` uncompressed, so the chat still streams piece by piece.
- **Every response says `Cache-Control: no-cache`.** Without it, browsers guess how long to keep each file, and after an edit they could pair a new `index.html` with an old script, leaving new buttons dead. The browser now checks each file on every load, and an unchanged one comes back as a short 304.
- **Every script module is listed as `modulepreload`** in `index.html`, so the browser fetches them all at once instead of discovering them import by import. A test fails if a module is missing from the list.

## Failure Handling

- **Nothing reaches the user as a crash.** Every request either answers or fails with a JSON error carrying a readable message. A failure inside a nice-to-have, such as the LLM merging a duplicate's description, falls back to a plain result instead of failing the request, and is logged in full so the bug stays visible. A failure mid-chat ends the stream with an `error` event, so the page never waits on a reply that will not come.
- **Requests without a Content-Length are refused (411).** The 256 KB limit is checked before the body is read, which needs the length up front. Browsers always send it for Stockpot's requests.

## Layout

- **Module names follow what they hold.** `guard.py` is the brief's `services.py` safety layer. `kitchen.py` holds the routes where the AI changes the kitchen, kept apart from the pantry's plain CRUD in `pantry.py` so `guard` can build on `pantry` without an import cycle. Tests mirror the modules, so the brief's `test_items.py` and `test_llm_ops.py` are `test_pantry.py` and `test_guard.py`.

- **Docs live in `docs/`**, including this file and `VERIFICATION.md`, rather than at the root as the brief sketches. This follows the conventions of the owner's other repositories. Only `README.md` and `AGENTS.md` sit at the root.
- **The brief itself is not tracked.** `STOCKPOT_BRIEF.md` is in `.gitignore`. The owner keeps it locally as the planning document.

## The Look

- **No design skill was available.** The brief asks for the polish to follow an installed frontend design skill. None was installed in this environment, so the design follows the brief's own direction directly; [FRONTEND.md](FRONTEND.md) describes it.
- **Fonts come from Google Fonts**, which the brief allows. Every font stack ends in a local fallback, so the demo still works offline, just in Georgia and the system sans.
- **Mock descriptions keep the user's own casing.** "a dozen eggs" stays lowercase, matching the seeded pantry, instead of being capitalized into "A dozen eggs".
