// The Kitchen tab: Use Soon, adding groceries in plain words or by hand, adjustments, and the pantry itself.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, changeSummary, emit, keepFocus, latestOnly, on, onSubmit, toast } from "./ui.js";

let items = [];
let loaded = false;
// Ids already on screen, so only newly added items settle in with an animation.
let seen = new Set();
// The item being edited and its open form, kept across re-renders so a reload never throws away typing.
let editing = null;

const fetchItems = latestOnly(() => api("GET", "/api/items"));

export function initPantry() {
  onSubmit(
    $("#parse-form"),
    async ({ text }) => {
      const added = await api("POST", "/api/items/parse", { text });
      $("#parse-form").reset();
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

  $("#pantry-filter").addEventListener("input", () => keepFocus(render));
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
    toast(error.message, "error");
  }
}

export function resetPantry() {
  items = [];
  loaded = false;
  seen = new Set();
  editing = null;
  render();
}

function render() {
  const soon = items.filter((item) => item.days_left !== null && item.days_left <= 3);
  $("#soon-list").replaceChildren(...soon.map((item) => itemRow(item, "soon")));
  show($("#soon-empty"), loaded && soon.length === 0);

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
  for (const item of items) item.isNew = false;
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
        onclick: (event) => discard(item, event.currentTarget),
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

async function discard(item, button) {
  await busy(button, async () => {
    await api("DELETE", `/api/items/${item.id}`);
    emit("pantry");
    toast(`Removed ${item.name.toLowerCase()}.`, "info", {
      label: "Add to shopping list",
      run: async () => {
        await api("POST", "/api/shopping", { name: item.name, note: "" });
        emit("shopping");
        toast(`Added ${item.name.toLowerCase()} to your shopping list.`);
      },
    });
  });
}
