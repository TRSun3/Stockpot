// The Kitchen notes dialog: standing notes about diet, allergies, and equipment that every suggestion respects.

import { api } from "./api.js";
import { $ } from "./dom.js";
import { toast } from "./ui.js";

export function initNotes() {
  const dialog = $("#notes-dialog");
  const field = $("#notes-form [name=notes]");

  $("#open-notes").addEventListener("click", async () => {
    try {
      const { notes } = await api("GET", "/api/preferences");
      field.value = notes;
      dialog.showModal();
      field.focus();
    } catch (error) {
      toast(error.message, "error");
    }
  });

  dialog.addEventListener("close", async () => {
    if (dialog.returnValue !== "save") return;
    try {
      await api("PUT", "/api/preferences", { notes: field.value });
      toast("Saved your kitchen notes.");
    } catch (error) {
      toast(error.message, "error");
    }
  });
}
