"""The demo, end to end in Edge against a live server: every flow a person would click through.

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
    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge")
        yield browser
        browser.close()


@pytest.fixture
def window(browser, server):
    """A fresh browser context, like its own private window, that fails the test on any page error."""
    context = browser.new_context(base_url=server, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    problems = []
    page.on("pageerror", lambda error: problems.append(str(error)))
    page.on(
        "console",
        lambda message: message.type == "error" and not expected(message.text) and problems.append(message.text),
    )
    page.on("dialog", lambda dialog: problems.append(f"unexpected dialog: {dialog.message}") or dialog.dismiss())
    yield page
    context.close()
    assert problems == []


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
    page.get_by_role("heading", name="Welcome to your kitchen").wait_for()
    shot(page, "01-login")

    log_in(page, "neal")
    assert page.locator("#username").text_content() == "neal"
    assert page.locator("#mock-badge").is_visible()
    soon = page.locator("#soon-list")
    for text in ("Spinach", "Greek yogurt", "Expired 1 day ago"):
        expect(soon).to_contain_text(text)
    shot(page, "02-kitchen")

    page.get_by_label("What did you bring home?").fill(
        "just got back from the store: a dozen eggs, a bag of spinach, chicken thighs and some cheddar"
    )
    page.get_by_role("button", name="Add to pantry").click()
    page.locator(".toast", has_text="Added eggs, spinach, chicken thighs, cheddar").wait_for()
    expect(page.locator("#pantry-list .item-name", has_text="Spinach")).to_have_count(2)

    milk = page.locator("#pantry-list .item", has_text="Milk")
    milk.get_by_role("button", name="Edit").click()
    page.locator(".edit-form [name=description]").fill("a full gallon, just opened")
    page.locator(".edit-form").get_by_role("button", name="Save").click()
    page.locator("#pantry-list .item", has_text="a full gallon, just opened").wait_for()

    page.get_by_label("What changed?").fill("I used half the milk and the avocados went bad")
    page.get_by_role("button", name="Update pantry").click()
    page.locator("#adjust-result", has_text="Updated milk, removed avocados").wait_for()
    expect(page.locator("#pantry-list .item-name", has_text="Avocados")).to_have_count(0)

    page.locator("#pantry-list .item", has_text="Sourdough").get_by_role("button", name="Used up").click()
    page.locator(".toast", has_text="Removed sourdough").get_by_role("button", name="Add to shopping list").click()
    page.locator(".toast", has_text="Added sourdough to your shopping list").wait_for()
    page.get_by_label("Filter").fill("jasmine")
    expect(page.locator("#pantry-list .item-name")).to_have_text(["Rice"])
    page.get_by_label("Filter").fill("")
    shot(page, "03-kitchen-after-edits")

    page.get_by_role("tab", name="Shopping list").click()
    page.locator("#shopping-list", has_text="Sourdough").wait_for()
    page.get_by_label("Item", exact=True).fill("Basil")
    page.get_by_label("Note", exact=True).fill("a big bunch")
    page.locator("#shopping-form").get_by_role("button", name="Add").click()
    page.locator("#shopping-list .entry", has_text="Basil").wait_for()
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
    page.get_by_role("heading", name="Welcome to your kitchen").wait_for()


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
    page.get_by_role("button", name="Check my kitchen").click()
    carbonara = page.locator("#recipe-list .recipe", has_text="Spaghetti Carbonara")
    carbonara.wait_for()
    assert "bacon" in carbonara.locator(".recipe-ingredients").inner_text()
    carbonara.get_by_role("button", name="Add missing to shopping list").click()
    page.locator(".toast", has_text="on your list").or_(page.locator(".toast", has_text="Added")).first.wait_for()

    carbonara.get_by_label("Tweak it").fill("make it spicier")
    carbonara.get_by_role("button", name="Tweak").click()
    spicy = page.locator("#recipe-list .recipe", has_text="Spicy Spaghetti Carbonara")
    spicy.wait_for()
    spicy.get_by_role("button", name="Save to recipe box").click()
    page.locator(".toast", has_text="Saved Spicy Spaghetti Carbonara").wait_for()

    first = cards.nth(1)
    used = first.locator(".recipe-ingredients li strong").all_text_contents()
    first.get_by_role("button", name="I cooked this").click()
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
    saved.get_by_role("button", name="Check my kitchen").click()
    page.locator("#box-list .recipe", has_text="Spaghetti Carbonara").wait_for()
    shot(page, "07-recipe-box")


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


def test_two_windows_hold_two_separate_kitchens(window, browser, server):
    neal = window
    log_in(neal, "neal")
    private = browser.new_context(base_url=server, viewport={"width": 1440, "height": 900})
    tianyue = private.new_page()
    log_in(tianyue, "tianyue")
    neal_items, tianyue_items = set(pantry_names(neal)), set(pantry_names(tianyue))
    assert "Tofu" in tianyue_items and "Tofu" not in neal_items
    assert "Chicken thighs" in neal_items and "Chicken thighs" not in tianyue_items
    neal.reload()
    neal.locator("#app-view").wait_for()
    assert neal.locator("#username").text_content() == "neal"
    shot(tianyue, "09-second-account")
    private.close()


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
