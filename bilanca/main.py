"""Vstopna tocka FastAPI aplikacije Bilanca."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bilanca.config import STATIC_DIR
from bilanca.db import init_db
from bilanca.web.routes import router


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


app.include_router(router)
