// Shared behavior: toasts, busy states that block double submits, and a tiny event bus between sections.

import { el, $ } from "./dom.js";

// A short message in the corner. `action` adds a button, like "Add to shopping list" after using something up.
export function toast(message, kind = "info", action) {
  const note = el("div", { class: `toast toast-${kind}` }, el("span", { text: message }));
  if (action) {
    note.append(
      el("button", {
        type: "button",
        class: "link",
        text: action.label,
        onclick: (event) => busy(event.currentTarget, action.run).then(() => note.remove()),
      })
    );
  }
  $("#toasts").append(note);
  setTimeout(() => note.remove(), action ? 9000 : kind === "error" ? 7000 : 4000);
}

// Runs `task` with the button disabled and marked busy, so a second click can't submit twice.
export async function busy(button, task, label = "Working…") {
  if (button.disabled) return undefined;
  const original = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = label;
  try {
    return await task();
  } catch (error) {
    toast(error.message || "Something went wrong.", "error");
    return undefined;
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = original;
  }
}

// Wires a form's submit to `task(data)`, with its submit button busy while the task runs.
export function onSubmit(form, task, label) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const button = event.submitter || form.querySelector("[type=submit]");
    const data = Object.fromEntries(new FormData(form));
    busy(button, () => task(data, button), label);
  });
}

const bus = new EventTarget();

export function emit(name, detail) {
  bus.dispatchEvent(new CustomEvent(name, { detail }));
}

export function on(name, handler) {
  bus.addEventListener(name, (event) => handler(event.detail));
}

// "Updated milk, removed eggs" for the changes the API reports after cooking or an adjustment.
export function describeChanges(result) {
  const words = { added: "Added", updated: "Updated", removed: "Removed" };
  const parts = result.changes.map((change, index) => {
    const verb = words[change.action] || change.action;
    return `${index === 0 ? verb : verb.toLowerCase()} ${change.name.toLowerCase()}`;
  });
  return parts.length ? `${parts.join(", ")}.` : "Nothing in your pantry needed to change.";
}

export function changeSummary(result) {
  const box = el("div", { class: "changes", role: "status" }, el("p", { text: describeChanges(result) }));
  if (result.changes.length) {
    box.append(
      el(
        "ul",
        {},
        result.changes.map((change) =>
          el("li", {}, el("strong", { text: change.name }), change.description ? ` — ${change.description}` : "")
        )
      )
    );
  }
  if (result.rejected.length) {
    box.append(el("p", { class: "muted", text: `${result.rejected.length} suggested change(s) were skipped as unsafe.` }));
  }
  return box;
}
