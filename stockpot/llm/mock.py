"""A deterministic stand-in for Gemini: plausible answers from hand-written rules, the same every time."""

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from stockpot.llm.base import LLM
from stockpot.schemas import ChatTurn, PantryItem, PantryOp, ParsedItem, Recipe, RecipeUse, ShoppingEntry

DEFAULT_SHELF_LIFE = 7

# How a food is stored outranks what it is: frozen chicken keeps like anything frozen.
STORAGE: dict[str, int | None] = {
    "frozen": 90,
    "canned": None,
    "can of": None,
    "cans of": None,
    "jar of": None,
    "dried": None,
}

# Days a food keeps from today; None for shelf-stable. The longest matching phrase wins.
# fmt: off
SHELF_LIFE: dict[str, int | None] = {
    "chicken": 2, "turkey": 2, "ground beef": 2, "ground pork": 2, "beef": 3, "steak": 3, "pork": 3,
    "sausage": 4, "bacon": 7, "ham": 5, "salmon": 2, "fish": 2, "shrimp": 2, "cod": 2, "tofu": 7,
    "milk": 7, "cream": 7, "sour cream": 14, "yogurt": 14, "butter": 30, "cheddar": 28, "parmesan": 60,
    "mozzarella": 14, "feta": 14, "cheese": 21, "egg": 21, "hummus": 7,
    "spinach": 5, "lettuce": 5, "arugula": 4, "kale": 6, "cilantro": 5, "basil": 4, "parsley": 7,
    "mushroom": 5, "broccoli": 5, "cauliflower": 7, "zucchini": 6, "bell pepper": 7, "tomato": 6,
    "cucumber": 6, "avocado": 4, "banana": 5, "berries": 4, "strawberr": 4, "blueberr": 5, "apple": 30,
    "orange": 21, "lemon": 21, "lime": 21, "grape": 7, "carrot": 21, "celery": 14, "onion": 30,
    "green onion": 7, "scallion": 7, "garlic": 60, "potato": 30, "ginger": 21, "corn": 3,
    "green beans": 5, "asparagus": 4, "cabbage": 21, "bread": 5, "tortilla": 14, "bagel": 5, "juice": 10,
    "salsa": 14,
    "rice": None, "pasta": None, "spaghetti": None, "penne": None, "noodle": None, "flour": None,
    "sugar": None, "salt": None, "oil": None, "vinegar": None, "beans": None, "lentil": None,
    "chickpea": None, "quinoa": None, "oats": None, "cereal": None, "honey": None, "soy sauce": None,
    "peanut butter": None, "coffee": None, "tea": None, "broth": None, "stock": None,
    "tomato sauce": None, "tomato paste": None, "spice": None, "cumin": None, "paprika": None,
    "chili flakes": None, "olives": None, "chicken broth": None, "chicken stock": None,
    "beef broth": None, "ice cream": 60, "cream cheese": 14, "eggplant": 7, "orange juice": 10,
}

UNITS = {
    "a", "an", "some", "the", "few", "couple", "of", "dozen", "half", "quarter", "bag", "bags", "box",
    "boxes", "can", "cans", "jar", "jars", "bottle", "bottles", "carton", "cartons", "pack", "packs",
    "package", "packages", "bunch", "bunches", "head", "heads", "loaf", "loaves", "lb", "lbs", "pound",
    "pounds", "oz", "ounce", "ounces", "g", "kg", "gallon", "gallons", "quart", "quarts", "pint", "pints",
    "cup", "cups", "stick", "sticks", "clove", "cloves", "slice", "slices", "tub", "tubs", "container",
    "containers", "piece", "pieces", "fillet", "fillets", "large", "small", "big", "fresh", "more",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a dozen": 12, "dozen": 12,
    "half a dozen": 6, "a couple": 2, "a couple of": 2,
}
# fmt: on

LEAD_INS = re.compile(
    r"^(?:(?:i\s+)?(?:just\s+)?(?:got back from the (?:store|market|shop)|went shopping|bought|picked up|"
    r"got|grabbed|have|has|added?|also|plus|then|there(?:'s| is| are)|i've got|i have)\b[\s:,-]*)+",
    re.IGNORECASE,
)

SPLITTER = re.compile(r"\s*(?:[,;\n]|\band\b|&|\bplus\b)\s*", re.IGNORECASE)

MEATS = ("chicken", "beef", "steak", "pork", "bacon", "ham", "sausage", "turkey", "salmon", "fish", "shrimp")

COUNT_LEFT = r"\b(?:only\s+)?(\d+)\s+(?:[a-z]+\s+)?(?:left|remaining)\b"

# What a clause says happened to an item, checked in order so "used all" wins over "used".
# fmt: off
ADJUSTMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gone", ("used up", "used all", "use all", "finished", "ran out", "run out", "out of", "threw out",
              "tossed", "threw away", "thrown out", "went bad", "gone bad", "spoiled", "moldy", "mouldy",
              "ate all", "no more", "is gone", "are gone", "all gone", "got rid", "none left")),
    ("frozen", ("froze", "frozen", "freezer")),
    ("count", ()),
    ("half", ("half",)),
    ("low", ("running low", "almost out", "not much", "less than", "barely any", "a little left")),
    ("add", ("bought", "picked up", "got", "grabbed", "restock", "another", "new")),
    ("more", ("more", "extra", "plenty", "found")),
    ("some", ("used", "ate", "some", "a bit", "a little", "cooked with")),
)
# fmt: on

