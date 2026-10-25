"""The web app: the JSON API under /api and the frontend's static files at /."""

import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from stockpot import auth, chat, config, db, kitchen, pantry, preferences, recipes, shopping
from stockpot.llm import LLM, LLMBusy, LLMError, get_llm

STATIC = Path(__file__).resolve().parent.parent / "static"

MAX_BODY = 256 * 1024

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
        app.state.pool.close()

    app = FastAPI(title="Stockpot", lifespan=lifespan)
    app.state.settings = settings
    app.state.pool = db.Pool(settings.db_path)
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
        return JSONResponse({"error": error.friendly}, status_code=429 if isinstance(error, LLMBusy) else 502)

    @app.exception_handler(Exception)
    async def server_error(request: Request, error: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse({"error": "Something went wrong on our side. Please try again."}, status_code=500)

    @app.middleware("http")
    async def limit_body(request: Request, call_next) -> Response:
        """Refuses request bodies over 256 KB before reading them; nothing Stockpot accepts comes close."""
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > MAX_BODY:
            return JSONResponse({"error": "That request is too large."}, status_code=413)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    for module in (auth, kitchen, pantry, shopping, recipes, chat, preferences):
        app.include_router(module.router)
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
