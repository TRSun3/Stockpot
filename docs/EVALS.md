# Evals

The evals check what the LLM actually says, scenario by scenario, with assertions a program can verify. They run against whichever backend `.env` selects, so the same suite that passes on the mock is the bar Gemini has to clear.

```bash
uv run python -m evals.run_evals                  # the backend .env selects
uv run python -m evals.run_evals --backend gemini
uv run python -m evals.run_evals --only suggest   # scenarios whose id contains "suggest"
```

It prints a pass/fail table with the reason for each failed check and a score, and exits non-zero when anything fails. `tests/test_evals.py` runs the whole suite on the mock as part of `uv run pytest`.

## Scenarios

`evals/scenarios.json` holds a few named kitchens (a weeknight pantry with spinach expiring tomorrow and an expired yogurt, a single-item pantry, a pantry of only shelf-stable goods, and an empty one) and a list of scenarios. Expiry dates are given as days from today, so the suite never goes stale. Each scenario names an LLM method, a kitchen, an input, and its checks:

| Method | What is checked |
|---|---|
| `parse_items` | The right number of items, sensible names, quantities kept in descriptions, perishables expiring within a plausible window, shelf-stable goods without a near expiry, notes in parentheses staying out of names, and nonsense or very long input not breaking anything |
| `suggest_recipes` | Recipes only cite real item ids, at least one uses the spinach expiring tomorrow, none uses the expired yogurt, the top suggestions miss at most two ingredients, vegetarian requests and kitchen notes keep the chicken out, a tired "under 20 minutes" request leads with something quick, and empty or odd pantries still answer validly |
| `plan_recipe` | "Carbonara" is a carbonara that uses the eggs and pasta and says bacon is missing |
| `tweak_recipe` | "Make it vegetarian" removes the chicken and still leaves a complete recipe |
| `apply_cooking` | Changes touch only the recipe's items, never add anything, always rewrite descriptions, and count down ("a dozen eggs" less 3 leaves 9), and using every egg removes them |
| `adjust_pantry` | "I used half the milk, the spinach went bad, and I bought a loaf of bread" updates the milk, removes the spinach, adds bread, and touches nothing else; freezing pushes the expiry out a month or more; small talk changes nothing |
| `chat` | Replies are non-empty, mention something from the pantry, don't claim the user has food they don't, stay short, and handle an empty pantry |

The checks themselves are small functions named `check_<name>` in `evals/run_evals.py`; a scenario refers to them by name.
