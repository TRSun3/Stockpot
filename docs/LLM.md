# LLM

Stockpot's AI is Google Gemini, reached through the `google-genai` SDK. Until a key is configured it runs on a deterministic mock, so every feature works offline and every test is repeatable.

## Choosing A Backend

`stockpot.llm.get_llm` picks Gemini when `.env` sets `STOCKPOT_LLM=gemini` and a non-empty `GEMINI_API_KEY`, and the mock otherwise. The model is `GEMINI_MODEL`, `gemini-3.5-flash-lite` by default; [DECISIONS.md](DECISIONS.md) says why. The server logs which backend is active at startup, never the key. `GET /api/me` reports it as `llm` so the page can show a "Mock AI" badge.

## What The LLM Does

Both backends implement the interface in `stockpot/llm/base.py`. Every method except `parse_items` sees the user's real pantry: item id, name, description, and expiry. Parsing only needs today's date, since it describes new food rather than existing items.

| Method | Turns | Into |
|---|---|---|
| `parse_items` | "a dozen eggs, a bag of spinach and some cheddar" | Items with a name, a description that keeps the quantities, and an estimated expiry |
| `suggest_recipes` | The pantry and an optional mood or preference | Recipes favoring what expires soonest: three from Gemini, up to four from the mock; the API keeps at most four |
| `plan_recipe` | A dish the user names, like "carbonara" | A recipe showing what the pantry covers and what is missing |
| `tweak_recipe` | A recipe and feedback, like "make it vegetarian" | The revised recipe |
| `apply_cooking` | A recipe the user cooked | Updates and deletes for the items it used |
| `adjust_pantry` | "I used half the milk and the spinach went bad" | Adds, updates, and deletes that make the pantry match |
| `chat` | The conversation so far and a new message | A reply, streamed in pieces |

A recipe is `{title, summary, time_minutes, uses: [{item_id, name, amount}], missing, steps, why}`. A pantry change is `{op: add | update | delete, item_id?, name?, description?, expires_on?}`.

## Never Trusting The Answer

Whatever the LLM returns passes through `stockpot/guard.py` before it touches the database.

- Dates must be real ISO dates between 30 days ago and 5 years from now. Anything else becomes "no expiry".
- Parsed groceries need a name. Text is trimmed to the same limits the API enforces.
- A recipe's `uses` may only name items the user owns. A use naming any other item moves to `missing` instead, and its name is replaced by the item's real name.
- A pantry change is refused when it names an item the user doesn't own, an item outside the allowed set, or an item an earlier change in the same batch already touched, or when it is malformed (an update with nothing to change, an add with no name). Cooking only allows changes to the items the recipe used, and only adjustments may add items. An add is also refused when that food is already in the pantry, because it should update the existing item instead, unless an earlier change in the same batch removed it ("the milk went bad, I bought a new gallon").

Adding a food that is already in the pantry asks `adjust_pantry` to fold the new amount into the existing item's description, saying what was bought and asking for amounts to be added up. Only its updates to those items are used. If it fails or skips an item, the old and new descriptions are joined ("6 left, plus a dozen eggs"), so nothing is lost. The expiry is never the LLM's: the item keeps the sooner of the two dates.

The valid changes in a batch are applied together in one transaction, and each refused change is reported with its reason. One bad suggestion never blocks the good ones, and a crash partway through leaves the pantry untouched. The LLM never writes SQL, never sees other tables, and never chooses a `user_id`.

When a Gemini call fails or times out (45 seconds), or answers with something that doesn't parse, the backend raises `LLMError`. The API turns that into a 502 with a friendly message, and nothing is changed. A rate limit (429) raises `LLMBusy` instead, which tells the user to give it a minute. Brief server overloads (500, 502, 503) are retried once. No structured answer may run past 4096 tokens; chat replies are kept short by the prompt.

## Gemini

`stockpot/llm/gemini.py` asks for JSON (`response_mime_type="application/json"`) with the Pydantic model as `response_schema` for every method except chat. Chat streams through `generate_content_stream`, sending the last 20 messages as history. Every prompt lives in `stockpot/llm/prompts.py`. Each carries today's date. Every prompt about the existing kitchen also carries the pantry with item ids and how many days each item has left, and the user's kitchen notes where they apply. The chat also sees the shopping list, with checked entries marked. The structured prompts tell the model to refer only to listed item ids; the chat prompt tells it to mention only listed items.

## The Mock

`stockpot/llm/mock.py` is hand-written rules, the same answer for the same input:

- Parsing splits on commas, "and", and new lines, strips lead-ins like "just got back from the store:", keeps the quantity phrase as the description, and looks the food up in a shelf-life table (chicken 2 days, spinach 5, eggs 21, rice and canned goods none, anything frozen 90).
- Recipes come from a library of 18 templates, each matched against the pantry and scored by coverage, with a bonus for items expiring within three days and for matching the mood. Expired items are never used.
- Cooking subtracts counts it can ("3 eggs" from "a dozen eggs" leaves "9 eggs"), deletes items a recipe used whole, and marks the rest "partly used". Buying more adds counts the same way ("6 eggs" and "a dozen" make "18 eggs"). When it can't add them up, it keeps what was bought ("half a gallon, plus a gallon of milk"), or marks a plain "I bought more milk" "restocked". Each line of an instruction is its own clause.
- Chat picks up moods (tired, cozy, healthy, quick, celebrate), suggests the best-fitting recipe by name with the items it uses, nudges about items expiring soon or already expired, and streams the reply word by word.