VERBS = ("used", "ate", "threw out", "tossed", "froze", "bought", "picked up", "finished")


def adjustment(clause: str) -> str | None:
    for action, phrases in ADJUSTMENTS:
        if action == "count":
            if re.search(COUNT_LEFT, clause):
                return action
        elif any(has_word(clause, phrase) for phrase in phrases):
            return action
    return None


def has_word(text: str, word: str) -> bool:
    """Whether `word` starts a word in `text`, so "tea" is not found in "steak"."""
    return re.search(rf"\b{re.escape(word)}", text) is not None


def shelf_life(text: str) -> int | None:
    lowered = text.lower()
    for phrase, days in STORAGE.items():
        if has_word(lowered, phrase):
            return days
    matches = [phrase for phrase in SHELF_LIFE if has_word(lowered, phrase)]
    if not matches:
        return DEFAULT_SHELF_LIFE
    return SHELF_LIFE[max(matches, key=len)]


def expiry(text: str, today: date) -> str | None:
    days = shelf_life(text)
    return None if days is None else (today + timedelta(days=days)).isoformat()


def name_of(phrase: str) -> str:
    """The food a phrase names, without its amount: "2 lbs chicken thighs" is "Chicken thighs"."""
    words = phrase.split()
    while words and (words[0].lower() in UNITS or re.fullmatch(r"[\d/.½¼¾]+%?x?", words[0])):
        words.pop(0)
    name = " ".join(words) or phrase
    return name[:1].upper() + name[1:]


def leading_count(text: str) -> tuple[int, str] | None:
    """The count a phrase starts with and the rest of it: "a dozen eggs" is (12, "eggs")."""
    lowered = text.strip().lower()
    match = re.match(r"(\d+)[\s,]+(.*)", lowered)
    if match:
        return int(match.group(1)), match.group(2)
    for words in sorted(NUMBER_WORDS, key=len, reverse=True):
        if lowered.startswith(words + " "):
            return NUMBER_WORDS[words], lowered[len(words) + 1 :]
    return None


MEASURES = UNITS | {"tablespoon", "tablespoons", "teaspoon", "teaspoons", "handful", "handfuls"}


def countable(have: tuple[int, str], used: tuple[int, str]) -> bool:
    """Whether a used amount can be subtracted from what is there: "3 eggs" from "12 eggs", not "2 cups"."""
    unit = used[1].split()[0] if used[1].split() else ""
    return unit not in MEASURES or (have[1].split() or [""])[0] == unit


def mentions(text: str, item: PantryItem) -> int:
    """How clearly `text` names `item`: 2 for its full name, 1 for one of its words, 0 for neither."""
    lowered = re.sub(r"[^a-z0-9 ]", " ", text.lower())

    def said(word: str) -> bool:
        word = word.rstrip("s")
        return len(word) > 2 and re.search(rf"\b{re.escape(word)}(?:s|es)?\b", lowered) is not None

    name = re.sub(r"[^a-z0-9 ]", " ", item.name.lower()).strip()
    if said(name):
        return 2
    return 1 if any(said(word) for word in name.split() if word not in UNITS) else 0


def named(text: str, pantry: list[PantryItem], exclude: frozenset[int] = frozenset()) -> list[PantryItem]:
    """The pantry items `text` names, preferring items named in full over items named in part."""
    scores = {item.id: mentions(text, item) for item in pantry if item.id not in exclude}
    best = max(scores.values(), default=0)
    return [item for item in pantry if best and scores.get(item.id) == best]


def with_note(description: str, note: str) -> str:
    """The description with a short note about its current state, replacing any earlier note."""
    base = description.split(" — ")[0].strip()
    return f"{base} — {note}" if base else note[:1].upper() + note[1:]


def days_left(item: PantryItem, today: date) -> int | None:
    if not item.expires_on:
        return None
    try:
        return (date.fromisoformat(item.expires_on) - today).days
    except ValueError:
        return None


@dataclass(frozen=True)
class Ingredient:
    words: tuple[str, ...]
    label: str
    amount: str
    optional: bool = False


def need(label: str, amount: str, *words: str, optional: bool = False) -> Ingredient:
    return Ingredient(words or (label,), label, amount, optional)


@dataclass(frozen=True)
class Template:
    title: str
    summary: str
    minutes: int
    tags: frozenset[str]
    ingredients: tuple[Ingredient, ...]
    steps: tuple[str, ...]
    aliases: tuple[str, ...] = ()


def template(title, summary, minutes, tags, ingredients, steps, aliases=()) -> Template:
    return Template(title, summary, minutes, frozenset(tags.split()), tuple(ingredients), tuple(steps), aliases)


