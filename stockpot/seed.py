"""Demo accounts with lived-in kitchens. Running it again resets them. Run with `uv run python -m stockpot.seed`."""

import sqlite3
from contextlib import closing
from datetime import date, timedelta

from stockpot import auth, config, db

PASSWORD = "stockpot"

# Each item is (name, description, days until it expires, or None for no expiry).
KITCHENS = {
    "neal": {
        "notes": "High spicy food tolerance. No scallions.",
        "items": [
            ("Spinach", "baby spinach, half the bag left", 1),
            ("Avocados", "2, soft enough to use now", 1),
            ("Chicken thighs", "bone-in, skin-on, about 2 lb", 2),
            ("Tomatoes", "4 on the vine", 2),
            ("Sourdough", "half a loaf from the farmers market", 0),
            ("Milk", "2%, a little under half a gallon", 3),
            ("Greek yogurt", "Fage, big tub, opened last Sunday", -1),
            ("Eggs", "dozen large, brown", 18),
            ("Cheddar", "Tillamook sharp, 8 oz block, unopened", 24),
            ("Butter", "salted, 1 stick left", 30),
            ("Onions", "2 yellow", 25),
            ("Garlic", "1 head, a few cloves used", 40),
            ("Parmesan", "wedge, about a third left", 45),
            ("Pasta", "Barilla spaghetti, 1 lb box", None),
            ("Rice", "jasmine, 5 lb bag, mostly full", None),
            ("Black beans", "2 cans", None),
            ("Soy sauce", "Kikkoman, about half the bottle", None),
        ],
        "shopping": [("Lemons", "2"), ("Bacon", "thick-cut, for carbonara on Friday"), ("Oat milk", "Oatly Barista")],
    },
    "tianyue": {
        "notes": "Low spicy food tolerance.",
        "items": [
            ("Shiitake mushrooms", "8 oz box from H Mart", 0),
            ("Salmon", "2 skin-on fillets", 1),
            ("Scallions", "1 bunch, getting a little limp", 1),
            ("Bok choy", "3 heads of baby bok choy", 2),
            ("Broccoli", "1 crown", 3),
            ("Tofu", "extra-firm, 1 block, unopened", 4),
            ("Cilantro", "half a bunch, going slimy", -2),
            ("Eggs", "6 left", 12),
            ("Lemons", "3", 14),
            ("Ginger", "a thumb-sized piece", 20),
            ("Kimchi", "napa cabbage, jar about half full", 30),
            ("Jasmine rice", "Three Ladies, big bag, plenty left", None),
            ("Rice noodles", "1 pack of pad thai noodles", None),
            ("Coconut milk", "1 can, full-fat", None),
            ("Soy sauce", "light soy, almost full", None),
        ],
        "shopping": [("Chili crisp", "Lao Gan Ma, the big jar"), ("Limes", "4")],
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
