"""Spletne poti: pregled, transakcije, uvoz."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from bilanca.categorize.rules import apply_rules, set_category
from bilanca.config import TEMPLATES_DIR
from bilanca.db import get_session
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.ingest.profiles.nkbm import NkbmParseError
from bilanca.insights.recurring import detect as detect_recurring
from bilanca.insights.trends import monthly_summary, spending_by_category
from bilanca.models import Account, Category, Transaction

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    txns = session.exec(select(Transaction)).all()
    income = sum(t.amount_cents for t in txns if t.amount_cents > 0)
    expense = sum(t.amount_cents for t in txns if t.amount_cents < 0)

    by_cat = spending_by_category(session)
    months = monthly_summary(session)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tx_count": len(txns),
            "income": income,
            "expense": expense,
            "cat_labels": [s.name for s in by_cat],
            "cat_values": [s.amount_eur for s in by_cat],
            "cat_colors": [s.color for s in by_cat],
            "month_labels": [m.month for m in months],
            "month_income": [m.income_eur for m in months],
            "month_expense": [m.expense_eur for m in months],
        },
    )


@router.get("/transactions", response_class=HTMLResponse)
def transactions(request: Request, session: Session = Depends(get_session)):
    txns = session.exec(
        select(Transaction).order_by(Transaction.booking_date.desc(), Transaction.id.desc())
    ).all()
    account = session.exec(select(Account)).first()
    categories = session.exec(select(Category).order_by(Category.kind, Category.name)).all()
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {"transactions": txns, "account": account, "categories": categories},
    )


@router.post("/transactions/{txn_id}/categorize")
def categorize_txn(
    txn_id: int,
    category_id: int | None = Form(None),
    create_rule: bool = Form(False),
    session: Session = Depends(get_session),
):
    set_category(session, txn_id, category_id, create_rule=create_rule)
    return RedirectResponse(url="/transactions", status_code=303)


@router.post("/recategorize")
def recategorize(session: Session = Depends(get_session)):
    apply_rules(session, only_uncategorized=True)
    return RedirectResponse(url="/transactions", status_code=303)


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(request: Request, session: Session = Depends(get_session)):
    report = detect_recurring(session)
    return templates.TemplateResponse(
        request,
        "subscriptions.html",
        {"report": report},
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
