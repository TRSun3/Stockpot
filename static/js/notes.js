// The Kitchen notes dialog: standing notes about diet, allergies, and equipment that every suggestion respects.
// Notes are saved while the dialog is still open, so a failed save never loses what was typed, and Esc or
// Cancel always throws edits away.

import { api } from "./api.js";
import { $, show } from "./dom.js";
import { busy, toast } from "./ui.js";

export function initNotes() {
  const dialog = $("#notes-dialog");
  const form = $("#notes-form");
  const field = form.elements.notes;
  const error = $("#notes-error");

  $("#open-notes").addEventListener("click", (event) =>
    busy(
      event.currentTarget,
      async () => {
        const { notes } = await api("GET", "/api/preferences");
        field.value = notes;
        show(error, false);
        dialog.showModal();
        field.focus();
      },
      "Opening…"
    )
  );

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const button = event.submitter || form.querySelector("[type=submit]");
    show(error, false);
    button.disabled = true;
    api("PUT", "/api/preferences", { notes: field.value })
      .then(() => {
        dialog.close();
        toast("Saved your kitchen notes.");
      })
      .catch((failure) => {
        error.textContent = failure.message;
        show(error, true);
      })
      .finally(() => {
        button.disabled = false;
      });
  });

  $("#notes-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => $("#open-notes").focus());
}
