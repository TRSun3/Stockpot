// The Recipes and Recipe box tabs: suggestions, "can I make this?", and recipe cards you can tweak, cook, and save.

import { api } from "./api.js";
import { el, $, show } from "./dom.js";
import { minutes } from "./format.js";
import { busy, changeSummary, emit, on, onSubmit, toast } from "./ui.js";

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
        show($("#recipes-empty"), true);
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
      $("#recipe-list").prepend(recipeCard(recipe));
      $("#plan-form").reset();
    },
    "Checking…"
  );

  on("box", loadBox);
}

export function suggestFor(preferences) {
  const form = $("#suggest-form");
  form.elements.preferences.value = preferences;
  form.requestSubmit();
}

export async function loadBox() {
  try {
    const saved = await api("GET", "/api/recipes/saved");
    $("#box-list").replaceChildren(...saved.map((entry) => recipeCard(entry.recipe, { savedId: entry.id })));
    show($("#box-empty"), saved.length === 0);
  } catch (error) {
    toast(error.message, "error");
  }
}

function recipeCard(recipe, { savedId } = {}) {
  const result = el("div", { class: "card-result" });
  const card = el(
    "article",
    { class: "recipe card" },
    el(
      "header",
      { class: "recipe-head" },
      el("h3", { text: recipe.title }),
      el("span", { class: "recipe-time", text: minutes(recipe.time_minutes) })
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
    tweakForm(recipe, () => card),
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
      onclick: (event) =>
        busy(
          event.currentTarget,
          async () => {
            const changes = await api("POST", "/api/recipes/cooked", { recipe });
            result.replaceChildren(changeSummary(changes));
            emit("pantry");
          },
          "Updating pantry…"
        ),
    })
  );
  if (recipe.missing.length) {
    row.append(
      el("button", {
        type: "button",
        text: "Add missing to shopping list",
        onclick: (event) =>
          busy(event.currentTarget, async () => {
            const { added, skipped } = await api("POST", "/api/recipes/missing-to-shopping", {
              names: recipe.missing,
              recipe_title: recipe.title,
            });
            const names = added.map((entry) => entry.name.toLowerCase());
            toast(
              names.length
                ? `Added ${names.join(", ")} to your shopping list.`
                : `${skipped.join(", ")} ${skipped.length === 1 ? "is" : "are"} already on your list.`
            );
            emit("shopping");
          }),
      })
    );
  }
  if (savedId === undefined) {
    row.append(
      el("button", {
        type: "button",
        text: "Save to recipe box",
        onclick: (event) =>
          busy(event.currentTarget, async () => {
            await api("POST", "/api/recipes/saved", { recipe });
            toast(`Saved ${recipe.title} to your recipe box.`);
            emit("box");
          }),
      })
    );
  } else {
    row.append(
      el("button", {
        type: "button",
        text: "Check my kitchen",
        onclick: (event) =>
          busy(
            event.currentTarget,
            async () => {
              const { recipe: fresh } = await api("POST", "/api/recipes/plan", { dish: recipe.title });
              card().replaceWith(recipeCard(fresh, { savedId }));
            },
            "Checking…"
          ),
      }),
      el("button", {
        type: "button",
        text: "Remove from box",
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

function tweakForm(recipe, card) {
  const form = el(
    "form",
    { class: "row tweak" },
    el(
      "label",
      { class: "grow" },
      "Tweak it ",
      el("input", { name: "feedback", required: true, maxLength: 300, placeholder: "make it vegetarian, no oven…" })
    ),
    el("button", { type: "submit", text: "Tweak" })
  );
  onSubmit(
    form,
    async ({ feedback }) => {
      const { recipe: tweaked } = await api("POST", "/api/recipes/tweak", { recipe, feedback });
      card().replaceWith(recipeCard(tweaked));
    },
    "Tweaking…"
  );
  return form;
}
