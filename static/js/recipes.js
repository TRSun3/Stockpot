// The Recipes and Recipe box tabs: suggestions, "can I make this?", and recipe cards you can tweak, cook, and save.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { minutes } from "./format.js";
import { busy, changeSummary, emit, latestOnly, on, onSubmit, toast } from "./ui.js";

const PREFERENCES_LIMIT = 300;
const fetchBox = latestOnly(() => api("GET", "/api/recipes/saved"));

export function initRecipes() {
  onSubmit(
    $("#suggest-form"),
    async ({ preferences }) => {
      const list = $("#recipe-list");
      list.replaceChildren(el("p", { class: "muted", text: "Looking through your kitchen…" }));
      show($("#recipes-empty"), false);
      try {
        const { recipes } = await api("POST", "/api/recipes/suggest", { preferences });
        list.replaceChildren(...recipes.map((recipe) => recipeCard(recipe)));
        if (!recipes.length) {
          list.replaceChildren(
            el("p", { class: "muted", text: "Nothing fits yet. Add a few groceries to your pantry and ask again." })
          );
        }
      } catch (error) {
        list.replaceChildren();
        show($("#recipes-empty"), !$("#plan-list").children.length);
        throw error;
      }
    },
    "Thinking…"
  );

  onSubmit(
    $("#plan-form"),
    async ({ dish }) => {
      const { recipe } = await api("POST", "/api/recipes/plan", { dish });
      show($("#recipes-empty"), false);
      $("#plan-list").replaceChildren(recipeCard(recipe));
      $("#plan-form").reset();
    },
    "Checking…"
  );

  on("box", loadBox);
}

// Asks for suggestions shaped by `preferences`, unless a suggestion is already on its way.
export function suggestFor(preferences) {
  const form = $("#suggest-form");
  if (form.querySelector("[type=submit]").disabled) return;
  form.elements.preferences.value = preferences.slice(0, PREFERENCES_LIMIT);
  form.requestSubmit();
}

export async function loadBox() {
  try {
    const saved = await fetchBox();
    if (saved === undefined) return;
    $("#box-list").replaceChildren(...saved.map((entry) => recipeCard(entry.recipe, { savedId: entry.id })));
    show($("#box-empty"), saved.length === 0);
  } catch (error) {
    toast(error.message, "error");
  }
}

export function resetRecipes() {
  for (const id of ["#recipe-list", "#plan-list", "#box-list"]) $(id).replaceChildren();
  show($("#recipes-empty"), true);
}

// "25 min · 3 from your kitchen · 1 to buy"
function meta(recipe) {
  const have = recipe.uses.length;
  const need = recipe.missing.length;
  return [
    minutes(recipe.time_minutes),
    `${have} from your kitchen`,
    need ? `${need} to buy` : "nothing to buy",
  ];
}

function recipeCard(recipe, { savedId } = {}) {
  const result = el("div", { class: "card-result" });
  const card = el(
    "article",
    { class: "recipe card", "aria-label": recipe.title },
    el(
      "header",
      { class: "recipe-head" },
      el("h3", { text: recipe.title }),
      el("p", { class: "recipe-meta" }, meta(recipe).map((part) => el("span", { text: part })))
    ),
    recipe.summary ? el("p", { class: "recipe-summary", text: recipe.summary }) : null,
    recipe.why ? el("p", { class: "recipe-why", text: recipe.why }) : null,
    el(
      "div",
      { class: "recipe-ingredients" },
      el(
        "div",
        {},
        el("h4", { text: "From your kitchen" }),
        recipe.uses.length
          ? el(
              "ul",
              {},
              recipe.uses.map((use) =>
                el("li", {}, el("strong", { text: use.name }), use.amount ? ` — ${use.amount}` : "")
              )
            )
          : el("p", { class: "muted", text: "Nothing yet." })
      ),
      el(
        "div",
        {},
        el("h4", { text: "You'd need" }),
        recipe.missing.length
          ? el(
              "ul",
              {},
              recipe.missing.map((name) => el("li", { text: name }))
            )
          : el("p", { class: "muted", text: "Nothing — you have it all." })
      )
    ),
    el(
      "details",
      { class: "recipe-steps" },
      el("summary", { text: `Steps (${recipe.steps.length})` }),
      el(
        "ol",
        {},
        recipe.steps.map((step) => el("li", { text: step }))
      )
    ),
    actions(recipe, savedId, () => card, result),
    tweakForm(recipe, savedId, () => card),
    result
  );
  return card;
}

