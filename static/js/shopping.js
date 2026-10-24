// The Shopping list tab: add, check off, remove, and move what you bought into the pantry.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { freshnessLabel } from "./format.js";
import { busy, emit, on, onSubmit, toast } from "./ui.js";

let entries = [];

export function initShopping() {
  onSubmit($("#shopping-form"), async (data) => {
    await api("POST", "/api/shopping", { name: data.name, note: data.note });
    $("#shopping-form").reset();
    $("#shopping-form [name=name]").focus();
    emit("shopping");
  });

  $("#move-to-pantry").addEventListener("click", (event) =>
    busy(
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
        emit("shopping");
        emit("pantry");
      },
      "Moving…"
    )
  );

  on("shopping", loadShopping);
}

export async function loadShopping() {
  try {
    entries = await api("GET", "/api/shopping");
    render();
  } catch (error) {
    toast(error.message, "error");
  }
}

function render() {
  $("#shopping-list").replaceChildren(...entries.map(entryRow));
  show($("#shopping-empty"), entries.length === 0);
  $("#move-to-pantry").disabled = !entries.some((entry) => entry.checked);
}

function entryRow(entry) {
  const box = el("input", {
    type: "checkbox",
    checked: entry.checked,
    "aria-label": `Bought ${entry.name}`,
    onchange: async () => {
      box.disabled = true;
      try {
        await api("PATCH", `/api/shopping/${entry.id}`, { checked: box.checked });
        emit("shopping");
      } catch (error) {
        box.checked = !box.checked;
        box.disabled = false;
        toast(error.message, "error");
      }
    },
  });
  return el(
    "li",
    { class: entry.checked ? "entry checked" : "entry" },
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
          emit("shopping");
        }),
    })
  );
}