LIBRARY = (
    template(
        "Spinach and Cheddar Omelette",
        "A soft, folded omelette with wilted spinach and sharp melted cheddar.",
        10,
        "quick tired breakfast cozy vegetarian",
        [
            need("eggs", "3 eggs", "egg"),
            need("spinach", "a big handful"),
            need("cheddar", "a small handful, grated", "cheddar", "cheese"),
            need("butter", "a knob", optional=True),
        ],
        [
            "Whisk the eggs with a pinch of salt and pepper.",
            "Melt the butter (or a little oil) in a nonstick pan over medium heat.",
            "Wilt the spinach in the pan for a minute, then pour in the eggs.",
            "Stir gently until just set at the edges, then scatter over the cheddar.",
            "Fold the omelette in half and slide it onto a plate.",
        ],
        ("omelet", "omelette"),
    ),
    template(
        "Creamy Garlic Chicken Thighs",
        "Golden chicken thighs in a garlicky cream sauce with spinach stirred through.",
        30,
        "cozy comfort dinner celebrate",
        [
            need("chicken", "the chicken thighs", "chicken"),
            need("garlic", "4 cloves, sliced"),
            need("cream", "about a cup", "cream", "milk"),
            need("spinach", "a couple of handfuls", optional=True),
            need("parmesan", "a handful, grated", optional=True),
        ],
        [
            "Season the chicken thighs well with salt and pepper.",
            "Sear them skin-side down in a hot oiled pan until deep golden, then flip and cook through.",
            "Move the chicken to a plate and soften the garlic in the pan for a minute.",
            "Pour in the cream, scrape up the browned bits, and simmer until it thickens slightly.",
            "Stir in the spinach and parmesan if you have them, then return the chicken to the sauce.",
        ],
        ("garlic chicken", "creamy chicken"),
    ),
    template(
        "Weeknight Fried Rice",
        "Crispy rice tossed with egg, vegetables, and a splash of soy.",
        20,
        "quick tired dinner",
        [
            need("rice", "2 cups cooked", "rice"),
            need("eggs", "2 eggs", "egg"),
            need("soy sauce", "2 tablespoons"),
            need("carrot", "1, diced", "carrot", "pea", "corn", optional=True),
            need("green onion", "2, sliced", "green onion", "scallion", optional=True),
            need("chicken", "any leftovers, diced", "chicken", optional=True),
        ],
        [
            "Heat a large pan or wok with a good splash of oil until very hot.",
            "Scramble the eggs quickly, then push them to one side.",
            "Add the vegetables and any chicken and stir-fry for 2 minutes.",
            "Add the rice and press it into the pan so it crisps, tossing every minute.",
            "Season with soy sauce, toss everything together, and top with green onion.",
        ],
        ("fried rice",),
    ),
    template(
        "Tomato Basil Pasta",
        "Bright, quick pasta with burst tomatoes, garlic, and fresh basil.",
        20,
        "quick vegetarian dinner",
        [
            need("pasta", "about 200 g", "pasta", "spaghetti", "penne", "noodle"),
            need("tomatoes", "2 cups, halved", "tomato"),
            need("garlic", "3 cloves"),
            need("basil", "a handful", optional=True),
            need("parmesan", "to serve", "parmesan", optional=True),
        ],
        [
            "Boil the pasta in well-salted water until al dente; save a cup of the water.",
            "Meanwhile, warm oil in a wide pan and soften the garlic.",
            "Add the tomatoes and cook until they burst and turn saucy.",
            "Toss in the drained pasta with a splash of pasta water.",
            "Finish with torn basil and grated parmesan.",
        ],
        ("tomato pasta", "pasta pomodoro"),
    ),
    template(
        "Cheesy Bean Quesadillas",
        "Crisp tortillas with melted cheddar and smashed beans.",
        15,
        "quick tired lunch vegetarian",
        [
            need("tortillas", "4", "tortilla"),
            need("cheddar", "a big handful, grated", "cheddar", "cheese"),
            need("beans", "1 can, drained", "beans", "chicken"),
            need("salsa", "to serve", "salsa", optional=True),
        ],
        [
            "Mash the beans roughly with a pinch of salt.",
            "Spread beans over half of each tortilla and top with cheese.",
            "Fold and cook in a dry pan over medium heat until golden on both sides.",
            "Cut into wedges and serve with salsa.",
        ],
        ("quesadilla",),
    ),
    template(
        "Vegetable Stir-Fry",
        "Crisp-tender vegetables in a glossy garlic-soy sauce over rice.",
        20,
        "healthy quick vegetarian dinner",
        [
            need("broccoli", "1 head, in florets"),
            need("bell pepper", "1, sliced", "bell pepper"),
            need("carrot", "1, sliced", "carrot", optional=True),
            need("garlic", "2 cloves"),
            need("soy sauce", "3 tablespoons"),
            need("rice", "to serve", "rice", optional=True),
        ],
        [
            "Get the rice going if you are serving it.",
            "Heat oil in a wok or large pan until shimmering.",
            "Stir-fry the firmest vegetables first, then the rest, keeping them crisp.",
            "Add the garlic for 30 seconds, then the soy sauce and a splash of water.",
            "Toss until glossy and serve over rice.",
        ],
        ("stir fry", "stir-fry"),
    ),
    template(
        "Hearty Chicken Noodle Soup",
        "A slow-simmered, soul-warming bowl of chicken, vegetables, and noodles.",
        45,
        "cozy comfort sick dinner",
        [
            need("chicken", "the chicken", "chicken"),
            need("carrots", "2, sliced", "carrot"),
            need("celery", "2 stalks, sliced", optional=True),
            need("onion", "1, diced", "onion"),
            need("noodles", "a big handful", "noodle", "pasta"),
            need("broth", "6 cups", "broth", "stock"),
        ],
        [
            "Soften the onion, carrot, and celery in a little oil in a large pot.",
            "Add the chicken and broth and bring to a gentle simmer for 20 minutes.",
            "Lift out the chicken, shred it, and return it to the pot.",
            "Add the noodles and cook until tender.",
            "Season well with salt and pepper and serve hot.",
        ],
        ("chicken soup", "noodle soup"),
    ),
    template(
        "Shakshuka",
        "Eggs gently poached in a spiced tomato and pepper sauce.",
        30,
        "cozy brunch vegetarian healthy",
        [
            need("eggs", "4 eggs", "egg"),
            need("tomatoes", "1 can or 4 fresh", "tomato"),
            need("onion", "1, sliced", "onion"),
            need("bell pepper", "1, sliced", "bell pepper", optional=True),
            need("garlic", "2 cloves"),
            need("feta", "to crumble over", "feta", optional=True),
        ],
        [
            "Soften the onion and pepper in oil in a deep pan.",
            "Add the garlic and a pinch of cumin or paprika if you have it.",
            "Pour in the tomatoes and simmer until thick, about 10 minutes.",
            "Make wells in the sauce, crack in the eggs, cover, and cook until the whites set.",
            "Crumble over feta and serve with bread.",
        ],
        ("shakshouka",),
    ),
    template(
        "Banana Pancakes",
        "Fluffy, golden pancakes with sweet banana folded through.",
        20,
        "breakfast celebrate cozy vegetarian",
        [
            need("bananas", "2 ripe", "banana"),
            need("eggs", "2 eggs", "egg"),
            need("flour", "1 cup"),
            need("milk", "3/4 cup", "milk"),
            need("butter", "for the pan", optional=True),
        ],
        [
            "Mash the bananas well in a bowl.",
            "Whisk in the eggs and milk, then fold in the flour with a pinch of salt.",
            "Heat a buttered pan over medium heat.",
            "Cook small pancakes until bubbles form, then flip until golden.",
            "Serve warm, stacked high.",
        ],
        ("pancake",),
    ),
    template(
        "Greek Salad",
        "Crunchy cucumber, ripe tomato, and salty feta in a sharp dressing.",
        10,
        "healthy quick light lunch vegetarian",
        [
            need("cucumber", "1, chunked"),
            need("tomatoes", "3, in wedges", "tomato"),
            need("feta", "a block, crumbled"),
            need("onion", "half, thinly sliced", "onion", optional=True),
            need("olives", "a handful", optional=True),
            need("lemon", "half, juiced", "lemon", optional=True),
        ],
        [
            "Chop the cucumber and tomatoes into big, rustic pieces.",
            "Add the onion and olives.",
            "Dress with oil, lemon juice, salt, and pepper.",
            "Top with the feta and toss gently just before eating.",
        ],
        ("salad",),
    ),
    template(
        "Lemon Garlic Salmon with Asparagus",
        "Tender roast salmon and asparagus on one tray, bright with lemon.",
        25,
        "healthy celebrate dinner light",
        [
            need("salmon", "2 fillets"),
            need("asparagus", "a bunch", "asparagus", "broccoli", "green beans"),
            need("lemon", "1"),
            need("garlic", "2 cloves, minced"),
        ],
        [
            "Heat the oven to 200°C / 400°F.",
            "Toss the asparagus with oil, salt, and pepper on a tray.",
            "Nestle in the salmon, top with garlic and lemon slices.",
            "Roast for 12 to 15 minutes until the salmon flakes.",
            "Squeeze over more lemon to serve.",
        ],
        ("salmon",),
    ),
    template(
        "Mushroom Risotto",
        "Slow-stirred, creamy rice with earthy mushrooms and parmesan.",
        40,
        "cozy comfort celebrate vegetarian dinner",
        [
            need("rice", "1 1/2 cups", "rice"),
            need("mushrooms", "a box, sliced", "mushroom"),
            need("onion", "1, finely diced", "onion"),
            need("parmesan", "a big handful, grated", "parmesan"),
            need("broth", "5 cups, warm", "broth", "stock"),
            need("butter", "a knob", optional=True),
        ],
        [
            "Brown the mushrooms in a hot oiled pan and set aside.",
            "Soften the onion in the same pan, then stir in the rice to toast it.",
            "Add the warm broth a ladle at a time, stirring until each is absorbed.",
            "After about 20 minutes, when the rice is creamy and just tender, stir in the mushrooms.",
            "Finish with butter and parmesan and let it rest a minute.",
        ],
        ("risotto",),
    ),
    template(
        "Black Bean Tacos",
        "Smoky black beans with creamy avocado and a squeeze of lime.",
        20,
        "quick healthy vegetarian dinner",
        [
            need("tortillas", "6 small", "tortilla"),
            need("black beans", "1 can, drained", "beans"),
            need("avocado", "1, sliced"),
            need("lime", "1", optional=True),
            need("onion", "a little, diced", "onion", optional=True),
            need("salsa", "to serve", "salsa", "tomato", optional=True),
        ],
        [
            "Warm the beans in a pan with a pinch of salt and any spices you like.",
            "Warm the tortillas in a dry pan.",
            "Fill each tortilla with beans and avocado.",
            "Top with onion and salsa and finish with lime.",
        ],
        ("taco",),
    ),
    template(
        "Grilled Cheese and Tomato Soup",
        "The classic pair: crisp, buttery grilled cheese for dunking in hot tomato soup.",
        20,
        "cozy comfort tired lunch vegetarian",
        [
            need("bread", "4 slices"),
            need("cheddar", "4 slices or a big handful", "cheddar", "cheese"),
            need("butter", "for the bread"),
            need("tomatoes", "1 can or 5 fresh", "tomato"),
        ],
        [
            "Simmer the tomatoes with a pinch of salt and a splash of water for 10 minutes, then blend or mash.",
            "Butter the outside of each slice of bread.",
            "Sandwich the cheese between the slices, butter facing out.",
            "Cook in a pan over medium-low heat until golden and melted, flipping once.",
            "Cut and serve with the soup for dunking.",
        ],
        ("grilled cheese", "tomato soup"),
    ),
    template(
        "Avocado Toast with a Fried Egg",
        "Crisp toast, smashed avocado, and a runny fried egg.",
        10,
        "quick healthy breakfast tired",
        [
            need("bread", "2 slices"),
            need("avocado", "1"),
            need("eggs", "2 eggs", "egg"),
            need("lemon", "a squeeze", "lemon", "lime", optional=True),
        ],
        [
            "Toast the bread.",
            "Mash the avocado with salt, pepper, and a squeeze of lemon.",
            "Fry the eggs in a little oil until the whites are set.",
            "Pile the avocado onto the toast and top each with an egg.",
        ],
        ("avocado toast",),
    ),
    template(
        "Yogurt Parfait",
        "Cool yogurt layered with fruit and something crunchy.",
        5,
        "quick healthy light breakfast",
        [
            need("yogurt", "1 cup"),
            need("fruit", "a handful", "berries", "strawberr", "blueberr", "banana"),
            need("oats", "a handful", "oats", "granola", optional=True),
            need("honey", "a drizzle", optional=True),
        ],
        [
            "Spoon a layer of yogurt into a glass or bowl.",
            "Add a layer of fruit and a sprinkle of oats.",
            "Repeat the layers.",
            "Finish with a drizzle of honey.",
        ],
        ("parfait",),
    ),
    template(
        "Steak with Garlic Butter Potatoes",
        "A properly seared steak with crispy, garlicky potatoes.",
        40,
        "celebrate dinner",
        [
            need("steak", "1 to 2 steaks", "steak", "beef"),
            need("potatoes", "4, in chunks", "potato"),
            need("garlic", "4 cloves, smashed"),
            need("butter", "3 tablespoons"),
        ],
        [
            "Boil the potatoes in salted water for 8 minutes, then drain and steam dry.",
            "Fry the potatoes in oil until crisp and golden on all sides.",
            "Season the steak generously and sear it in a very hot pan, about 3 minutes a side.",
            "Add the butter and garlic and spoon the foaming butter over the steak.",
            "Rest the steak for 5 minutes, then slice and serve with the potatoes.",
        ],
        ("steak",),
    ),
    template(
        "Spaghetti Carbonara",
        "Silky Roman pasta with egg, crisp bacon, and plenty of cheese.",
        25,
        "cozy comfort celebrate dinner",
        [
            need("spaghetti", "about 200 g", "spaghetti", "pasta"),
            need("eggs", "3 eggs", "egg"),
            need("bacon", "4 strips, chopped", "bacon", "pancetta"),
            need("parmesan", "a big handful, grated", "parmesan"),
        ],
        [
            "Boil the spaghetti in well-salted water; save a cup of the water.",
            "Crisp the bacon in a wide pan, then take it off the heat.",
            "Whisk the eggs with the parmesan and lots of black pepper.",
            "Toss the hot drained pasta with the bacon, then the egg mixture, adding pasta water to make it silky.",
            "Serve straight away with more cheese.",
        ],
        ("carbonara",),
    ),
)

