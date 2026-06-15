"""Spletne poti: pregled, transakcije, uvoz."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from bilanca.config import TEMPLATES_DIR
from bilanca.db import get_session
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.ingest.profiles.nkbm import NkbmParseError
from bilanca.models import Account, Transaction

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    txns = session.exec(select(Transaction)).all()
    income = sum(t.amount_cents for t in txns if t.amount_cents > 0)
    expense = sum(t.amount_cents for t in txns if t.amount_cents < 0)
    return templates.TemplateResponse(
        request,
        "index.html",
        {"tx_count": len(txns), "income": income, "expense": expense},
    )


@router.get("/transactions", response_class=HTMLResponse)
def transactions(request: Request, session: Session = Depends(get_session)):
    txns = session.exec(
        select(Transaction).order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    ).all()
    account = session.exec(select(Account)).first()
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {"transactions": txns, "account": account},
    )


@router.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {})


@router.post("/import", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    raw = await file.read()
    ctx: dict = {}
    try:
        source = NkbmCsvSource(raw)
        batch = import_source(session, source, filename=file.filename or "")
        ctx["result"] = batch
    except NkbmParseError as exc:
        ctx["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — uporabniku prijazno sporočilo namesto 500
        ctx["error"] = f"Nepričakovana napaka pri uvozu: {exc}"
    return templates.TemplateResponse(request, "import.html", ctx)
