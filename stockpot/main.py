"""The web app: the JSON API under /api and the frontend's static files at /."""

import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from stockpot import auth, config, db

STATIC = Path(__file__).resolve().parent.parent / "static"

log = logging.getLogger("uvicorn.error")


def describe(error: dict) -> str:
    """One readable sentence for a request validation error, naming the field it is about."""
    field = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
    message = error.get("msg", "Invalid value")
    return f"{field}: {message}" if field else message


def create_app(settings: config.Settings | None = None, llm=None) -> FastAPI:
    settings = settings or config.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(settings.db_path)
        log.info("Stockpot is using the %s LLM backend.", settings.backend)
        yield

    app = FastAPI(title="Stockpot", lifespan=lifespan)
    app.state.settings = settings
    app.state.today = date.today
    app.state.llm = llm

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": describe(error.errors()[0])}, status_code=422)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    app.include_router(auth.router)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
