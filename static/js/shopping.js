// The Shopping list tab: add, check off, remove, and move what you bought into the pantry.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, emit, keepFocus, latestOnly, on, onSubmit, toast } from "./ui.js";

let entries = [];
let loaded = false;
let seen = new Set();

const fetchEntries = latestOnly(() => api("GET", "/api/shopping"));

export function initShopping() {
  onSubmit($("#shopping-form"), async (data) => {
    await api("POST", "/api/shopping", { name: data.name, note: data.note });
    $("#shopping-form").reset();
    $("#shopping-form [name=name]").focus();
    emit("shopping");
  });

  $("#move-to-pantry").addEventListener("click", async (event) => {
    await busy(
      event.currentTarget,
      async () => {
        const { moved } = await api("POST", "/api/shopping/move-to-pantry");
        $("#move-result").replaceChildren(
          el(
            "div",
            { class: "changes", role: "status" },
            el("p", { text: `Moved ${moved.length} item${moved.length === 1 ? "" : "s"} into your pantry.` }),
            el(
              "ul",
              {},
              moved.map((item) => el("li", {}, el("strong", { text: item.name }), ` — ${freshnessLabel(item)}`))
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
    keepFocus(render);
  } catch (error) {
    toast(error.message, "error");
  }
}

export function resetShopping() {
  entries = [];
  loaded = false;
  seen = new Set();
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
  $("#shopping-list").replaceChildren(...sorted().map(entryRow));
  show($("#shopping-loading"), !loaded);
  show($("#shopping-empty"), loaded && entries.length === 0);
  syncMoveButton();
  for (const entry of entries) entry.isNew = false;
}

// Checking off updates the list in place, so ticking several boxes quickly never waits on or races a reload.
async function toggle(entry, box) {
  const checked = box.checked;
  entry.checked = checked;
  keepFocus(render);
  try {
    const saved = await api("PATCH", `/api/shopping/${entry.id}`, { checked });
    Object.assign(entry, saved);
  } catch (error) {
    entry.checked = !checked;
    toast(error.message, "error");
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
  );
}
