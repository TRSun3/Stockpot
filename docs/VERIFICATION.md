# Verification

What was run to check Stockpot before the visual polish, what it found, and what was fixed. Benchmark runs are appended at the end by `uv run python -m bench.run_bench --record`.

## Summary, 2026-10-24 (mock backend)

| Check | Result |
|---|---|
| `uv run pytest` | 132 passed (the 5 browser tests run separately) |
| `uv run pytest --browser` | 5 passed: every demo flow in Edge, no page or console errors |
| `uv run ruff check .` and `ruff format --check .` | Clean |
| `uv run python -m evals.run_evals` | 23 of 23 scenarios pass |
| `uv run python -m bench.run_bench` | Nothing pathologically slow; two users at once, 0 errors (table below) |
| Four independent code reviews | 46 findings; every one checked against the code, all real ones fixed (below) |

## Automated Tests

The suite covers everything the brief's verification list asks for, each in the test file for the module it exercises:

- The database is created when missing and keeps its data on restart (`test_db.py`).
- Accounts: signup, duplicate usernames regardless of case, wrong passwords, logout invalidating even a copied cookie, and a 401 from every protected route (`test_auth.py`).
- Cross-user isolation: another account gets 404 for listing, reading, editing, deleting, and cooking with someone's items, and for their shopping entries and saved recipes, even when the LLM is made to propose the other account's ids (`test_pantry.py`, `test_shopping.py`, `test_recipes.py`, `test_kitchen.py`).
- Items, sorting by expiry, and every Use Soon boundary (expired, today, 1 and 3 days, 4 days, no expiry) against a frozen today (`test_pantry.py`).
- The shopping list and moving checked entries into the pantry (`test_shopping.py`, `test_kitchen.py`).
- LLM change validation: foreign and missing ids, malformed ops, duplicates, cooking limited to the recipe's items, valid ops applying in one transaction, and a crash partway through leaving nothing changed (`test_guard.py`).
- Recipe shape and favoring what expires soon (`test_recipes.py`, `tests/llm/test_mock.py`).
- Chat streaming and saving both messages, including partial and failed replies (`test_chat.py`).
- The seed creating both demo accounts and resetting cleanly (`test_seed.py`).
- The Gemini client against a stand-in SDK client: the schema and prompt it sends, parsing, and every failure becoming a friendly error (`tests/llm/test_gemini.py`).

## Code Reviews

Four reviewers each read the code without being told what to expect: backend correctness, security, frontend robustness, and compliance with the brief. Each finding was checked against the code before anything changed.

### Backend correctness (12 findings)

| Finding | Outcome |
|---|---|
| Moving shopping into the pantry ran each entry's note through the grocery parser, so "Spinach (for Spinach and Cheddar Omelette)" became four junk items | Fixed: entries keep their own name and note, the LLM only estimates expiry from the name |
| An entry the LLM skipped (paper towels) vanished from both lists | Fixed: every claimed entry moves, without an expiry if the LLM skipped it |
| A double-submitted move could add everything twice | Fixed: entries are claimed inside the transaction; a repeat answers 409 |
| Ids too large for SQLite crashed with a 500 | Fixed: path ids are bounded and answer 422 |
| The mock's diet filter over-captured ("no dairy but love eggs" banned eggs), missed families ("fish", "dairy"), and ignored optional extras | Fixed |
| The seeded "no oven" account was offered an oven recipe | Fixed: oven recipes are tagged and filtered |
| "Make it less spicy" made it spicier | Fixed: milder requests remove heat |
| "Took the chicken out of the freezer" deleted it; "finished half the milk" deleted it; "chocolate" matched "ate" | Fixed: thawing is understood, halves are checked before "gone", verbs match whole words |
| Dishes matched loosely ("tea" planned steak); a dish of only punctuation gave 502 | Fixed: whole-word matching; such dishes answer 422 |
| The mock could use an expired item in a generic plan, and "egg" matched "Eggplant" | Fixed |
| Cooking didn't count down a bare "1", and "2 cups, halved" was subtracted from tomatoes | Fixed |
| A client disconnecting before the chat stream began left an unanswered question saved | Fixed: both messages are saved together when the reply ends |

### Security (nothing exploitable at high or medium severity)

The reviewer confirmed parameterized SQL everywhere, user isolation on every route (including crafted recipe JSON and prompt injection), sound password hashing and sessions, the key never logged or returned, `.env` never committed, and no HTML built from strings anywhere in the frontend.

| Finding | Outcome |
|---|---|
| Request bodies sent to the LLM had no size limit (a 20 MB recipe was accepted) | Fixed: bodies over 256 KB answer 413, and a tweaked recipe is trimmed before it reaches the LLM |
| Login was measurably faster for unknown usernames | Fixed: unknown usernames hash a dummy password |
| Expired session rows were never cleaned up | Fixed: logging in clears expired sessions |
| No Host check, so DNS rebinding could reach a local server | Accepted: the demo binds to 127.0.0.1, cookies stay on `localhost`, and a fixed allow-list would break other local setups |
| No login rate limit; demo accounts share a known password | Accepted: the brief rules out rate limiting, and the server only listens on 127.0.0.1 |

### Frontend robustness (20 findings, all fixed)

