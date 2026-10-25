// The chat panel: tell the cook your mood, and the reply streams in built on your real kitchen.

import { api, stream } from "./api.js";
import { el, $, show } from "./dom.js";
import { busy, onSubmit, toast } from "./ui.js";

let lastAsked = "";
let streaming = false;

export function initChat({ onRecipes }) {
  const form = $("#chat-form");
  const input = $("#chat-input");

  onSubmit(form, ({ message }) => send(message.trim()), "Sending…");

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  $("#chat-clear").addEventListener("click", (event) => {
    if (streaming || !confirm("Clear the whole conversation?")) return;
    busy(event.currentTarget, async () => {
      await api("DELETE", "/api/chat");
      render([]);
    });
  });

  $("#chat-to-recipes").addEventListener("click", () => onRecipes(lastAsked));
}

export async function loadChat() {
  try {
    render(await api("GET", "/api/chat"));
  } catch (error) {
    toast(error.message, "error");
  }
}

export function resetChat() {
  render([]);
}

function render(history) {
  const list = $("#chat-messages");
  list.setAttribute("aria-busy", "true");
  list.replaceChildren(...history.map((message) => bubble(message.role, message.content)));
  list.removeAttribute("aria-busy");
  show($("#chat-empty"), history.length === 0);
  const asked = history.filter((message) => message.role === "user").at(-1);
  lastAsked = asked ? asked.content : "";
  show($("#chat-to-recipes"), Boolean(lastAsked));
  scrollToEnd();
}

function bubble(role, text) {
  return el(
    "li",
    { class: `message message-${role}` },
    el("span", { class: "visually-hidden", text: role === "user" ? "You: " : "Cook: " }),
    el("p", { text })
  );
}

function scrollToEnd() {
  const list = $("#chat-messages");
  list.scrollTop = list.scrollHeight;
}

function setStreaming(active) {
  streaming = active;
  $("#chat-clear").disabled = active;
  const list = $("#chat-messages");
  if (active) list.setAttribute("aria-busy", "true");
  else list.removeAttribute("aria-busy");
}

async function send(message) {
  if (!message || streaming) return;
  const list = $("#chat-messages");
  const input = $("#chat-input");
  const asked = bubble("user", message);
  const reply = bubble("assistant", "");
  const text = reply.querySelector("p");
  show($("#chat-empty"), false);
  reply.classList.add("streaming");
  text.textContent = "…";
  list.append(asked, reply);
  input.value = "";
  input.disabled = true;
  setStreaming(true);
  scrollToEnd();
  let received = "";
  let failed = "";
  try {
    await stream("/api/chat", { message }, (event) => {
      if (event.type === "text") {
        received += event.text;
        text.textContent = received;
        scrollToEnd();
      } else if (event.type === "error") {
        failed = event.error;
      }
    });
  } catch (error) {
    failed = error.message;
  }
  if (failed && !received) {
    // Nothing was said, so the server forgot the question too; put it back to send again.
    asked.remove();
    reply.classList.add("message-error");
    text.textContent = failed;
    input.value = message;
  } else if (failed) {
    reply.classList.add("message-error");
    text.textContent = `${received} … ${failed}`;
  }
  if (received) {
    lastAsked = message;
    show($("#chat-to-recipes"), true);
  }
  reply.classList.remove("streaming");
  input.disabled = false;
  setStreaming(false);
  const focus = document.activeElement;
  if (!focus || focus === document.body || focus.closest(".chat")) input.focus();
}
