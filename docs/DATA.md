# Data

Stockpot keeps everything in one SQLite file, `stockpot.db` in the repository root unless `STOCKPOT_DB` names another. The schema lives in `stockpot/db.py`.

## Starting Up

When the app starts, `db.init` creates the file and every table that is missing. Running it on an existing database changes nothing, so restarts keep all data. The database runs in WAL mode so reads never wait on a write.

Every connection turns foreign keys on, so deleting a user deletes their sessions, items, shopping list, chat, kitchen notes, and saved recipes. Connections run in autocommit mode with `synchronous = NORMAL`, which WAL makes safe. Requests borrow connections from a pool kept open for the life of the app, because opening the file is the slow part of a request on Windows (see VERIFICATION.md). A change that spans several statements runs inside `db.transaction`, which commits all of it or none of it.

## Tables

| Table | Holds |
|---|---|
| `users` | Username (unique, ignoring case), PBKDF2-SHA256 password hash, and its salt |
| `sessions` | A random token per login, tied to a user. Tokens last 30 days |
| `items` | The pantry: `name`, a free-text `description`, and `expires_on` (ISO date or null) |
| `shopping_items` | The shopping list: `name`, `note`, and `checked` |
| `chat_messages` | The chat history: `role` (`user` or `assistant`) and `content` |
| `preferences` | One row per user holding their kitchen notes: diet, allergies, equipment, household |
| `saved_recipes` | The recipe box: each recipe stored whole as JSON, with its title |

An item is deliberately just a name, a description, and an expiry. Amounts, brands, and state ("about half a gallon of 2% milk, opened Tuesday") all live in the description, which the AI reads and rewrites. There are no quantity or unit columns.

## Isolation

Every query that touches user data filters by `user_id`, and every value reaches SQL as a parameter. A row that belongs to someone else behaves exactly like a row that does not exist: both answer 404.
