// The kitchen home: an illustrated kitchen, opened from the pot logo, whose objects lead to each part of the app.

import { $ } from "./dom.js";
import { pantryCounts } from "./pantry.js";
import { savedCount } from "./recipes.js";
import { stillToBuy } from "./shopping.js";

const NOTE_LINES = 4;

// Every object and its label carry `data-go`: a tab's id, or "chat". Labels are the keyboard way in.
export function initHome({ onGo }) {
  for (const target of document.querySelectorAll("#home-view [data-go]")) {
    target.addEventListener("click", () => onGo(target.dataset.go));
  }
}

function greeting() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  return "Good evening";
}

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

function summary() {
  const { total, soon } = pantryCounts();
  const toBuy = stillToBuy().length;
  const saved = savedCount();
  const parts = [
    soon ? `${plural(soon, "thing", "things")} to use soon` : total ? "nothing about to turn" : "an empty pantry",
    toBuy ? `${toBuy} on your shopping list` : "nothing to buy",
  ];
  if (saved) parts.push(plural(saved, "saved recipe", "saved recipes"));
  const text = parts.join(", ");
  return `${text[0].toUpperCase()}${text.slice(1)}.`;
}

// The fridge note shows what's still to buy, in the list's order; the last line says how many more there are.
function writeNote() {
  const names = stillToBuy();
  const lines = names.length > NOTE_LINES ? [...names.slice(0, NOTE_LINES - 1), `+ ${names.length - (NOTE_LINES - 1)} more`] : names;
  if (!names.length) lines.push("All stocked up");
  for (let index = 0; index < NOTE_LINES; index += 1) {
    const text = lines[index] || "";
    $(`#home-note-${index}`).textContent = text.length > 15 ? `${text.slice(0, 14)}…` : text;
  }
}

// On a phone the kitchen is a panorama wider than the screen; it opens centered on the stove.
export function centerKitchen() {
  const frame = $(".scene-frame");
  frame.scrollLeft = (frame.scrollWidth - frame.clientWidth) / 2;
}

// Clears the greeting and the fridge note, so nothing of one account stays on the page for the next.
export function resetHome() {
  $("#home-title").textContent = "Your kitchen";
  $("#home-summary").textContent = "";
  for (let index = 0; index < NOTE_LINES; index += 1) $(`#home-note-${index}`).textContent = "";
}

export function renderHome(username) {
  $("#home-title").textContent = `${greeting()}, ${username}.`;
  $("#home-summary").textContent = summary();
  writeNote();
}
