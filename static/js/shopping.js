// The Shopping list tab: add, check off, remove, and move what you bought into the pantry.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, emit, keepFocus, latestOnly, on, onSubmit, reportError } from "./ui.js";

let entries = [];
let loaded = false;
let seen = new Set();
// The entry being edited and its open form, kept across re-renders so a reload never throws away typing.
let editing = null;

const fetchEntries = latestOnly(() => api("GET", "/api/shopping"));

export function initShopping() {
  onSubmit($("#shopping-form"), async (data) => {
    await api("POST", "/api/shopping", { name: data.name, note: data.note });
    $("#shopping-form").reset();
    $("#shopping-form [name=name]").focus();
    emit("shopping");
  });

  $("#move-to-pantry").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    await busy(
      button,
      async () => {
        const { moved } = await api("POST", "/api/shopping/move-to-pantry");
        $("#move-result").replaceChildren(
          el(
            "div",
            { class: "changes", role: "status", tabindex: "-1" },
            el("p", { text: `Moved ${moved.length} item${moved.length === 1 ? "" : "s"} into your pantry.` }),
            el(
              "ul",
              {},
              moved.map((item) => el("li", {}, el("strong", { text: item.name }), `: ${freshnessLabel(item)}`))
            )
          )
        );
        entries = entries.filter((entry) => !entry.checked);
        render();
        emit("shopping");
        emit("pantry");
      },
      "Moving…"
    );
    syncMoveButton();
    // With nothing left checked the button disables itself; keyboard focus moves on to what was moved.
    if (button.disabled && (document.activeElement === button || document.activeElement === document.body)) {
      $("#move-result .changes")?.focus({ preventScroll: true });
    }
  });

  on("shopping", loadShopping);
}

export async function loadShopping() {
  try {
    const fresh = await fetchEntries();
    if (fresh === undefined) return;
    const before = seen;
    entries = fresh.map((entry) => ({ ...entry, isNew: loaded && !before.has(entry.id) }));
    seen = new Set(entries.map((entry) => entry.id));
    loaded = true;
    if (editing && !entries.some((entry) => entry.id === editing.id)) editing = null;
    keepFocus(render);
  } catch (error) {
    reportError(error);
  }
}

// The names still to buy, in list order, for the note on the kitchen home's fridge.
export function stillToBuy() {
  return sorted()
    .filter((entry) => !entry.checked)
    .map((entry) => entry.name);
}

export function resetShopping() {
  entries = [];
  loaded = false;
  seen = new Set();
  editing = null;
  render();
}

function sorted() {
  return [...entries].sort((a, b) => Number(a.checked) - Number(b.checked) || a.id - b.id);
}

function syncMoveButton() {
  const button = $("#move-to-pantry");
  if (!button.hasAttribute("aria-busy")) button.disabled = !entries.some((entry) => entry.checked);
}

function render() {
  $("#shopping-list").replaceChildren(
    ...sorted().map((entry) => (editing && editing.id === entry.id ? editing.row : entryRow(entry)))
  );
  show($("#shopping-loading"), !loaded);
  show($("#shopping-empty"), loaded && entries.length === 0);
  syncMoveButton();
  for (const entry of entries) entry.isNew = false;
}

// Applies changes to the entry as the list holds it now, which a reload may have replaced since a request began.
function updateEntry(id, changes) {
  const current = entries.find((entry) => entry.id === id);
  if (current) Object.assign(current, changes);
}

// Checking off updates the list in place, so ticking several boxes quickly never waits on or races a reload.
async function toggle(entry, box) {
  const checked = box.checked;
  updateEntry(entry.id, { checked });
  keepFocus(render);
  try {
    updateEntry(entry.id, await api("PATCH", `/api/shopping/${entry.id}`, { checked }));
  } catch (error) {
    updateEntry(entry.id, { checked: !checked });
    reportError(error);
  }
  keepFocus(render);
}

function entryRow(entry) {
  const box = el("input", {
    type: "checkbox",
    checked: entry.checked,
    "aria-label": `Bought ${entry.name}`,
    "data-key": `entry-${entry.id}-check`,
    onchange: () => toggle(entry, box),
  });
  return el(
    "li",
    { class: `entry${entry.checked ? " checked" : ""}${entry.isNew ? " is-new" : ""}` },
    el(
      "label",
      { class: "entry-main" },
      box,
      el("span", { class: "entry-name", text: entry.name }),
      entry.note ? el("span", { class: "entry-note", text: entry.note }) : null
    ),
    el(
      "div",
      { class: "item-actions" },
      el("button", {
        type: "button",
        text: "Edit",
        "aria-label": `Edit ${entry.name}`,
        "data-key": `entry-${entry.id}-edit`,
        onclick: () => startEditing(entry),
      }),
      el("button", {
        type: "button",
        text: "Remove",
        "aria-label": `Remove ${entry.name}`,
        onclick: (event) =>
          busy(event.currentTarget, async () => {
            await api("DELETE", `/api/shopping/${entry.id}`);
            entries = entries.filter((other) => other.id !== entry.id);
            render();
            $("#shopping-form [name=name]").focus();
          }),
      })
    )
  );
}

function startEditing(entry) {
  const form = el(
    "form",
    { class: "grid-form edit-form", "aria-label": `Edit ${entry.name}` },
    el("label", {}, "Item ", el("input", { name: "name", value: entry.name, required: true, maxLength: 80 })),
    el("label", {}, "Note ", el("input", { name: "note", value: entry.note, maxLength: 500 })),
    el(
      "div",
      { class: "row" },
      el("button", { type: "submit", class: "primary", text: "Save" }),
      el("button", { type: "button", text: "Cancel", onclick: () => stopEditing(entry) })
    )
  );
  onSubmit(form, async (data) => {
    updateEntry(entry.id, await api("PATCH", `/api/shopping/${entry.id}`, { name: data.name, note: data.note }));
    stopEditing(entry);
  });
  form.addEventListener("keydown", (event) => {
    if (event.key === "Escape") stopEditing(entry);
  });
  editing = { id: entry.id, row: el("li", { class: "entry editing" }, form) };
  render();
  form.querySelector("input").focus();
}

function stopEditing(entry) {
  editing = null;
  render();
  document.querySelector(`[data-key="entry-${entry.id}-edit"]`)?.focus();
}
