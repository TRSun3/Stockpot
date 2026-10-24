// The Kitchen tab: Use Soon, adding groceries in plain words or by hand, adjustments, and the pantry itself.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, changeSummary, emit, on, onSubmit, toast } from "./ui.js";

let items = [];

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

  $("#pantry-filter").addEventListener("input", render);
  on("pantry", loadPantry);
}

export async function loadPantry() {
  try {
    items = await api("GET", "/api/items");
    render();
  } catch (error) {
    toast(error.message, "error");
  }
}

function render() {
  const soon = items.filter((item) => item.days_left !== null && item.days_left <= 3);
  $("#soon-list").replaceChildren(...soon.map((item) => itemRow(item, { editable: false })));
  show($("#soon-empty"), soon.length === 0);

  const query = $("#pantry-filter").value.trim().toLowerCase();
  const shown = query
    ? items.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(query))
    : items;
  $("#pantry-list").replaceChildren(...shown.map((item) => itemRow(item, { editable: true })));
  $("#pantry-count").textContent = items.length ? `(${items.length})` : "";
  show($("#pantry-empty"), items.length === 0);
}

function itemRow(item, { editable }) {
  const row = el(
    "li",
    { class: `item status-${item.status}` },
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
      editable ? el("button", { type: "button", text: "Edit", onclick: () => row.replaceWith(editRow(item)) }) : null,
      el("button", {
        type: "button",
        text: item.status === "expired" ? "Toss" : "Used up",
        onclick: (event) => discard(item, event.currentTarget),
      })
    )
  );
  return row;
}

function editRow(item) {
  const form = el(
    "form",
    { class: "grid-form edit-form" },
    el("label", {}, "Name ", el("input", { name: "name", value: item.name, required: true, maxLength: 80 })),
    el(
      "label",
      {},
      "Details ",
      el("input", { name: "description", value: item.description, maxLength: 500 })
    ),
    el("label", {}, "Expires ", el("input", { name: "expires_on", type: "date", value: item.expires_on || "" })),
    el(
      "div",
      { class: "row" },
      el("button", { type: "submit", class: "primary", text: "Save" }),
      el("button", { type: "button", text: "Cancel", onclick: render })
    )
  );
  onSubmit(form, async (data) => {
    await api("PATCH", `/api/items/${item.id}`, {
      name: data.name,
      description: data.description,
      expires_on: data.expires_on || null,
    });
    emit("pantry");
  });
  const row = el("li", { class: "item editing" }, form);
  queueMicrotask(() => form.querySelector("input").focus());
  return row;
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
