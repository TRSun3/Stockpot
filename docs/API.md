# API

Every route is JSON under `/api`. Errors come back as `{"error": "a readable message"}` with a fitting status code. Everything except the auth routes and `/api/health` needs a logged-in session and answers 401 without one.

## Accounts

| Method | Path | Does |
|---|---|---|
| POST | `/api/auth/signup` | `{username, password}` creates an account and logs it in (201). 409 if the username is taken |
| POST | `/api/auth/login` | `{username, password}` logs in. 401 on a wrong username or password |
| POST | `/api/auth/logout` | Ends the session and clears the cookie |
| GET | `/api/me` | `{username, llm}`, where `llm` is `mock` or `gemini` |

Usernames are 3 to 32 letters, digits, `_`, `.`, or `-`, unique regardless of case. Passwords are 6 to 128 characters. Logging in sets an `HttpOnly`, `SameSite=Lax` cookie named `stockpot_session`. Each browser holds its own cookie, so a normal window and a private window can be logged in as different people at once.

## Pantry

| Method | Path | Does |
|---|---|---|
| GET | `/api/items` | Every item, soonest to expire first, items without an expiry last |
| POST | `/api/items` | `{name, description?, expires_on?}` adds one item (201) |
| GET | `/api/items/expiring?days=3` | The Use Soon list: items expiring within `days` (0 to 60), plus everything already expired |
| GET | `/api/items/{id}` | One item |
| PATCH | `/api/items/{id}` | Changes only the fields sent. `"expires_on": null` clears the expiry |
| DELETE | `/api/items/{id}` | Discards an item, whether used up or thrown out |

An item comes back as `{id, name, description, expires_on, status, days_left, updated_at}`. `days_left` counts from today and goes negative once the item has expired. `status` is one of:

| Status | Means |
|---|---|
| `expired` | Past its date |
| `today` | Expires today |
| `soon` | Expires within 3 days |
| `fresh` | More than 3 days left |
| `none` | No expiry, like rice or salt |

Names are 1 to 80 characters and descriptions up to 500. An item that belongs to another account answers 404, the same as one that doesn't exist.

### In Plain Words

| Method | Path | Does |
|---|---|---|
| POST | `/api/items/parse` | `{text}` like "a dozen eggs and some spinach" adds each grocery with an estimated expiry, and returns the new items (201). 422 when the text names no food |
| POST | `/api/items/adjust` | `{text}` like "I used half the milk" changes the pantry to match. Returns `{changes, rejected}` |

`changes` lists what happened, each as `{action: added | updated | removed, item_id, name, description?}`, so the page can say "Updated milk, removed eggs". `rejected` lists every change the LLM proposed that was refused, each with a `reason`. See [LLM.md](LLM.md) for the rules.

When the LLM fails, these routes and every other AI route answer 502 with a friendly message and change nothing.

## Shopping List

| Method | Path | Does |
|---|---|---|
| GET | `/api/shopping` | The list, unchecked entries first, each group in the order added |
| POST | `/api/shopping` | `{name, note?}` adds an entry (201) |
| PATCH | `/api/shopping/{id}` | `{name?, note?, checked?}` changes only the fields sent |
| DELETE | `/api/shopping/{id}` | Removes an entry |
| POST | `/api/shopping/move-to-pantry` | Moves every checked entry into the pantry with an estimated expiry, and returns `{moved: [items]}`. 400 when nothing is checked |

An entry comes back as `{id, name, note, checked}`.
