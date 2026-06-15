"""Vstopna tocka FastAPI aplikacije Bilanca."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from bilanca.config import STATIC_DIR
from bilanca.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ob zagonu pripravi bazo."""
    init_db()
    yield


app = FastAPI(title="Bilanca", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    """Preprost preverjevalnik delovanja."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Zacasna domaca stran (nadomesti jo dashboard v kasnejsem mejniku)."""
    return "<h1>Bilanca</h1><p>Aplikacija deluje. Nadzorna plo&scaron;&ccaron;a pride v naslednjih korakih.</p>"
