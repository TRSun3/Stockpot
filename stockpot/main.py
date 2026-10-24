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

from stockpot import auth, config, db, kitchen, pantry, shopping
from stockpot.llm import LLM, LLMError, get_llm

STATIC = Path(__file__).resolve().parent.parent / "static"

AI_UNAVAILABLE = "The AI cook couldn't answer just now. Nothing was changed; please try again in a moment."

log = logging.getLogger("uvicorn.error")


def describe(error: dict) -> str:
    """One readable sentence for a request validation error, naming the field it is about."""
    field = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
    message = error.get("msg", "Invalid value")
    return f"{field}: {message}" if field else message


def create_app(settings: config.Settings | None = None, llm: LLM | None = None) -> FastAPI:
    settings = settings or config.load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init(settings.db_path)
        log.info("Stockpot is using the %s LLM backend.", settings.backend)
        yield

    app = FastAPI(title="Stockpot", lifespan=lifespan)
    app.state.settings = settings
    app.state.today = date.today
    app.state.llm = llm or get_llm(settings)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": error.detail}, status_code=error.status_code, headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse({"error": describe(error.errors()[0])}, status_code=422)

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, error: LLMError) -> JSONResponse:
        log.warning("LLM call failed: %s", error)
        return JSONResponse({"error": AI_UNAVAILABLE}, status_code=502)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    for module in (auth, kitchen, pantry, shopping):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
