// Starts the page: shows the login screen or the kitchen, and switches between tabs.

import { api } from "./api.js";
import { initAuth, showAuthMessage } from "./auth.js";
import { initChat, loadChat, resetChat } from "./chat.js";
import { $, show } from "./dom.js";
import { initNotes } from "./notes.js";
import { initPantry, loadPantry, resetPantry } from "./pantry.js";
import { initRecipes, loadBox, resetRecipes, suggestFor } from "./recipes.js";
import { initShopping, loadShopping, resetShopping } from "./shopping.js";
import { busy } from "./ui.js";

const TAB_KEY = "stockpot.tab";
const THEME_KEY = "stockpot.theme";

function currentTheme() {
  return document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
}

function labelThemeToggle() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  $("#theme-toggle").setAttribute("aria-label", `Switch to ${next} mode`);
}

function initTheme() {
  labelThemeToggle();
  $("#theme-toggle").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // Without storage the choice lasts until the page reloads.
    }
    labelThemeToggle();
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", labelThemeToggle);
}

// Enter submits the plain-words boxes, like the chat; Shift+Enter still adds a line.
function enterSubmits(form) {
  form.querySelector("textarea").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
}

function selectTab(tab, { focus = false } = {}) {
  for (const other of document.querySelectorAll("[role=tab]")) {
    const selected = other === tab;
    other.setAttribute("aria-selected", String(selected));
    other.tabIndex = selected ? 0 : -1;
    show(document.getElementById(other.getAttribute("aria-controls")), selected);
  }
  if (focus) tab.focus();
  try {
    localStorage.setItem(TAB_KEY, tab.id);
  } catch {
    // Storage can be unavailable in private windows; the tab just isn't remembered.
  }
}

function initTabs() {
  const tabs = [...document.querySelectorAll("[role=tab]")];
  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (!step) return;
      event.preventDefault();
      selectTab(tabs[(tabs.indexOf(tab) + step + tabs.length) % tabs.length], { focus: true });
    });
  }
  let remembered = null;
  try {
    remembered = document.getElementById(localStorage.getItem(TAB_KEY));
  } catch {
    remembered = null;
  }
  selectTab(remembered && remembered.getAttribute("role") === "tab" ? remembered : tabs[0]);
}

async function enter(me) {
  $("#username").textContent = me.username;
  $("#avatar").textContent = me.username.slice(0, 1);
  show($("#mock-badge"), me.llm === "mock");
  show($("#account"), true);
  show($("#auth-view"), false);
  show($("#app-view"), true);
  document.querySelector("[role=tab][aria-selected=true]")?.focus();
  await Promise.all([loadPantry(), loadShopping(), loadBox(), loadChat()]);
}

// Shows the login screen and clears everything the last account left on the page.
function leave(message = "") {
  show($("#account"), false);
  show($("#app-view"), false);
  show($("#auth-view"), true);
  resetPantry();
  resetShopping();
  resetRecipes();
  resetChat();
  for (const form of document.querySelectorAll("#app-view form")) form.reset();
  for (const id of ["#adjust-result", "#move-result"]) $(id).replaceChildren();
  $("#toasts").replaceChildren();
  showAuthMessage(message);
  $("#auth-form [name=username]").focus();
}

async function start() {
  initTheme();
  initTabs();
  enterSubmits($("#parse-form"));
  enterSubmits($("#adjust-form"));
  initAuth({ onEnter: enter });
  initPantry();
  initShopping();
  initRecipes();
  initNotes();
  initChat({
    onRecipes: (preferences) => {
      selectTab($("#tab-recipes"));
      suggestFor(preferences);
    },
  });

  $("#logout").addEventListener("click", (event) =>
    busy(event.currentTarget, async () => {
      await api("POST", "/api/auth/logout");
      location.reload();
    })
  );

  document.addEventListener("auth:lost", () => {
    if (!$("#app-view").hidden) leave("Your session ended. Please log in again.");
  });

  try {
    await enter(await api("GET", "/api/me"));
  } catch (error) {
    leave(error.status === 401 ? "" : error.message);
  }
}

start();
