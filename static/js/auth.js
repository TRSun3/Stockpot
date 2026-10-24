// The login and sign-up screen.

import { api } from "./api.js";
import { $, show } from "./dom.js";
import { busy } from "./ui.js";

export function initAuth({ onEnter }) {
  const form = $("#auth-form");
  const error = $("#auth-error");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const button = event.submitter || form.querySelector("[data-mode=login]");
    const signup = button.dataset.mode === "signup";
    const { username, password } = Object.fromEntries(new FormData(form));
    show(error, false);
    busy(
      button,
      async () => {
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
        }
      },
      signup ? "Creating…" : "Logging in…"
    );
  });
}

export function showAuthMessage(message) {
  const error = $("#auth-error");
  error.textContent = message;
  show(error, Boolean(message));
}
