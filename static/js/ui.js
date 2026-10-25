// Shared behavior: toasts, busy states that block double submits, keeping focus and only the latest response
// across re-renders, and a tiny event bus between sections.

import { el, $ } from "./dom.js";

// A short message at the bottom of the page, which it returns. Each action adds a button, like "Undo" or "Add to
// shopping list" after using something up; an action that succeeds closes the toast, and one that fails leaves it
// to try again. The toast stays while the pointer or keyboard focus is on it.
export function toast(message, kind = "info", ...actions) {
  const note = el(
    "div",
    { class: `toast toast-${kind}`, role: kind === "error" ? "alert" : null },
    el("span", { text: message })
  );
  const close = () => {
    const hadFocus = note.contains(document.activeElement);
    note.remove();
    if (hadFocus) $("#app-view").focus({ preventScroll: true });
  };
  for (const action of actions) {
    note.append(
      el("button", {
        type: "button",
        class: "link",
        text: action.label,
        "aria-label": action.ariaLabel,
        onclick: (event) =>
          busy(event.currentTarget, async () => {
            await action.run();
            return true;
          }).then((done) => done && close()),
      })
    );
  }
  const lifetime = actions.length ? 10000 : kind === "error" ? 7000 : 4000;
  let timer = setTimeout(close, lifetime);
  const hold = () => clearTimeout(timer);
  const release = () => {
    if (note.matches(":hover") || note.contains(document.activeElement)) return;
    clearTimeout(timer);
    timer = setTimeout(close, 3000);
  };
  note.addEventListener("mouseenter", hold);
  note.addEventListener("focusin", hold);
  note.addEventListener("mouseleave", release);
  // Focus moving between the toast's own buttons is not leaving it.
  note.addEventListener("focusout", () => setTimeout(release));
  $("#toasts").append(note);
  return note;
}

// Runs `task` with the button disabled and marked busy, so a second click can't submit twice.
// With `done`, the button stays disabled afterwards showing that text, for actions that only make sense once.
export async function busy(button, task, label = "Working…", done) {
  if (button.disabled) return undefined;
  const original = button.textContent;
  let succeeded = false;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = label;
  try {
    const result = await task();
    succeeded = true;
    return result;
  } catch (error) {
    toast(error.message || "Something went wrong.", "error");
    return undefined;
  } finally {
    button.removeAttribute("aria-busy");
    if (succeeded && done) {
      button.textContent = done;
    } else {
      button.disabled = false;
      button.textContent = original;
    }
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

// Wraps a loader so only the most recent call's result counts; older responses resolve to undefined.
export function latestOnly(load) {
  let ticket = 0;
  return async (...args) => {
    const mine = ++ticket;
    const result = await load(...args);
    return mine === ticket ? result : undefined;
  };
}

// Re-renders while keeping keyboard focus where it was: on the control with the same `data-key` if there is
// one, or on the same element if the render only moved it, like a field in an edit form kept across reloads.
export function keepFocus(render) {
  const active = document.activeElement;
  const key = active?.dataset?.key;
  render();
  if (key) {
    document.querySelector(`[data-key="${CSS.escape(key)}"]`)?.focus();
  } else if (active && active !== document.body && active.isConnected && document.activeElement !== active) {
    active.focus({ preventScroll: true });
  }
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
          el("li", {}, el("strong", { text: change.name }), change.description ? `: ${change.description}` : "")
        )
      )
    );
  }
  if (result.rejected.length) {
    const count = result.rejected.length;
    box.append(el("p", { class: "muted", text: `${count} suggested change${count === 1 ? " was" : "s were"} skipped as unsafe.` }));
  }
  return box;
}
