// Starts the page: shows the login screen or the kitchen, and switches between tabs.

import { api } from "./api.js";
import { initAuth, showAuthMessage } from "./auth.js";
import { initChat, loadChat, openChat, resetChat } from "./chat.js";
import { $, show } from "./dom.js";
import { centerKitchen, initHome, renderHome, resetHome } from "./home.js";
import { initNotes } from "./notes.js";
import { initPantry, loadPantry, resetPantry } from "./pantry.js";
import { initRecipes, loadBox, resetRecipes, suggestFor } from "./recipes.js";
import { initShopping, loadShopping, resetShopping } from "./shopping.js";
import { busy, reportError } from "./ui.js";

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

// Keeps --masthead-height equal to the frozen masthead's height, so the tabs and chat stick just below it.
// On phones the masthead isn't frozen, so it counts as 0.
function trackMasthead() {
  const masthead = $(".masthead");
  const update = () => {
    const frozen = getComputedStyle(masthead).position === "sticky";
    document.documentElement.style.setProperty("--masthead-height", `${frozen ? masthead.offsetHeight : 0}px`);
  };
  new ResizeObserver(update).observe(masthead);
  matchMedia("(max-width: 760px)").addEventListener("change", update);
  update();
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

// Who is logged in, or null on the login screen.
let current = null;

// The address decides the view: "#home" is the kitchen home, anything else the app. The pot links to "#home",
// so the browser's Back button returns from a tab to the kitchen.
function route() {
  if (!current) return;
  const home = location.hash === "#home";
  const switching = home !== !$("#home-view").hidden;
  show($("#home-view"), home);
  show($("#app-view"), !home);
  if (home) renderHome(current.username);
  if (!switching) return;
  // Moving between the kitchen home and the app puts keyboard focus at the start of the new view.
  if (home) {
    centerKitchen();
    $("#home-view").focus({ preventScroll: true });
  } else {
    document.querySelector("[role=tab][aria-selected=true]")?.focus();
  }
}

// The skip link goes to whichever view is showing, without changing the address that chooses it.
function initSkipLink() {
  $(".skip-link").addEventListener("click", (event) => {
    event.preventDefault();
    if (!$("#home-view").hidden) $("#home-view").focus();
    else if (!$("#app-view").hidden) $("#app-view").focus();
    else $("#auth-form [name=username]").focus();
  });
}

// Leaves the kitchen home for one part of the app: a tab's id, or "chat".
function goTo(target) {
  history.pushState(null, "", location.pathname + location.search);
  route();
  if (target === "chat") {
    openChat();
    return;
  }
  selectTab(document.getElementById(target), { focus: true });
  window.scrollTo({ top: 0 });
}

async function enter(me) {
  current = me;
  $("#username").textContent = me.username;
  $("#avatar").textContent = me.username.slice(0, 1);
  show($("#mock-badge"), me.llm === "mock");
  show($("#account"), true);
  show($("#auth-view"), false);
  route();
  if (!$("#app-view").hidden) document.querySelector("[role=tab][aria-selected=true]")?.focus();
  await Promise.all([loadPantry(), loadShopping(), loadBox(), loadChat()]);
  route();
}

// Shows the login screen and clears everything the last account left on the page.
function leave(message = "") {
  current = null;
  if ($("#notes-dialog").open) $("#notes-dialog").close();
  show($("#account"), false);
  show($("#app-view"), false);
  show($("#home-view"), false);
  show($("#auth-view"), true);
  resetPantry();
  resetShopping();
  resetRecipes();
  resetChat();
  resetHome();
  for (const form of document.querySelectorAll("#app-view form")) form.reset();
  for (const id of ["#adjust-result", "#move-result"]) $(id).replaceChildren();
  $("#toasts").replaceChildren();
  showAuthMessage(message);
  $("#auth-form [name=username]").focus();
}

async function start() {
  // A last resort: every action handles its own errors, but anything missed still gets a readable message.
  window.addEventListener("unhandledrejection", (event) => {
    reportError(event.reason);
  });
  initTheme();
  trackMasthead();
  initTabs();
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

  initHome({ onGo: goTo });
  initSkipLink();
  window.addEventListener("hashchange", route);

  document.addEventListener("auth:lost", () => {
    if (current) leave("Your session ended. Please log in again.");
  });

  try {
    await enter(await api("GET", "/api/me"));
  } catch (error) {
    leave(error.status === 401 ? "" : error.message);
  }
}

start();