The most visible were: pressing Esc in Kitchen notes saved the edits anyway; a session ending left the last account's recipes and chat on screen; an older list reload could overwrite a newer one, so deleted items reappeared; any reload threw away an open edit form and keyboard focus; a dropped chat stream looked finished; Clear could run mid-reply; "Find recipes for this" failed on chat messages over 300 characters; and tweaking or saving could be repeated by accident. Also fixed: loading and no-match states, error toasts announced as alerts and kept while hovered, screen readers not flooded during streaming, the chat no longer stealing focus, and buttons named for the item they act on.

### Brief compliance

Every required test and rule checked out. The gaps were small and are fixed: errors outside the handled cases now answer with JSON, suggestions are capped at the documented four, two deviations are recorded in `DECISIONS.md` (updates that only change expiry; parsing without the pantry), the chat prompt says to mention only listed items, five stale doc statements were corrected, and the 401 test now covers every protected route.

## Evals

`uv run python -m evals.run_evals` on the mock: 23 of 23 scenarios pass. The first run caught a real mock bug: the bean quesadilla, tagged vegetarian, accepted chicken in place of beans, so vegetarian requests could still get chicken. See [EVALS.md](EVALS.md) for what each scenario checks.

## Benchmarks

The first run showed every write at about 31 ms against about 5 ms for a read. SQLite itself took under a millisecond for the write; the time went into opening the database file, which costs about 20 ms on Windows right after another connection has written to it (most likely the antivirus rescanning the changed file). Each request used to open its own connection, so every write paid that. Requests now borrow connections from a small pool kept open for the app's lifetime (`db.Pool`). Writes dropped to about 3 ms, and the two-user run from 9.7 s to 2.2 s. `synchronous = NORMAL`, safe under WAL, is on as well but was not the cause.

See [BENCH.md](BENCH.md) for what is measured. The first run below is from before the pool; the second is after.

### Benchmark, before the connection pool, 2026-10-24 20:17, mock backend

Live uvicorn server on 127.0.0.1, 60 runs per core route. Milliseconds.

| Pantry | Route | p50 | p95 | max |
|---|---|---:|---:|---:|
| seeded (17) | list items | 6.0 | 19.5 | 22.4 |
| seeded (17) | use soon | 6.1 | 16.2 | 23.9 |
| seeded (17) | shopping list | 5.3 | 16.3 | 33.2 |
| seeded (17) | add item | 31.3 | 36.2 | 48.9 |
| seeded (17) | edit item | 32.0 | 47.3 | 120.9 |
| seeded (17) | remove item | 30.7 | 41.1 | 43.2 |
| seeded (17) | check off shopping | 32.1 | 42.1 | 43.8 |
| large (500) | list items | 7.9 | 10.2 | 34.8 |
| large (500) | use soon | 6.8 | 8.6 | 10.2 |
| large (500) | shopping list | 4.5 | 14.8 | 21.3 |
| large (500) | add item | 31.3 | 38.1 | 86.7 |
| large (500) | edit item | 31.1 | 41.6 | 121.3 |
| large (500) | remove item | 30.9 | 39.5 | 71.2 |
| large (500) | check off shopping | 32.3 | 44.9 | 79.1 |
| AI | add groceries from text | 34.4 | 40.5 | 40.5 |
| AI | suggest recipes | 32.5 | 40.4 | 40.4 |
| AI | can I make it | 10.9 | 14.1 | 14.1 |
| AI | I cooked this | 15.2 | 28.3 | 28.3 |
| AI | chat: first chunk | 58.3 | 88.7 | 88.7 |
| AI | chat: whole reply | 2209.3 | 2248.8 | 2248.8 |

Two users at once: 200 add-read-remove rounds in 9.74 s, p50 90.7 ms, p95 147.8 ms per round, 0 errors.

### Benchmark, 2026-10-24 20:20, mock backend

Live uvicorn server on 127.0.0.1, 60 runs per core route. Milliseconds.

| Pantry | Route | p50 | p95 | max |
|---|---|---:|---:|---:|
| seeded (17) | list items | 3.6 | 6.3 | 47.2 |
| seeded (17) | use soon | 3.9 | 4.5 | 4.7 |
| seeded (17) | shopping list | 3.0 | 3.6 | 10.5 |
| seeded (17) | add item | 5.4 | 11.2 | 30.5 |
| seeded (17) | edit item | 5.5 | 11.8 | 21.4 |
| seeded (17) | remove item | 4.2 | 9.1 | 9.5 |
| seeded (17) | check off shopping | 9.6 | 11.3 | 25.2 |
| large (500) | list items | 21.5 | 37.8 | 40.9 |
| large (500) | use soon | 14.9 | 19.6 | 20.1 |
| large (500) | shopping list | 7.2 | 8.6 | 9.3 |
| large (500) | add item | 9.7 | 11.5 | 12.6 |
| large (500) | edit item | 9.7 | 11.3 | 19.4 |
| large (500) | remove item | 8.0 | 10.3 | 28.2 |
| large (500) | check off shopping | 8.6 | 10.2 | 11.4 |
| AI | add groceries from text | 13.5 | 25.6 | 25.6 |
| AI | suggest recipes | 30.5 | 75.9 | 75.9 |
| AI | can I make it | 12.5 | 14.7 | 14.7 |
| AI | I cooked this | 13.0 | 16.5 | 16.5 |
| AI | chat: first chunk | 57.3 | 80.7 | 80.7 |
| AI | chat: whole reply | 2196.8 | 2209.4 | 2209.4 |

Two users at once: 200 add-read-remove rounds in 5.80 s, p50 50.2 ms, p95 78.6 ms per round, 0 errors.