function actions(recipe, savedId, card, result) {
  const row = el("div", { class: "row recipe-actions" });
  row.append(
    el("button", {
      type: "button",
      class: "primary",
      text: "I cooked this",
      "aria-label": `I cooked ${recipe.title}`,
      onclick: (event) =>
        busy(
          event.currentTarget,
          async () => {
            const changes = await api("POST", "/api/recipes/cooked", { recipe });
            result.replaceChildren(changeSummary(changes));
            emit("pantry");
          },
          "Updating pantry…",
          "Cooked"
        ),
    })
  );
  if (recipe.missing.length) {
    row.append(
      el("button", {
        type: "button",
        text: "Add missing to shopping list",
        "aria-label": `Add what ${recipe.title} is missing to the shopping list`,
        onclick: (event) =>
          busy(
            event.currentTarget,
            async () => {
              const { added, skipped } = await api("POST", "/api/recipes/missing-to-shopping", {
                names: recipe.missing,
                recipe_title: recipe.title.slice(0, PREFERENCES_LIMIT),
              });
              const names = added.map((entry) => entry.name.toLowerCase());
              toast(
                names.length
                  ? `Added ${names.join(", ")} to your shopping list.`
                  : `${skipped.join(", ")} ${skipped.length === 1 ? "is" : "are"} already on your list.`
              );
              emit("shopping");
            },
            "Adding…",
            "On your list"
          ),
      })
    );
  }
  if (savedId === undefined) {
    row.append(
      el("button", {
        type: "button",
        text: "Save to recipe box",
        "aria-label": `Save ${recipe.title} to the recipe box`,
        onclick: (event) =>
          busy(
            event.currentTarget,
            async () => {
              await api("POST", "/api/recipes/saved", { recipe });
              toast(`Saved ${recipe.title} to your recipe box.`);
              emit("box");
            },
            "Saving…",
            "Saved"
          ),
      })
    );
  } else {
    row.append(
      el("button", {
        type: "button",
        text: "Check my kitchen",
        "aria-label": `Check my kitchen for ${recipe.title}`,
        onclick: (event) =>
          busy(
            event.currentTarget,
            async () => {
              const { recipe: fresh } = await api("POST", "/api/recipes/plan", { dish: recipe.title.slice(0, 120) });
              card().replaceWith(recipeCard(fresh, { savedId }));
            },
            "Checking…"
          ),
      }),
      el("button", {
        type: "button",
        text: "Remove from box",
        "aria-label": `Remove ${recipe.title} from the recipe box`,
        onclick: (event) =>
          busy(event.currentTarget, async () => {
            await api("DELETE", `/api/recipes/saved/${savedId}`);
            emit("box");
          }),
      })
    );
  }
  return row;
}

// A tweak makes a new recipe. In the recipe box it appears in place of the saved one, ready to be saved too.
function tweakForm(recipe, savedId, card) {
  const form = el(
    "form",
    { class: "row tweak" },
    el(
      "label",
      { class: "grow" },
      "Tweak it ",
      el("input", { name: "feedback", required: true, maxLength: 300, placeholder: "make it vegetarian, no oven…" })
    ),
    el("button", { type: "submit", text: "Tweak", "aria-label": `Tweak ${recipe.title}` })
  );
  onSubmit(
    form,
    async ({ feedback }) => {
      const { recipe: tweaked } = await api("POST", "/api/recipes/tweak", { recipe, feedback });
      const fresh = recipeCard(tweaked);
      if (savedId !== undefined) {
        fresh.prepend(el("p", { class: "muted", text: "A tweaked version, not saved yet." }));
      }
      card().replaceWith(fresh);
      fresh.querySelector("[name=feedback]").focus();
    },
    "Tweaking…"
  );
  return form;
}
