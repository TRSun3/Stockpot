// Starts the page: shows the login screen or the kitchen, and switches between tabs.

import { api } from "./api.js";
import { initAuth, showAuthMessage } from "./auth.js";
import { initChat, loadChat } from "./chat.js";
import { $, show } from "./dom.js";
import { initNotes } from "./notes.js";
import { initPantry, loadPantry } from "./pantry.js";
import { initRecipes, loadBox, suggestFor } from "./recipes.js";
import { initShopping, loadShopping } from "./shopping.js";
import { busy } from "./ui.js";

const TAB_KEY = "stockpot.tab";

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
  show($("#mock-badge"), me.llm === "mock");
  show($("#account"), true);
  show($("#auth-view"), false);
  show($("#app-view"), true);
  await Promise.all([loadPantry(), loadShopping(), loadBox(), loadChat()]);
}

function leave(message = "") {
  show($("#account"), false);
  show($("#app-view"), false);
  show($("#auth-view"), true);
  showAuthMessage(message);
  $("#auth-form [name=username]").focus();
}

async function start() {
  initTabs();
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
  } catch {
    leave();
  }
}

start();
