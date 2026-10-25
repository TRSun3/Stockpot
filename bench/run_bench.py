"""Measures Stockpot against a live server on a throwaway database.

    uv run python -m bench.run_bench             # print the table
    uv run python -m bench.run_bench --record    # also append it to docs/VERIFICATION.md

Starts uvicorn on a free port with the configured LLM backend (the mock unless .env selects Gemini),
then times the core routes with a realistic pantry and a 500-item one, the AI-backed routes including
the chat's time to first chunk, and two users working at once.
"""

import argparse
import http.client
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from stockpot import auth, config, db, seed

ROOT = Path(__file__).resolve().parent.parent
RUNS = 60


class Client:
    """One keep-alive connection holding one account's session cookie."""

    def __init__(self, port: int, username: str):
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        self.cookie = ""
        status, _ = self.call("POST", "/api/auth/login", {"username": username, "password": seed.PASSWORD})
        assert status == 200, f"login failed for {username}"

    def call(self, method: str, path: str, body=None) -> tuple[int, object]:
        headers = {"Content-Type": "application/json", "Cookie": self.cookie}
        self.conn.request(method, path, body=None if body is None else json.dumps(body), headers=headers)
        response = self.conn.getresponse()
        data = response.read()
        cookie = response.getheader("set-cookie")
        if cookie:
            self.cookie = cookie.split(";")[0]
        return response.status, json.loads(data) if data and data[:1] in b"[{" else data

    def rest(self, seconds: float) -> None:
        """Waits, letting go of the connection first so the server's keep-alive timeout can't drop it mid-request."""
        if seconds:
            self.conn.close()
            time.sleep(seconds)

    def timed(self, method: str, path: str, body=None) -> float:
        started = time.perf_counter()
        status, _ = self.call(method, path, body)
        elapsed = time.perf_counter() - started
        assert status < 400, f"{method} {path} answered {status}"
        return elapsed

    def chat(self, message: str) -> tuple[float, float]:
        """Seconds to the first streamed text and to the end of the reply."""
        started = time.perf_counter()
        self.conn.request(
            "POST",
            "/api/chat",
            body=json.dumps({"message": message}),
            headers={"Content-Type": "application/json", "Cookie": self.cookie},
        )
        response = self.conn.getresponse()
        first = None
        while line := response.readline():
            if first is None and line.startswith(b'data: {"type": "text"'):
                first = time.perf_counter() - started
        return first or float("nan"), time.perf_counter() - started


def stats(samples: list[float]) -> tuple[float, float, float]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return statistics.median(ordered) * 1000, p95 * 1000, max(ordered) * 1000


