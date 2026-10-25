# Frontend

The page is plain HTML, CSS, and JavaScript modules in `static/`, served by FastAPI at `/`. There is no build step, framework, or npm: edit a file and reload.

## Layout

`static/index.html` holds the whole page. When logged out it shows an introduction beside the login form. When logged in it shows four tabs on the left (Kitchen, Shopping list, Recipes, Recipe box) and the chat panel on the right. Kitchen notes open in a dialog from the masthead, and a "Mock AI" badge appears there whenever the server runs on the mock.

## Design

The look is a cookbook rather than an app: parchment paper, espresso ink, and a single terracotta accent.

- **Type:** Fraunces, an editorial serif, for headings, recipe titles, and the cook's chat replies; Inter for everything you operate. Both load from Google Fonts and fall back to Georgia and the system sans offline.
- **Freshness:** a colored dot and a quiet label rather than colored blocks: olive for fresh, saffron for soon, ember for today, red for expired, gray for no expiry. Use Soon shows the same colors as a thin rule along the top of each index card.
- **Pages:** Use Soon is a shelf of cards, the pantry a ruled ledger, the shopping list a checklist, and recipes cookbook pages with the reason in italics, ingredients split into what you have and what you'd buy, and numbered steps.
- **Motion:** only newly added items, recipes, messages, and toasts settle in, and the streaming reply shows a blinking caret. With `prefers-reduced-motion`, nothing moves.
- **Dark mode:** follows the system, and the moon/sun button in the masthead overrides it. The choice is remembered and applied before the first paint.
- **Narrow windows:** below 1080px the chat moves under the tabs; below 760px everything stacks and the shelf shows two cards across. The browser tests check that nothing scrolls sideways at phone width.

## Modules

| File | Does |
|---|---|
| `js/app.js` | Starts the page, chooses login or kitchen, switches tabs (arrow keys work), remembers the last tab, and switches light and dark |
| `js/api.js` | `api(method, path, body)` for JSON calls and `stream(path, body, onEvent)` for the chat's server-sent events. Errors arrive as `ApiError` with the server's message |
| `js/dom.js` | `el(tag, props, ...children)` builds elements; text always goes in through `textContent` |
| `js/ui.js` | Toasts (optionally with an action button), `busy` and `onSubmit` to block double submits, a small event bus, and the "Updated milk, removed eggs" summary |
| `js/format.js` | Freshness labels ("Expires tomorrow", "Expired 2 days ago") and cooking times |
| `js/auth.js` | The login and sign-up form |
| `js/pantry.js` | Use Soon, adding groceries in plain words or by hand, plain-words adjustments, filtering, editing, and using items up |
| `js/shopping.js` | The shopping list and moving checked entries into the pantry |
| `js/recipes.js` | Suggestions, "Can I make…", recipe cards (cook, tweak, save, add missing to the list), and the recipe box |
| `js/chat.js` | The chat history and streaming replies; Enter sends, Shift+Enter adds a line |
| `js/notes.js` | The kitchen notes dialog |

Sections talk through the event bus rather than calling each other: anything that changes the pantry emits `pantry`, and the pantry reloads itself. The same goes for `shopping` and `box`.

## Rules

- User and AI text is only ever set with `textContent` (through `el`). Nothing is assigned to `innerHTML`.
- Every button that calls the server is disabled while its request runs (most through `busy`), so double clicks can't submit twice. Buttons for things that only make sense once, like "I cooked this" and "Save to recipe box", stay disabled afterwards.
- Lists reload through `latestOnly`, so a slow older response never overwrites a newer one, and re-render through `keepFocus`, so keyboard focus survives. An item being edited keeps its open form across reloads.
- Logging out, or a session ending, clears everything the account left on the page.
- Every color, space, and font is a custom property at the top of `css/base.css`, with the dark palette redefining the same names.
- Freshness has one class per status (`freshness-expired`, `-today`, `-soon`, `-fresh`, `-none`) so it can be restyled in one place.
