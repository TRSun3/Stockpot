"""The web app: the JSON API under /api and the frontend's static files at /."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Stockpot")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
