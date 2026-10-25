// The Kitchen tab: Use Soon, adding groceries in plain words or by hand, adjustments, and the pantry itself.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, changeSummary, emit, keepFocus, latestOnly, on, onSubmit, reportError, toast } from "./ui.js";

let items = [];
let loaded = false;
// Ids already on screen, so only newly added items settle in with an animation.
let seen = new Set();
// The item being edited and its open form, kept across re-renders so a reload never throws away typing.
let editing = null;

const fetchItems = latestOnly(() => api("GET", "/api/items"));

// Groceries typed one at a time, each as {text}, waiting to be added to the pantry together in one request.
// Each is its own object so a request clears exactly the ones it sent, even if more are typed meanwhile.
let staged = [];
// The API's limit on the text it parses at once.
const MAX_TEXT = 2000;

function stagedText(entries) {
  return entries.map((entry) => entry.text).join("\n");
}

function stageEntry() {
  const entry = $("#grocery-entry");
  const text = entry.value.trim();
  if (!text) return;
  if (stagedText([...staged, { text }]).length > MAX_TEXT) {
    toast("That's a full bag. Add these to your pantry first, then keep going.", "error");
    return;
  }
  staged.push({ text });
  entry.value = "";
  renderStaged();
}

function unstage(index) {
  staged.splice(index, 1);
  renderStaged();
  $("#grocery-entry").focus();
}

function renderStaged() {
  $("#staged-list").replaceChildren(
    ...staged.map(({ text }, index) =>
      el(
        "li",
        { class: "staged-item" },
        el("span", { text }),
        el("button", {
          type: "button",
          class: "quiet small",
          text: "×",
          "aria-label": `Remove ${text}`,
          onclick: () => unstage(index),
        })
      )
    )
  );
  show($("#staged-list"), staged.length > 0);
}

function initStaging() {
  $("#grocery-entry").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) {
      event.preventDefault();
      stageEntry();
    }
  });
  $("#stage-add").addEventListener("click", () => {
    stageEntry();
    $("#grocery-entry").focus();
  });
}

const SOON_KEY = "stockpot.soon";

function setSoonOpen(open) {
  const toggle = $("#soon-toggle");
  toggle.setAttribute("aria-expanded", String(open));
  toggle.setAttribute("aria-label", `${open ? "Hide" : "Show"} Use soon`);
  toggle.querySelector("span").textContent = open ? "Hide" : "Show";
  show($("#soon-body"), open);
}

function initSoonToggle() {
  let open = true;
  try {
    open = localStorage.getItem(SOON_KEY) !== "collapsed";
  } catch {
    // Without storage the panel starts open.
  }
  setSoonOpen(open);
  $("#soon-toggle").addEventListener("click", () => {
    const next = $("#soon-toggle").getAttribute("aria-expanded") !== "true";
    setSoonOpen(next);
    try {
      localStorage.setItem(SOON_KEY, next ? "open" : "collapsed");
    } catch {
      // The choice lasts until the page reloads.
    }
  });
}

export function initPantry() {
  initSoonToggle();
  initStaging();
  onSubmit(
    $("#parse-form"),
    async () => {
      stageEntry();
      if (!staged.length) {
        $("#grocery-entry").focus();
        return;
      }
      const sent = [...staged];
      const added = await api("POST", "/api/items/parse", { text: stagedText(sent) });
      staged = staged.filter((entry) => !sent.includes(entry));
      renderStaged();
      toast(`Added ${added.map((item) => item.name.toLowerCase()).join(", ")}.`);
      emit("pantry");
    },
    "Adding…"
  );

  onSubmit($("#manual-form"), async (data) => {
    const item = await api("POST", "/api/items", {
      name: data.name,
      description: data.description,
      expires_on: data.expires_on || null,
    });
    $("#manual-form").reset();
    toast(`Added ${item.name.toLowerCase()}.`);
    emit("pantry");
  });

  onSubmit(
    $("#adjust-form"),
    async ({ text }) => {
      const result = await api("POST", "/api/items/adjust", { text });
      $("#adjust-form").reset();
      $("#adjust-result").replaceChildren(changeSummary(result));
      emit("pantry");
    },
    "Updating…"
  );

  $("#pantry-filter").addEventListener("input", () => keepFocus(renderLedger));
  on("pantry", loadPantry);
}

export async function loadPantry() {
  try {
    const fresh = await fetchItems();
    if (fresh === undefined) return;
    const before = seen;
    items = fresh.map((item) => ({ ...item, isNew: loaded && !before.has(item.id) }));
    seen = new Set(items.map((item) => item.id));
    loaded = true;
    if (editing && !items.some((item) => item.id === editing.id)) editing = null;
    keepFocus(render);
  } catch (error) {
    reportError(error);
  }
}

// How full the pantry is and how much of it to use soon, for the kitchen home's greeting.
export function pantryCounts() {
  const soon = items.filter((item) => item.days_left !== null && item.days_left <= 3).length;
  return { total: items.length, soon };
}

