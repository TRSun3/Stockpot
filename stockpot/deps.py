"""What each request is handed: a database connection, today's date, and the LLM backend."""

import sqlite3
from collections.abc import Iterator
from datetime import date
from typing import Annotated

from fastapi import Depends, Path, Request

from stockpot.llm import LLM


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with request.app.state.pool.connection() as conn:
        yield conn


def get_today(request: Request) -> date:
    return request.app.state.today()


def get_llm(request: Request) -> LLM:
    return request.app.state.llm


Today = Annotated[date, Depends(get_today)]
Model = Annotated[LLM, Depends(get_llm)]
# A row id in a URL. Anything larger than SQLite can hold is refused as invalid rather than crashing a query.
RowId = Annotated[int, Path(ge=1, le=2**63 - 1)]
