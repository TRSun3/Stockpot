// The chat panel: tell the cook your mood, and the reply streams in built on your real kitchen.

import { api, stream } from "./api.js";
import { el, $, show } from "./dom.js";
import { busy, onSubmit, toast } from "./ui.js";

let lastAsked = "";

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
    if (!confirm("Clear the whole conversation?")) return;
    busy(event.currentTarget, async () => {
      await api("DELETE", "/api/chat");
      render([]);
    });
  });

  $("#chat-to-recipes").addEventListener("click", () => onRecipes(lastAsked));
}

export async function loadChat() {
  try {
    const history = await api("GET", "/api/chat");
    render(history);
  } catch (error) {
    toast(error.message, "error");
  }
}

function render(history) {
  $("#chat-messages").replaceChildren(...history.map((message) => bubble(message.role, message.content)));
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

async function send(message) {
  if (!message) return;
  const list = $("#chat-messages");
  const input = $("#chat-input");
  show($("#chat-empty"), false);
  list.append(bubble("user", message));
  const reply = bubble("assistant", "");
  reply.classList.add("streaming");
  const text = reply.querySelector("p");
  text.textContent = "…";
  list.append(reply);
  input.value = "";
  input.disabled = true;
  scrollToEnd();
  let received = "";
  try {
    await stream("/api/chat", { message }, (event) => {
      if (event.type === "text") {
        received += event.text;
        text.textContent = received;
        scrollToEnd();
      } else if (event.type === "error") {
        reply.classList.add("message-error");
        text.textContent = received ? `${received} … ${event.error}` : event.error;
      }
    });
    lastAsked = message;
    show($("#chat-to-recipes"), true);
  } catch (error) {
    reply.classList.add("message-error");
    text.textContent = error.message;
    input.value = message;
  } finally {
    reply.classList.remove("streaming");
    input.disabled = false;
    input.focus();
  }
}
