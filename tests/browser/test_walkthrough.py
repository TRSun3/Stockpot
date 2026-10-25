"""The demo, end to end in Chrome against a live server: every flow a person would click through.

Screenshots of each step land in `screenshots/` for looking over by eye.
"""

import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import expect

from stockpot import db, seed

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "screenshots"


def stop(process: subprocess.Popen) -> None:
    """Stops the server and anything it started; on Windows the venv's python.exe is a launcher with a child."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    path = tmp_path_factory.mktemp("browser") / "stockpot.db"
    db.init(path)
    with closing(db.connect(path)) as conn:
        seed.seed(conn, date.today())
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "STOCKPOT_DB": str(path), "STOCKPOT_LLM": "mock"}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "stockpot.main:app", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield url
    stop(process)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        yield browser
        browser.close()


@pytest.fixture
def windows(browser, server):
    """Opens fresh browser contexts, each like its own private window. Any page error in any of them fails the test."""
    contexts, problems = [], []

    def open_window(width=1440, height=900, **options):
        context = browser.new_context(base_url=server, viewport={"width": width, "height": height}, **options)
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda error: problems.append(str(error)))
        page.on(
            "console",
            lambda message: message.type == "error" and not expected(message.text) and problems.append(message.text),
        )
        page.on("dialog", lambda dialog: problems.append(f"unexpected dialog: {dialog.message}") or dialog.dismiss())
        return page

    yield open_window
    for context in contexts:
        context.close()
    assert problems == []


@pytest.fixture
def window(windows):
    return windows()


def expected(console_text):
    """The browser logs every 401 itself; the page asks /api/me before anyone logs in and gets one."""
    return "status of 401" in console_text


def shot(page, name):
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=SHOTS / f"{name}.png", full_page=True)


def log_in(page, username):
    page.goto("/")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(seed.PASSWORD)
    page.get_by_role("button", name="Log in").click()
    page.locator("#pantry-list .item").first.wait_for()


def pantry_names(page):
    return page.locator("#pantry-list .item-name").all_text_contents()


def test_the_pantry_flows_from_login_to_logout(window):
    page = window
    page.goto("/")
    page.get_by_role("heading", name="Log in to Stockpot").wait_for()
    shot(page, "01-login")

    log_in(page, "neal")
    assert page.locator("#username").text_content() == "neal"
    assert page.locator("#mock-badge").is_visible()
    soon = page.locator("#soon-list")
    for text in ("Spinach", "Greek yogurt", "Expired 1 day ago"):
        expect(soon).to_contain_text(text)
    shot(page, "02-kitchen")

    toggle = page.locator("#soon-toggle")
    toggle.click()
    expect(soon).to_be_hidden()
    expect(page.locator("#soon-count")).not_to_be_empty()
    page.reload()
    page.locator("#pantry-list .item").first.wait_for()
    expect(soon).to_be_hidden()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    toggle.click()
    expect(soon).to_be_visible()

    entry = page.get_by_label("What did you bring home?")
    for grocery in ("a dozen eggs", "a bag of spinach", "a tub of lard", "chicken thighs", "some cheddar"):
        entry.fill(grocery)
        entry.press("Enter")
    staged = page.locator("#staged-list .staged-item")
    expect(staged).to_have_count(5)
    page.get_by_role("button", name="Remove a tub of lard").click()
    expect(staged.locator("span")).to_have_text(["a dozen eggs", "a bag of spinach", "chicken thighs", "some cheddar"])
    held = []
    page.route("**/api/items/parse", lambda route: held.append(route))
    page.get_by_role("button", name="Add to pantry").click()
    page.wait_for_function("() => document.querySelector('#parse-form [type=submit]').disabled")
    entry.fill("a bag of rice")
    entry.press("Enter")
    held[0].continue_()
    page.unroute("**/api/items/parse")
    page.locator(".toast", has_text="Added eggs, spinach, chicken thighs, cheddar").wait_for()
    expect(page.locator("#pantry-list .item-name", has_text="Spinach")).to_have_count(1)
    expect(page.locator("#pantry-list .item-name", has_text="Eggs")).to_have_count(1)
    expect(staged.locator("span")).to_have_text(["a bag of rice"])
    page.get_by_role("button", name="Remove a bag of rice").click()
    expect(page.locator("#staged-list")).to_be_hidden()

    milk = page.locator("#pantry-list .item", has_text="Milk")
    milk.locator("button", has_text="Edit").click()
    page.locator(".edit-form [name=description]").fill("a full gallon, just opened")
    page.locator(".edit-form").get_by_role("button", name="Save").click()
    page.locator("#pantry-list .item", has_text="a full gallon, just opened").wait_for()

    page.get_by_label("What changed?").fill("I used half the milk and the avocados went bad")
    page.get_by_role("button", name="Update pantry").click()
    page.locator("#adjust-result", has_text="Updated milk, removed avocados").wait_for()
    expect(page.locator("#pantry-list .item-name", has_text="Avocados")).to_have_count(0)

    page.locator("#pantry-list .item", has_text="Sourdough").locator("button", has_text="Used up").press("Enter")
    removed = page.locator(".toast", has_text="Removed sourdough")
    expect(removed.get_by_role("button", name="Add to shopping list")).to_be_focused()
    page.keyboard.press("Enter")
    page.locator(".toast", has_text="Added sourdough to your shopping list").wait_for()
    expect(removed).to_have_count(0)

    yogurt = page.locator("#pantry-list .item", has_text="Greek yogurt")
    yogurt.locator("button", has_text="Toss").click()
    expect(yogurt).to_have_count(0)
    tossed = page.locator(".toast", has_text="Removed greek yogurt")
    expect(tossed.locator("button")).to_have_text(["Add to shopping list", "Undo"])
    tossed.get_by_role("button", name="Undo removing Greek yogurt").click()
    page.locator(".toast", has_text="Put greek yogurt back").wait_for()
    expect(yogurt).to_contain_text("Fage, big tub, opened last Sunday")
    expect(yogurt).to_contain_text("Expired 1 day ago")
    page.get_by_label("Filter").fill("jasmine")
    expect(page.locator("#pantry-list .item-name")).to_have_text(["Rice"])
    page.get_by_label("Filter").fill("")
    shot(page, "03-kitchen-after-edits")

    page.get_by_role("tab", name="Shopping list").click()
    page.locator("#shopping-list", has_text="Sourdough").wait_for()
    page.get_by_label("Item", exact=True).fill("Basil")
    page.get_by_label("Note", exact=True).fill("a big bunch")
    page.locator("#shopping-form").get_by_role("button", name="Add").click()
    basil = page.locator("#shopping-list .entry", has_text="Basil")
    basil.wait_for()
    assert basil.locator(".item-actions button").all_text_contents() == ["Edit", "Remove"]
    basil.get_by_role("button", name="Edit Basil").click()
    editor = page.locator("#shopping-list .edit-form")
    editor.locator("[name=note]").fill("two bunches, Thai")
    editor.get_by_role("button", name="Save").click()
    expect(page.locator("#shopping-list .entry", has_text="Basil")).to_contain_text("two bunches, Thai")
    expect(page.get_by_role("button", name="Edit Basil")).to_be_focused()
    page.get_by_label("Bought Basil").check()
    page.get_by_label("Bought Lemons").check()
    page.locator("#shopping-list .entry.checked", has_text="Lemons").wait_for()
    page.get_by_role("button", name="Move checked to pantry").click()
    page.locator("#move-result", has_text="Moved 2 items into your pantry").wait_for()
    expect(page.locator("#shopping-list")).not_to_contain_text("Lemons")
    shot(page, "04-shopping")

    page.get_by_role("tab", name="Kitchen").click()
    for name in ("Basil", "Lemons"):
        expect(page.locator("#pantry-list .item-name", has_text=name)).to_have_count(1)

    page.get_by_role("button", name="Kitchen notes").click()
    page.get_by_label("Notes", exact=True).fill("Cooking for one. Love garlic.")
    page.get_by_role("button", name="Save notes").click()
    page.locator(".toast", has_text="Saved your kitchen notes").wait_for()

    page.get_by_role("button", name="Log out").click()
    page.get_by_role("heading", name="Log in to Stockpot").wait_for()


def test_recipes_can_be_suggested_checked_tweaked_saved_and_cooked(window):
    page = window
    log_in(page, "neal")
    page.get_by_role("tab", name="Recipes").click()
    page.get_by_label("In the mood for").fill("something cozy")
    page.get_by_role("button", name="Suggest recipes").click()
    cards = page.locator("#recipe-list .recipe")
    cards.first.wait_for()
    assert 1 <= cards.count() <= 4
    assert re.search(r"before (it turns|they turn)", cards.first.locator(".recipe-why").inner_text())
    shot(page, "05-recipes")

    page.get_by_label("Can I make…").fill("carbonara")
    page.locator("#plan-form button").click()
    carbonara = page.locator("#plan-list .recipe", has_text="Spaghetti Carbonara")
    carbonara.wait_for()
    assert "bacon" in carbonara.locator(".recipe-ingredients").inner_text()
    carbonara.locator("button", has_text="Add missing to shopping list").click()
    page.locator(".toast", has_text="on your list").or_(page.locator(".toast", has_text="Added")).first.wait_for()

    carbonara.get_by_label("Tweak it").fill("make it spicier")
    carbonara.locator("button", has_text="Tweak").click()
    spicy = page.locator("#plan-list .recipe", has_text="Spicy Spaghetti Carbonara")
    spicy.wait_for()
    spicy.locator("button", has_text="Save to recipe box").click()
    page.locator(".toast", has_text="Saved Spicy Spaghetti Carbonara").wait_for()

    first = cards.nth(1)
    used = first.locator(".recipe-ingredients li strong").all_text_contents()
    first.locator("button", has_text="I cooked this").click()
    first.locator(".changes").wait_for()
    assert first.locator(".changes").inner_text().startswith(("Updated", "Removed"))
    shot(page, "06-cooked")

    page.get_by_role("tab", name="Kitchen").click()
    page.locator("#pantry-list .item").first.wait_for()
    after = page.locator("#pantry-list").inner_text()
    assert any("partly used" in after or name not in after for name in used)

    page.get_by_role("tab", name="Recipe box").click()
    saved = page.locator("#box-list .recipe", has_text="Spicy Spaghetti Carbonara")
    saved.wait_for()
    saved.locator("button", has_text="Check my kitchen").click()
    page.locator("#box-list .recipe", has_text="Spaghetti Carbonara").wait_for()
    shot(page, "07-recipe-box")

    page.get_by_role("button", name="Remove Spaghetti Carbonara from the recipe box").click()
    expect(page.locator("#box-list .recipe")).to_have_count(0)
    page.get_by_role("button", name="Undo removing Spaghetti Carbonara").click()
    page.locator(".toast", has_text="Put Spicy Spaghetti Carbonara back in your recipe box").wait_for()
    expect(page.locator("#box-list .recipe h3")).to_have_text(["Spicy Spaghetti Carbonara"])


def test_the_chat_streams_a_reply_and_leads_to_recipes(window):
    page = window
    log_in(page, "neal")
    page.get_by_label("Message").fill("Long day, I want something warm and comforting, under 30 minutes")
    page.get_by_label("Message").press("Enter")
    reply = page.locator(".message-assistant").last
    page.wait_for_function("() => document.querySelector('.message-assistant.streaming') !== null")
    page.wait_for_function("() => document.querySelector('.message-assistant.streaming') === null")
    text = reply.inner_text().lower()
    assert "long one" in text or "warm" in text
    assert any(word in text for word in ("spinach", "chicken", "eggs", "tomatoes", "cheddar"))
    shot(page, "08-chat")

    page.get_by_role("button", name="Find recipes for this").click()
    page.locator("#recipe-list .recipe").first.wait_for()
    assert page.get_by_role("tab", name="Recipes").get_attribute("aria-selected") == "true"

    page.reload()
    page.locator(".message-assistant").last.wait_for()
    assert page.locator(".message-user").last.inner_text().endswith("under 30 minutes")

    workspace = page.locator(".workspace")
    hat = page.locator("#chat-toggle")
    narrow, spot = workspace.bounding_box()["width"], hat.bounding_box()
    expect(hat.locator(".icon-minimize")).to_be_visible()
    expect(hat.locator(".icon-chef")).to_be_hidden()
    hat.click()
    expect(hat).to_have_accessible_name("Open the chat")
    expect(hat.locator(".icon-chef")).to_be_visible()
    expect(hat.locator(".icon-minimize")).to_be_hidden()
    expect(page.get_by_label("Message")).to_be_hidden()
    assert hat.bounding_box() == spot
    assert workspace.bounding_box()["width"] > narrow
    shot(page, "08b-chat-minimized")
    page.reload()
    expect(hat).to_have_attribute("aria-expanded", "false")
    hat.click()
    expect(page.get_by_label("Message")).to_be_visible()
    assert hat.bounding_box() == spot


def test_two_windows_hold_two_separate_kitchens(window, windows):
    neal = window
    log_in(neal, "neal")
    tianyue = windows()
    log_in(tianyue, "tianyue")
    neal_items, tianyue_items = set(pantry_names(neal)), set(pantry_names(tianyue))
    assert "Tofu" in tianyue_items and "Tofu" not in neal_items
    assert "Chicken thighs" in neal_items and "Chicken thighs" not in tianyue_items
    neal.reload()
    neal.locator("#app-view").wait_for()
    assert neal.locator("#username").text_content() == "neal"
    shot(tianyue, "09-second-account")


def test_text_from_users_and_the_ai_is_shown_as_text_never_run_as_html(window):
    page = window
    log_in(page, "neal")
    payload = '<img src=x onerror="document.title=`hacked`">'
    page.locator("summary", has_text="Add one item by hand").click()
    page.locator("#manual-form [name=name]").fill(payload)
    page.locator("#manual-form [name=description]").fill("<b>bold?</b>")
    page.locator("#manual-form").get_by_role("button", name="Add item").click()
    page.locator("#pantry-list .item-name", has_text="<img").wait_for()
    assert page.locator("#pantry-list img").count() == 0
    assert page.locator("#pantry-list b").count() == 0
    assert page.title() == "Stockpot"


def test_the_pot_opens_a_kitchen_home_whose_objects_lead_to_each_part_of_the_app(window, windows):
    page = window
    log_in(page, "neal")
    page.locator(".brand").click()
    home = page.locator("#home-view")
    expect(home).to_be_visible()
    expect(page.locator("#home-title")).to_contain_text("neal.")
    to_buy = [entry["name"] for entry in page.request.get("/api/shopping").json() if not entry["checked"]]
    expect(page.locator("#home-note-0")).to_have_text(to_buy[0] if to_buy else "All stocked up")
    shot(page, "13-kitchen-home")

    for label, tab in [("Shopping list", "Shopping list"), ("Recipes", "Recipes"), ("Kitchen", "Kitchen")]:
        home.get_by_role("button", name=label, exact=True).click()
        expect(home).to_be_hidden()
        expect(page.get_by_role("tab", name=tab)).to_have_attribute("aria-selected", "true")
        page.go_back()
        expect(home).to_be_visible()
        expect(home).to_be_focused()
    page.go_forward()
    expect(page.get_by_role("tab", name="Kitchen")).to_be_focused()
    page.go_back()

    page.locator(".k-box").click()
    expect(page.get_by_role("tab", name="Recipe box")).to_have_attribute("aria-selected", "true")
    page.go_back()
    home.get_by_role("button", name="Recipe box").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("tab", name="Recipe box")).to_be_focused()
    page.go_back()
    home.get_by_role("button", name="Ask the cook").click()
    expect(page.get_by_label("Message")).to_be_focused()

    phone = windows(390, 844)
    log_in(phone, "tianyue")
    phone.locator(".brand").click()
    phone.locator("#home-view").wait_for()
    assert phone.locator(".scene-frame").evaluate("frame => frame.scrollLeft > 0")
    assert phone.evaluate("document.documentElement.scrollWidth") <= 390


def test_the_masthead_and_tabs_stay_at_the_top_while_the_page_scrolls(window, windows):
    page = window
    log_in(page, "neal")
    page.mouse.wheel(0, 5000)
    page.wait_for_function("() => window.scrollY > 400")
    masthead = page.locator(".masthead").bounding_box()
    assert masthead["y"] == 0
    assert abs(page.locator(".tabs").bounding_box()["y"] - masthead["height"]) <= 1
    assert abs(page.locator("#chat-panel").bounding_box()["y"] - masthead["height"]) <= 1
    expect(page.get_by_role("tab", name="Recipes")).to_be_in_viewport()

    phone = windows(390, 844)
    log_in(phone, "tianyue")
    phone.mouse.wheel(0, 3000)
    phone.wait_for_function("() => window.scrollY > 400")
    assert phone.locator(".tabs").bounding_box()["y"] == 0
    expect(phone.locator(".masthead")).not_to_be_in_viewport()


def test_the_kitchen_fits_a_phone_width_window_without_sideways_scrolling(windows):
    page = windows(390, 844)
    log_in(page, "tianyue")
    for tab in ("Kitchen", "Shopping list", "Recipes", "Recipe box"):
        page.get_by_role("tab", name=tab).click()
        assert page.evaluate("document.documentElement.scrollWidth") <= 390, tab
    page.get_by_role("tab", name="Kitchen").click()
    shot(page, "10-phone")


def test_dark_mode_follows_the_system_and_the_toggle_switches_it(windows):
    page = windows(color_scheme="dark")
    log_in(page, "neal")
    background = "getComputedStyle(document.body).backgroundColor"
    dark = page.evaluate(background)
    shot(page, "11-dark-kitchen")
    page.get_by_role("tab", name="Recipes").click()
    page.get_by_role("button", name="Suggest recipes").click()
    page.locator("#recipe-list .recipe").first.wait_for()
    shot(page, "12-dark-recipes")
    page.get_by_role("button", name="Switch to light mode").click()
    assert page.evaluate(background) != dark
    page.reload()
    page.locator("#app-view").wait_for()
    assert page.evaluate("document.documentElement.dataset.theme") == "light"
