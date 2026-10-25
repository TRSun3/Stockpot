"""Accounts and sessions: salted password hashes, a session token in an HTTP-only cookie."""

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from stockpot.deps import get_db
from stockpot.schemas import Credentials

COOKIE = "stockpot_session"
ITERATIONS = 200_000
SESSION_DAYS = 30

router = APIRouter(prefix="/api")


@dataclass(frozen=True)
class User:
    id: int
    username: str


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()


def create_user(conn: sqlite3.Connection, username: str, password: str) -> User:
    """Stores a new account. Raises `ValueError` when the username is taken, ignoring case."""
    salt = secrets.token_hex(16)
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, hash_password(password, salt), salt),
        )
    except sqlite3.IntegrityError:
        raise ValueError("That username is taken.") from None
    return User(cursor.lastrowid, username)


UNKNOWN_SALT = secrets.token_hex(16)


def verify(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """The user these credentials belong to, or None. Unknown usernames take as long as wrong passwords."""
    row = conn.execute("SELECT id, username, password_hash, salt FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        hash_password(password, UNKNOWN_SALT)
        return None
    if not hmac.compare_digest(hash_password(password, row["salt"]), row["password_hash"]):
        return None
    return User(row["id"], row["username"])


def start_session(conn: sqlite3.Connection, user: User, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE created_at <= datetime('now', ?)", (f"-{SESSION_DAYS} days",))
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user.id))
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", path="/")


Conn = Annotated[sqlite3.Connection, Depends(get_db)]


def current_user(request: Request, conn: Conn) -> User:
    """The logged-in user, or a 401 when the session cookie is missing, unknown, or expired."""
    token = request.cookies.get(COOKIE)
    row = None
    if token:
        row = conn.execute(
            "SELECT users.id, users.username FROM sessions JOIN users ON users.id = sessions.user_id "
            "WHERE sessions.token = ? AND sessions.created_at > datetime('now', ?)",
            (token, f"-{SESSION_DAYS} days"),
        ).fetchone()
    if row is None:
        raise HTTPException(401, "Please log in.")
    return User(row["id"], row["username"])


CurrentUser = Annotated[User, Depends(current_user)]


def profile(request: Request, user: User) -> dict:
    """Who is logged in and which LLM backend answers them; signup, login, and /api/me all return this."""
    return {"username": user.username, "llm": request.app.state.settings.backend}


@router.post("/auth/signup", status_code=201)
def signup(body: Credentials, request: Request, response: Response, conn: Conn) -> dict:
    try:
        user = create_user(conn, body.username, body.password)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    start_session(conn, user, response)
    return profile(request, user)


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, conn: Conn) -> dict:
    user = verify(conn, body.username, body.password)
    if user is None:
        raise HTTPException(401, "Wrong username or password.")
    start_session(conn, user, response)
    return profile(request, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, conn: Conn) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: CurrentUser) -> dict:
    return profile(request, user)
