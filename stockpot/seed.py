"""Demo accounts with lived-in kitchens. Running it again resets them. Run with `uv run python -m stockpot.seed`."""

import sqlite3
from contextlib import closing
from datetime import date, timedelta

from stockpot import auth, config, db

PASSWORD = "stockpot"

# Each item is (name, description, days until it expires, or None for no expiry).
KITCHENS = {
    "neal": {
        "notes": "",
        "items": [
            ("Spinach", "a bag of baby spinach, about half left", 1),
            ("Avocados", "2 ripe avocados", 1),
            ("Chicken thighs", "2 lbs, bone-in", 2),
            ("Tomatoes", "4 vine tomatoes", 2),
            ("Sourdough", "half a loaf", 0),
            ("Milk", "about half a gallon of 2% milk", 3),
            ("Greek yogurt", "a big tub, opened last week", -1),
            ("Eggs", "a dozen large eggs", 18),
            ("Cheddar", "a block of sharp cheddar", 24),
            ("Butter", "1 stick, salted", 30),
            ("Onions", "2 yellow onions", 25),
            ("Garlic", "a head of garlic", 40),
            ("Parmesan", "a wedge, about a third left", 45),
            ("Pasta", "a box of spaghetti", None),
            ("Rice", "a bag of jasmine rice", None),
            ("Black beans", "2 cans", None),
            ("Soy sauce", "a bottle", None),
        ],
        "shopping": [("Lemons", "two"), ("Bacon", "for carbonara"), ("Oat milk", "")],
    },
    "tianyue": {
        "notes": "Loves spicy food. Cooking for two. Only a stovetop and a rice cooker, no oven.",
        "items": [
            ("Shiitake mushrooms", "a small box", 0),
            ("Salmon", "2 fillets", 1),
            ("Scallions", "a bunch", 1),
            ("Bok choy", "3 heads", 2),
            ("Broccoli", "1 head", 3),
            ("Tofu", "a block of firm tofu", 4),
            ("Cilantro", "a wilted bunch", -2),
            ("Eggs", "6 eggs", 12),
            ("Lemons", "3 lemons", 14),
            ("Ginger", "a knob of fresh ginger", 20),
            ("Kimchi", "a jar, half full", 30),
            ("Jasmine rice", "a big bag", None),
            ("Rice noodles", "a pack", None),
            ("Coconut milk", "1 can", None),
            ("Soy sauce", "a bottle", None),
        ],
        "shopping": [("Chili crisp", "the good one"), ("Limes", "")],
    },
}


def seed(conn: sqlite3.Connection, today: date) -> None:
    """Replaces the demo accounts with fresh ones. Other accounts are left alone."""
    with db.transaction(conn):
        for username, kitchen in KITCHENS.items():
            conn.execute("DELETE FROM users WHERE username = ?", (username,))
            user = auth.create_user(conn, username, PASSWORD)
            conn.executemany(
                "INSERT INTO items (user_id, name, description, expires_on) VALUES (?, ?, ?, ?)",
                [
                    (user.id, name, description, None if days is None else (today + timedelta(days)).isoformat())
                    for name, description, days in kitchen["items"]
                ],
            )
            conn.executemany(
                "INSERT INTO shopping_items (user_id, name, note) VALUES (?, ?, ?)",
                [(user.id, name, note) for name, note in kitchen["shopping"]],
            )
            if kitchen["notes"]:
                conn.execute("INSERT INTO preferences (user_id, notes) VALUES (?, ?)", (user.id, kitchen["notes"]))


def main() -> None:
    settings = config.load()
    db.init(settings.db_path)
    with closing(db.connect(settings.db_path)) as conn:
        seed(conn, date.today())
    accounts = ", ".join(KITCHENS)
    print(f"Seeded {accounts} in {settings.db_path} (password: {PASSWORD}).")


if __name__ == "__main__":
    main()
