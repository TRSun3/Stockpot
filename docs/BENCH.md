# Benchmarks

`bench/run_bench.py` measures a live server rather than calling functions directly, so the numbers include HTTP, sessions, and SQLite.

```bash
uv run python -m bench.run_bench            # print the table
uv run python -m bench.run_bench --record   # also append it to docs/VERIFICATION.md
```

It builds a throwaway database holding the two demo accounts and a third account, `bulk`, with 500 items, starts uvicorn on a free port on 127.0.0.1, and measures:

- **Core routes**, 60 times each, for the 17-item demo pantry and the 500-item one: listing the pantry, Use Soon, the shopping list, adding, editing, and removing an item, and checking off a shopping entry.
- **AI routes** on whichever backend `.env` selects: adding groceries from text, suggesting recipes, "can I make it", "I cooked this", and the chat's time to first chunk and to the end of the reply.
- **Two users at once**: both demo accounts add, list, and remove items in parallel for 100 rounds each. Any error, or either account seeing the other's items, fails the run.

Results are p50, p95, and max in milliseconds. With the mock, the chat's whole-reply time is mostly its deliberate word-by-word pacing (30 ms per word).

On Windows the server is stopped with `taskkill /T`, because the venv's `python.exe` is a launcher that starts the real interpreter as a child.