MOODS = {
    "tired": (
        ("tired", "exhausted", "long day", "worn out", "lazy", "no energy", "drained"),
        "Sounds like a long one, so let's keep it easy.",
    ),
    "cozy": (
        ("cozy", "comfort", "warm", "cold", "rainy", "hug", "soothing"),
        "Something warm and comforting coming right up.",
    ),
    "healthy": (("healthy", "light", "fresh", "clean", "salad", "veggie"), "Let's keep it fresh and light."),
    "quick": (("quick", "fast", "hurry", "minutes", "no time", "busy"), "Let's make it quick."),
    "celebrate": (
        ("celebrate", "special", "date", "fancy", "treat", "party", "impress"),
        "Ooh, a reason to make it a little special.",
    ),
}


MEATLESS = ("vegetarian", "vegan", "no meat", "meatless", "plant-based", "plant based")
AVOIDING = re.compile(r"\b(?:allergic to|allergy to|no|avoid|avoids|don't eat|dont eat|can't eat|hate)\s+([a-z ]+)")


def allowed(recipe: Template, text: str) -> bool:
    """Whether a recipe respects what the user says about their diet, like "vegetarian" or "allergic to eggs"."""
    lowered = text.lower()
    if any(word in lowered for word in MEATLESS) and "vegetarian" not in recipe.tags:
        return False
    avoided = {word.rstrip("s") for match in AVOIDING.finditer(lowered) for word in match.group(1).split()}
    avoided -= UNITS | {"time", "oven", "stove", "meat", "more", "than", "and", "or", "too", "much", "spicy"}
    return not any(
        avoid in word or avoid in ingredient.label
        for ingredient in recipe.ingredients
        if not ingredient.optional
        for word in ingredient.words
        for avoid in avoided
        if len(avoid) > 2
    )


