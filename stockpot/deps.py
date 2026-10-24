"""What each request is handed: a database connection, today's date, and the LLM backend."""

import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Request

from stockpot import db
from stockpot.llm import LLM


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_today(request: Request) -> date:
    return request.app.state.today()


def get_llm(request: Request) -> LLM:
    return request.app.state.llm


Today = Annotated[date, Depends(get_today)]
Model = Annotated[LLM, Depends(get_llm)]
