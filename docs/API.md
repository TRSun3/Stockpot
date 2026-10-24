# API

Every route is JSON under `/api`. Errors come back as `{"error": "a readable message"}` with a fitting status code. Everything except the auth routes and `/api/health` needs a logged-in session and answers 401 without one.

## Accounts

| Method | Path | Does |
|---|---|---|
| POST | `/api/auth/signup` | `{username, password}` creates an account and logs it in (201). 409 if the username is taken |
| POST | `/api/auth/login` | `{username, password}` logs in. 401 on a wrong username or password |
| POST | `/api/auth/logout` | Ends the session and clears the cookie |
| GET | `/api/me` | `{username, llm}`, where `llm` is `mock` or `gemini` |

Usernames are 3 to 32 letters, digits, `_`, `.`, or `-`, unique regardless of case. Passwords are 6 to 128 characters. Logging in sets an `HttpOnly`, `SameSite=Lax` cookie named `stockpot_session`. Each browser holds its own cookie, so a normal window and a private window can be logged in as different people at once.