export function resetPantry() {
  items = [];
  loaded = false;
  seen = new Set();
  editing = null;
  staged = [];
  $("#pantry-filter").value = "";
  renderStaged();
  render();
}

function render() {
  renderSoon();
  renderLedger();
  for (const item of items) item.isNew = false;
}

function renderSoon() {
  const soon = items.filter((item) => item.days_left !== null && item.days_left <= 3);
  $("#soon-list").replaceChildren(...soon.map((item) => itemRow(item, "soon")));
  show($("#soon-empty"), loaded && soon.length === 0);
  $("#soon-count").textContent = soon.length ? `(${soon.length})` : "";
}

// The pantry list, filtered by the search box; typing in the search redraws only this.
function renderLedger() {
  const query = $("#pantry-filter").value.trim().toLowerCase();
  const shown = query
    ? items.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(query))
    : items;
  $("#pantry-list").replaceChildren(
    ...shown.map((item) => (editing && editing.id === item.id ? editing.row : itemRow(item, "all")))
  );
  $("#pantry-count").textContent = items.length ? `(${items.length})` : "";
  show($("#pantry-loading"), !loaded);
  show($("#pantry-empty"), loaded && items.length === 0);
  show($("#pantry-no-match"), loaded && items.length > 0 && shown.length === 0);
}

function itemRow(item, list) {
  const discardLabel = item.status === "expired" ? "Toss" : "Used up";
  return el(
    "li",
    { class: `item status-${item.status}${item.isNew ? " is-new" : ""}` },
    el(
      "div",
      { class: "item-main" },
      el("span", { class: "item-name", text: item.name }),
      item.description ? el("span", { class: "item-description", text: item.description }) : null
    ),
    el("span", { class: `freshness freshness-${item.status}`, text: freshnessLabel(item) }),
    el(
      "div",
      { class: "item-actions" },
      list === "all"
        ? el("button", {
            type: "button",
            text: "Edit",
            "aria-label": `Edit ${item.name}`,
            "data-key": `item-${item.id}-edit`,
            onclick: () => startEditing(item),
          })
        : null,
      el("button", {
        type: "button",
        text: discardLabel,
        "aria-label": `${discardLabel}: ${item.name}`,
        "data-key": `item-${item.id}-discard-${list}`,
        // A click with no pointer behind it (detail 0) came from the keyboard.
        onclick: (event) => discard(item, event.currentTarget, event.detail === 0),
      })
    )
  );
}

function startEditing(item) {
  const form = el(
    "form",
    { class: "grid-form edit-form", "aria-label": `Edit ${item.name}` },
    el("label", {}, "Name ", el("input", { name: "name", value: item.name, required: true, maxLength: 80 })),
    el("label", {}, "Details ", el("input", { name: "description", value: item.description, maxLength: 500 })),
    el("label", {}, "Expires ", el("input", { name: "expires_on", type: "date", value: item.expires_on || "" })),
    el(
      "div",
      { class: "row" },
      el("button", { type: "submit", class: "primary", text: "Save" }),
      el("button", { type: "button", text: "Cancel", onclick: () => stopEditing(item) })
    )
  );
  onSubmit(form, async (data) => {
    await api("PATCH", `/api/items/${item.id}`, {
      name: data.name,
      description: data.description,
      expires_on: data.expires_on || null,
    });
    stopEditing(item);
    emit("pantry");
  });
  form.addEventListener("keydown", (event) => {
    if (event.key === "Escape") stopEditing(item);
  });
  editing = { id: item.id, row: el("li", { class: "item editing" }, form) };
  render();
  form.querySelector("input").focus();
}

function stopEditing(item) {
  editing = null;
  render();
  document.querySelector(`[data-key="item-${item.id}-edit"]`)?.focus();
}

// From the keyboard, focus moves to the toast, since the button pressed is about to disappear with its row and
// the toast's Undo would otherwise be dozens of Tab presses away.
async function discard(item, button, byKeyboard) {
  await busy(button, async () => {
    await api("DELETE", `/api/items/${item.id}`);
    emit("pantry");
    const note = toast(
      `Removed ${item.name.toLowerCase()}.`,
      "info",
      {
        label: "Add to shopping list",
        run: async () => {
          await api("POST", "/api/shopping", { name: item.name, note: "" });
          emit("shopping");
          toast(`Added ${item.name.toLowerCase()} to your shopping list.`);
        },
      },
      {
        label: "Undo",
        ariaLabel: `Undo removing ${item.name}`,
        // Adds the item back as it was; it returns with a new id.
        run: async () => {
          await api("POST", "/api/items", {
            name: item.name,
            description: item.description,
            expires_on: item.expires_on,
          });
          emit("pantry");
          toast(`Put ${item.name.toLowerCase()} back.`);
        },
      }
    );
    if (byKeyboard) note.querySelector("button").focus();
  });
}