def moods_in(text: str) -> list[str]:
    lowered = text.lower()
    return [mood for mood, (words, _) in MOODS.items() if any(word in lowered for word in words)]


def time_limit(text: str) -> int | None:
    match = re.search(r"(?:under|less than|within|in)\s+(\d+)\s*(?:min|minutes)", text.lower())
    return int(match.group(1)) if match else None


def join(words: list[str]) -> str:
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + f" and {words[-1]}"


def turns_phrase(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


class Mock(LLM):
    name = "mock"

    def __init__(self, delay: float = 0.03):
        self.delay = delay

    def parse_items(self, text: str, today: date) -> list[ParsedItem]:
        items = []
        for piece in SPLITTER.split(text):
            phrase = LEAD_INS.sub("", piece.strip(" .!?:-")).strip(" .!?:-")
            if not phrase or not re.search(r"[a-zA-Z]", phrase):
                continue
            detail = re.search(r"\s*\(([^)]*)\)", phrase)
            food = (phrase[: detail.start()] + phrase[detail.end() :]).strip() if detail else phrase
            name = name_of(food)
            parts = [food] if food.lower() != name.lower() else []
            parts += [detail.group(1).strip()] if detail and detail.group(1).strip() else []
            description = ", ".join(parts)
            description = description[:1].upper() + description[1:]
            items.append(ParsedItem(name=name, description=description, expires_on=expiry(phrase, today)))
        return items

    def build(self, recipe: Template, pantry: list[PantryItem], today: date) -> tuple[Recipe, float]:
        """The template filled in from the pantry, and how well it fits."""
        usable = [item for item in pantry if (days_left(item, today) or 0) >= 0]
        uses, missing, used_ids, urgency, covered = [], [], set(), 0.0, 0
        for ingredient in recipe.ingredients:
            matches = [
                item
                for item in usable
                if item.id not in used_ids and any(has_word(item.name.lower(), word) for word in ingredient.words)
            ]
            matches.sort(key=lambda item: (days_left(item, today) is None, days_left(item, today) or 0, item.id))
            if matches:
                item = matches[0]
                used_ids.add(item.id)
                uses.append(RecipeUse(item_id=item.id, name=item.name, amount=ingredient.amount))
                covered += not ingredient.optional
                left = days_left(item, today)
                if left is not None and left <= 3:
                    urgency += (4 - left) * 0.25
            elif not ingredient.optional:
                missing.append(ingredient.label)
        required = sum(1 for ingredient in recipe.ingredients if not ingredient.optional)
        score = covered / required + urgency + 0.15 * len(uses) - 0.4 * len(missing)
        return (
            Recipe(
                title=recipe.title,
                summary=recipe.summary,
                time_minutes=recipe.minutes,
                uses=uses,
                missing=missing,
                steps=list(recipe.steps),
                why=self.why(uses, missing, pantry, today),
            ),
            score,
        )

    def why(self, uses: list[RecipeUse], missing: list[str], pantry: list[PantryItem], today: date) -> str:
        by_id = {item.id: item for item in pantry}
        soon = [
            (days_left(by_id[use.item_id], today), by_id[use.item_id].name.lower())
            for use in uses
            if (days_left(by_id[use.item_id], today) is not None) and days_left(by_id[use.item_id], today) <= 3
        ]
        if soon:
            soon.sort()
            names = [name for _, name in soon]
            pronoun = "it turns" if len(names) == 1 else "they turn"
            return f"Uses your {join(names)} before {pronoun} {turns_phrase(soon[0][0])}."
        if not uses:
            return "You'd need to shop for this one."
        if not missing:
            return f"You have everything: it uses {len(uses)} things already in your kitchen."
        return f"Uses {len(uses)} things you already have."

    def suggest_recipes(
        self, pantry: list[PantryItem], today: date, preferences: str = "", notes: str = ""
    ) -> list[Recipe]:
        if not pantry:
            return []
        wanted = set(moods_in(preferences))
        limit = time_limit(preferences)
        if limit and limit <= 20:
            wanted.add("quick")
        scored = []
        for recipe in LIBRARY:
            if not allowed(recipe, f"{preferences} {notes}"):
                continue
            built, score = self.build(recipe, pantry, today)
            if not built.uses or len(built.missing) > 2:
                continue
            score += 0.5 * len(wanted & recipe.tags)
            if limit and recipe.minutes > limit:
                score -= 1.0
            scored.append((-score, recipe.title, built))
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        return [built for _, _, built in scored[:4]]

    def plan_recipe(self, dish: str, pantry: list[PantryItem], today: date, notes: str = "") -> Recipe:
        lowered = dish.lower()
        for recipe in LIBRARY:
            names = (recipe.title.lower(), *recipe.aliases)
            if any(name in lowered or lowered in name for name in names):
                built, _ = self.build(recipe, pantry, today)
                if built.missing:
                    built.why = f"You'd need to pick up {join(built.missing)}."
                else:
                    built.why = "Good news: you have everything you need."
                return built
        title = dish.strip().rstrip("?.!")
        title = title[:1].upper() + title[1:]
        uses = [RecipeUse(item_id=item.id, name=item.name, amount="as needed") for item in named(dish, pantry)]
        return Recipe(
            title=title,
            summary=f"A simple, homestyle take on {title.lower()}.",
            time_minutes=30,
            uses=uses,
            missing=[],
            steps=[
                "Gather and prep your ingredients.",
                "Cook the main components over medium heat until done, seasoning as you go.",
                "Taste, adjust the seasoning, and serve.",
            ],
            why="I don't know this one well, so check the ingredients against a trusted recipe.",
        )

    def tweak_recipe(
        self, recipe: Recipe, feedback: str, pantry: list[PantryItem], today: date, notes: str = ""
    ) -> Recipe:
        revised = recipe.model_copy(deep=True)
        lowered = feedback.lower()
        changes = []
        if any(word in lowered for word in ("quick", "faster", "less time", "shorter", "speed")):
            revised.time_minutes = max(5, round(recipe.time_minutes * 0.6))
            changes.append("made it faster")
        if "spic" in lowered or "heat" in lowered or "kick" in lowered:
            chili = next(
                (item for item in pantry if "chili" in item.name.lower() or "jalape" in item.name.lower()),
                None,
            )
            if chili:
                revised.uses.append(RecipeUse(item_id=chili.id, name=chili.name, amount="to taste"))
            elif "chili flakes" not in revised.missing:
                revised.missing.append("chili flakes")
            revised.steps.append("Finish with chili flakes or hot sauce for heat.")
            if not revised.title.lower().startswith("spicy"):
                revised.title = f"Spicy {revised.title}"
            changes.append("added some heat")
        if any(word in lowered for word in ("vegetarian", "vegan", "no meat", "meatless")):
            revised.uses = [use for use in revised.uses if not any(meat in use.name.lower() for meat in MEATS)]
            revised.missing = [name for name in revised.missing if not any(meat in name.lower() for meat in MEATS)]
            revised.steps = [step for step in revised.steps if not any(meat in step.lower() for meat in MEATS)]
            if "vegetarian" not in revised.title.lower():
                revised.title = f"Vegetarian {revised.title}"
            changes.append("made it vegetarian")
        for match in re.finditer(
            r"\b(?:without|no|skip|leave out|out of|don't have|dont have)\s+(?:the\s+)?([a-z ]+?)(?:[,.;!]|\band\b|$)",
            lowered,
        ):
            target = match.group(1).strip()
            if target in ("meat", "time") or not target:
                continue
            singular = target.rstrip("s")
            before = len(revised.uses) + len(revised.missing)
            revised.uses = [use for use in revised.uses if singular not in use.name.lower()]
            revised.missing = [name for name in revised.missing if singular not in name.lower()]
            if len(revised.uses) + len(revised.missing) < before:
                revised.steps.append(f"Leave out the {target}; the dish holds up without it.")
                changes.append(f"dropped the {target}")
        if any(word in lowered for word in ("healthier", "lighter", "less fat", "less butter")):
            revised.steps.append("Go easy on the butter and oil, and add extra vegetables if you have them.")
            changes.append("lightened it up")
        if not changes:
            revised.steps.append(f"Adjust to taste: {feedback.strip()}.")
            changes.append("noted your feedback")
        revised.why = f"Tweaked for you: {join(changes)}."
        return revised

    def apply_cooking(self, recipe: Recipe, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        by_id = {item.id: item for item in pantry}
        ops = []
        for use in recipe.uses:
            item = by_id.get(use.item_id)
            if item is None:
                continue
            amount = use.amount.lower()
            have, used = leading_count(item.description), leading_count(use.amount)
            if amount.startswith("the ") or re.search(r"\b(?:all|whole|entire)\b", amount):
                ops.append(PantryOp(op="delete", item_id=item.id))
            elif have and used and countable(have, used):
                left = have[0] - used[0]
                if left <= 0:
                    ops.append(PantryOp(op="delete", item_id=item.id))
                else:
                    ops.append(PantryOp(op="update", item_id=item.id, description=f"{left} {have[1]}"))
            elif any(note in item.description.lower() for note in ("partly used", "a little left", "almost gone")):
                ops.append(PantryOp(op="delete", item_id=item.id))
            else:
                ops.append(
                    PantryOp(op="update", item_id=item.id, description=with_note(item.description, "partly used"))
                )
        return ops

    def adjust_pantry(self, instruction: str, pantry: list[PantryItem], today: date) -> list[PantryOp]:
        ops: list[PantryOp] = []
        touched: set[int] = set()
        verb = ""
        for clause in re.split(r"\s*(?:[,;.!]|\band\b|\bbut\b|\bthen\b)\s*", instruction):
            lowered = clause.lower().strip()
            if not lowered:
                continue
            action = adjustment(lowered) or (adjustment(f"{verb} {lowered}") if verb else None)
            verb = next((word for word in VERBS if word in lowered), verb)
            items = named(lowered, pantry, frozenset(touched))
            for item in items:
                touched.add(item.id)
                if op := self.adjusted(item, action, lowered, today):
                    ops.append(op)
            if not items and action in ("add", "more"):
                for parsed in self.parse_items(clause, today):
                    ops.append(
                        PantryOp(
                            op="add",
                            name=parsed.name,
                            description=parsed.description,
                            expires_on=parsed.expires_on,
                        )
                    )
        return ops

    def adjusted(self, item: PantryItem, action: str | None, clause: str, today: date) -> PantryOp | None:
        def update(note: str, **changes) -> PantryOp:
            return PantryOp(op="update", item_id=item.id, description=with_note(item.description, note), **changes)

        match action:
            case "gone":
                return PantryOp(op="delete", item_id=item.id)
            case "frozen":
                return update("frozen", expires_on=(today + timedelta(days=90)).isoformat())
            case "count":
                count = re.search(COUNT_LEFT, clause).group(1)
                have = leading_count(item.description)
                noun = have[1] if have else item.name.lower()
                return PantryOp(op="update", item_id=item.id, description=f"{count} {noun}")
            case "half":
                return update("about half left")
            case "low":
                return update("running low")
            case "add":
                return update("restocked", expires_on=expiry(item.name, today))
            case "more":
                return update("plenty left")
            case "some":
                return update("partly used")
        return None

    def chat(
        self,
        history: list[ChatTurn],
        message: str,
        pantry: list[PantryItem],
        shopping: list[ShoppingEntry],
        today: date,
        notes: str = "",
    ) -> Iterator[str]:
        for index, word in enumerate(self.reply(message, pantry, shopping, today, notes).split(" ")):
            if self.delay:
                time.sleep(self.delay)
            yield f" {word}" if index else word

    def reply(
        self, message: str, pantry: list[PantryItem], shopping: list[ShoppingEntry], today: date, notes: str = ""
    ) -> str:
        lowered = message.lower()
        if not pantry:
            return (
                "Your pantry is empty right now, so I don't have much to work with. Tell me what you picked up, "
                'something like "eggs, spinach and cheddar", and I\'ll find you something good to cook.'
            )
        expired = [item.name.lower() for item in pantry if (days_left(item, today) or 0) < 0]
        soon = sorted(
            (item for item in pantry if days_left(item, today) is not None and 0 <= days_left(item, today) <= 3),
            key=lambda item: (days_left(item, today), item.id),
        )
        if any(word in lowered for word in ("expir", "use soon", "going bad", "go bad", "use up")):
            if not soon:
                return "Nothing is about to expire, so you're in good shape. Want a recipe idea anyway?"
            listed = join([f"{item.name.lower()} ({turns_phrase(days_left(item, today))})" for item in soon])
            return f"Here's what to use soon: {listed}. Want me to build a meal around them?"
        if any(word in lowered for word in ("shopping", "buy", "store", "grocer")):
            needed = [entry.name.lower() for entry in shopping if not entry.checked]
            if needed:
                return f"Your shopping list has {join(needed)}. Anything you want me to add for tonight's dinner?"
            return "Your shopping list is empty. Tell me what you're planning and I'll help you figure out what to buy."
        sentences = []
        moods = moods_in(message)
        if moods:
            sentences.append(MOODS[moods[0]][1])
        elif re.match(r"^\s*(hi|hello|hey|yo)\b", lowered):
            sentences.append("Hi! I can see what's in your kitchen.")
        ideas = self.suggest_recipes(pantry, today, message, notes)
        if ideas:
            top = ideas[0]
            used = join([use.name.lower() for use in top.uses[:3]])
            line = f"How about {top.title.lower()}? It takes about {top.time_minutes} minutes and uses your {used}"
            line += f", and you'd just need {join(top.missing)}." if top.missing else ", so you have everything."
            sentences.append(line)
            if len(ideas) > 1:
                sentences.append(f"If that doesn't grab you, {ideas[1].title.lower()} is another good fit.")
        elif soon:
            sentences.append(f"Your {soon[0].name.lower()} needs using {turns_phrase(days_left(soon[0], today))}.")
        else:
            names = join([item.name.lower() for item in pantry[:3]])
            sentences.append(
                f"I see {names} in your kitchen. Tell me what you're craving and I'll shape a meal around it."
            )
        if soon and ideas and not any(use.item_id == soon[0].id for use in ideas[0].uses):
            sentences.append(
                f"Keep in mind your {soon[0].name.lower()} turns {turns_phrase(days_left(soon[0], today))}."
            )
        if expired:
            sentences.append(f"Also, your {join(expired)} is past its date, so it's probably time to toss it.")
        return " ".join(sentences)