def stop(process: subprocess.Popen) -> None:
    """Stops the server and anything it started; on Windows the venv's python.exe is a launcher with a child."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        process.terminate()
    process.wait(timeout=10)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def prepare(path: Path) -> None:
    """Seeds the demo accounts and a third account, `bulk`, with 500 items."""
    db.init(path)
    with closing(db.connect(path)) as conn:
        seed.seed(conn, date.today())
        with db.transaction(conn):
            conn.execute("DELETE FROM users WHERE username = 'bulk'")
            user = auth.create_user(conn, "bulk", seed.PASSWORD)
            foods = [name for kitchen in seed.KITCHENS.values() for name, _, _ in kitchen["items"]]
            conn.executemany(
                "INSERT INTO items (user_id, name, description, expires_on) VALUES (?, ?, ?, ?)",
                [
                    (
                        user.id,
                        f"{foods[i % len(foods)]} {i}",
                        "some left",
                        None if i % 7 == 0 else (date.today() + timedelta(days=i % 40 - 5)).isoformat(),
                    )
                    for i in range(500)
                ],
            )


def core_routes(client: Client, label: str) -> list[tuple]:
    rows = []
    for name, method, path, body in (
        ("list items", "GET", "/api/items", None),
        ("use soon", "GET", "/api/items/expiring?days=3", None),
        ("shopping list", "GET", "/api/shopping", None),
    ):
        rows.append((label, name, *stats([client.timed(method, path, body) for _ in range(RUNS)])))
    added, edited, removed = [], [], []
    for i in range(RUNS):
        started = time.perf_counter()
        _, item = client.call("POST", "/api/items", {"name": f"Bench {i}", "description": "one", "expires_on": None})
        added.append(time.perf_counter() - started)
        edited.append(client.timed("PATCH", f"/api/items/{item['id']}", {"description": "two"}))
        removed.append(client.timed("DELETE", f"/api/items/{item['id']}"))
    rows += [
        (label, "add item", *stats(added)),
        (label, "edit item", *stats(edited)),
        (label, "remove item", *stats(removed)),
    ]
    toggles = []
    for i in range(RUNS):
        _, entry = client.call("POST", "/api/shopping", {"name": f"Bench {i}", "note": ""})
        toggles.append(client.timed("PATCH", f"/api/shopping/{entry['id']}", {"checked": True}))
        client.call("DELETE", f"/api/shopping/{entry['id']}")
    rows.append((label, "check off shopping", *stats(toggles)))
    return rows


def ai_routes(client: Client, runs: int, pause: float) -> list[tuple]:
    """Times each AI route, pausing `pause` seconds between rounds so a free-tier per-minute limit isn't hit."""
    rows = []
    parse, suggest, plan, cook = [], [], [], []
    for _ in range(runs):
        started = time.perf_counter()
        _, added = client.call("POST", "/api/items/parse", {"text": "a dozen eggs, a bag of spinach and some cheddar"})
        parse.append(time.perf_counter() - started)
        suggest.append(client.timed("POST", "/api/recipes/suggest", {"preferences": "something cozy"}))
        started = time.perf_counter()
        _, planned = client.call("POST", "/api/recipes/plan", {"dish": "omelette"})
        plan.append(time.perf_counter() - started)
        cook.append(client.timed("POST", "/api/recipes/cooked", {"recipe": planned["recipe"]}))
        client.rest(pause)
        for item in added:
            client.call("DELETE", f"/api/items/{item['id']}")
    rows += [
        ("AI", "add groceries from text", *stats(parse)),
        ("AI", "suggest recipes", *stats(suggest)),
        ("AI", "can I make it", *stats(plan)),
        ("AI", "I cooked this", *stats(cook)),
    ]
    chats = []
    for _ in range(max(3, runs // 2)):
        chats.append(client.chat("Long day, something warm please"))
        client.rest(pause)
    firsts, totals = zip(*chats, strict=True)
    rows += [("AI", "chat: first chunk", *stats(list(firsts))), ("AI", "chat: whole reply", *stats(list(totals)))]
    client.call("DELETE", "/api/chat")
    return rows


def concurrency(port: int) -> dict:
    """Two accounts each add, read, and remove items at the same time; nothing may fail or cross over."""
    errors: list[str] = []
    timings: list[float] = []
    lock = threading.Lock()

    def work(username: str) -> None:
        client = Client(port, username)
        for i in range(100):
            started = time.perf_counter()
            status, item = client.call("POST", "/api/items", {"name": f"{username} race {i}"})
            status2, items = client.call("GET", "/api/items")
            status3, _ = client.call("DELETE", f"/api/items/{item['id']}")
            with lock:
                timings.append(time.perf_counter() - started)
                if (status, status2, status3) != (201, 200, 200):
                    errors.append(f"{username}: {status} {status2} {status3}")
                if any(not row["name"].startswith(username) for row in items if " race " in row["name"]):
                    errors.append(f"{username} saw another account's item")

    threads = [threading.Thread(target=work, args=(name,)) for name in seed.KITCHENS]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = time.perf_counter() - started
    return {"rounds": len(timings), "seconds": elapsed, "errors": errors, "stats": stats(timings)}


def table(rows: list[tuple], backend: str, together: dict) -> str:
    lines = [
        f"### Benchmark, {datetime.now():%Y-%m-%d %H:%M}, {backend} backend",
        "",
        f"Live uvicorn server on 127.0.0.1, {RUNS} runs per core route. Milliseconds.",
        "",
        "| Pantry | Route | p50 | p95 | max |",
        "|---|---|---:|---:|---:|",
    ]
    lines += [f"| {label} | {name} | {p50:.1f} | {p95:.1f} | {peak:.1f} |" for label, name, p50, p95, peak in rows]
    p50, p95, peak = together["stats"]
    lines += [
        "",
        f"Two users at once: {together['rounds']} add-read-remove rounds in {together['seconds']:.2f} s, "
        f"p50 {p50:.1f} ms, p95 {p95:.1f} ms per round, {len(together['errors'])} errors"
        + (f": {together['errors'][:3]}" if together["errors"] else "."),
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="append the results to docs/VERIFICATION.md")
    args = parser.parse_args()
    backend = config.load().backend
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "bench.db"
        prepare(path)
        port = free_port()
        env = {**os.environ, "STOCKPOT_DB": str(path)}
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "stockpot.main:app", "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=env,
        )
        try:
            for _ in range(100):
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            rows = core_routes(Client(port, "neal"), "seeded (17)")
            rows += core_routes(Client(port, "bulk"), "large (500)")
            mock = backend == "mock"
            rows += ai_routes(Client(port, "neal"), runs=10 if mock else 3, pause=0 if mock else 15)
            together = concurrency(port)
        finally:
            stop(server)
    result = table(rows, backend, together)
    print(result)
    if args.record:
        log = ROOT / "docs" / "VERIFICATION.md"
        with log.open("a", encoding="utf-8") as file:
            file.write(f"\n{result}\n")
        print(f"\nAppended to {log}")
    if together["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
