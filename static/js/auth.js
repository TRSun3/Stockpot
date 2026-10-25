// The login and sign-up screen.

import { api } from "./api.js";
import { $, show } from "./dom.js";

export function initAuth({ onEnter }) {
  const form = $("#auth-form");
  const error = $("#auth-error");
  const buttons = [...form.querySelectorAll("[type=submit]")];

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (buttons.some((button) => button.disabled)) return;
    const button = event.submitter || form.querySelector("[data-mode=login]");
    const signup = button.dataset.mode === "signup";
    const { username, password } = Object.fromEntries(new FormData(form));
    const original = button.textContent;
    show(error, false);
    for (const each of buttons) each.disabled = true;
    button.textContent = signup ? "Creating…" : "Logging in…";
    try {
      const me = await api("POST", signup ? "/api/auth/signup" : "/api/auth/login", {
        username: username.trim(),
        password,
      });
      form.reset();
      await onEnter(me);
    } catch (failure) {
      error.textContent = failure.message;
      show(error, true);
    } finally {
      for (const each of buttons) each.disabled = false;
      button.textContent = original;
    }
  });
}

export function showAuthMessage(message) {
  const error = $("#auth-error");
  error.textContent = message;
  show(error, Boolean(message));
}
