"""Spletne poti: prijava/registracija, pregled, transakcije, uvoz."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from bilanca.auth import (
    COOKIE_NAME,
    SESSION_DAYS,
    create_session,
    destroy_session,
    get_current_user,
    hash_password,
    optional_current_user,
    verify_password,
)
from bilanca.categorize.rules import apply_rules, set_category
from bilanca.categorize.suggest import uncategorized_groups
from bilanca.config import TEMPLATES_DIR
from bilanca.db import get_session
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.ingest.profiles.nkbm import NkbmParseError
from bilanca.insights.recurring import detect as detect_recurring
from bilanca.insights.stats import (
    period_series,
    spending_by_weekday,
    stats_summary,
    top_merchants,
)
from bilanca.insights.trends import (
    coverage_gaps,
    monthly_summary,
    spending_by_category,
    yearly_comparison,
)
from bilanca.models import Account, Category, ImportBatch, Transaction, User

router = APIRouter()
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_COOKIE_MAX_AGE = SESSION_DAYS * 24 * 3600


def _set_session_cookie(resp: RedirectResponse, token: str) -> None:
    resp.set_cookie(
        COOKIE_NAME, token, httponly=True, samesite="lax", max_age=_COOKIE_MAX_AGE
    )


def _user_txns_query(user: User):
    return select(Transaction).where(
        Transaction.account_id.in_(select(Account.id).where(Account.user_id == user.id))
    )


# ---------------------------------------------------------------- prijava / registracija


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, user: User | None = Depends(optional_current_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {})


@router.post("/register")
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    ctx: dict = {"email": email}
    if not email or "@" not in email:
        ctx["error"] = "Vnesi veljaven e-naslov."
    elif len(password) < 8:
        ctx["error"] = "Geslo naj ima vsaj 8 znakov."
    elif session.exec(select(User).where(User.email == email)).first() is not None:
        ctx["error"] = "Uporabnik s tem e-naslovom že obstaja."
    if "error" in ctx:
        return templates.TemplateResponse(request, "register.html", ctx)

    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    session.refresh(user)
    token = create_session(session, user)
    resp = RedirectResponse("/", status_code=303)
    _set_session_cookie(resp, token)
    return resp


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, user: User | None = Depends(optional_current_user)):
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(get_session),
):
    email = email.strip().lower()
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"email": email, "error": "Napačen e-naslov ali geslo."},
        )
    token = create_session(session, user)
    resp = RedirectResponse("/", status_code=303)
    _set_session_cookie(resp, token)
    return resp


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_session)):
    destroy_session(session, request.cookies.get(COOKIE_NAME))
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------------------------------------------------------------- pregled / transakcije


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@router.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    od: str | None = None,
    do: str | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # Celoten razpon razpoložljivih podatkov (za prikaz in meje vnosov).
    bounds = session.exec(
        select(func.min(Transaction.booking_date), func.max(Transaction.booking_date)).where(
            Transaction.account_id.in_(select(Account.id).where(Account.user_id == user.id))
        )
    ).one()
    data_from, data_to = bounds  # lahko (None, None), če ni transakcij

    date_from = _parse_date(od)
    date_to = _parse_date(do)

    query = _user_txns_query(user)
    if date_from is not None:
        query = query.where(Transaction.booking_date >= date_from)
    if date_to is not None:
        query = query.where(Transaction.booking_date <= date_to)
    txns = session.exec(query).all()

    income = sum(t.amount_cents for t in txns if t.amount_cents > 0)
    expense = sum(t.amount_cents for t in txns if t.amount_cents < 0)  # negativen

    by_cat = spending_by_category(session, user.id, date_from, date_to)

    period_from = date_from or data_from
    period_to = date_to or data_to
    # Za daljša obdobja (>2 leti) je mesečni prikaz preveč skrčen, zato preklopimo na leta.
    granularity = "month"
    if period_from and period_to:
        span_months = (period_to.year - period_from.year) * 12 + (
            period_to.month - period_from.month
        ) + 1
        if span_months > 24:
            granularity = "year"
    months = monthly_summary(session, user.id, date_from, date_to, granularity=granularity)
    month_saldo = [round(m.income_eur - m.expense_eur, 2) for m in months]

    yoy = yearly_comparison(session, user.id, date_from, date_to)

    # Vrzeli med uvozi (npr. uvožena obdobja 1.1.-1.2. in 15.2.-28.2. → manjka 2.2.-14.2.),
    # ki sodijo v prikazano obdobje.
    gaps = []
    if period_from and period_to:
        for gap_from, gap_to in coverage_gaps(session, user.id):
            if gap_from <= period_to and gap_to >= period_from:
                gaps.append(
                    (max(gap_from, period_from), min(gap_to, period_to))
                )

    # Dodatne statistike (vse v izbranem obdobju).
    avg_monthly_expense = (-expense / 100 / len(months)) if months else 0.0
    savings_rate = ((income + expense) / income * 100) if income > 0 else None
    expenses = [t for t in txns if t.amount_cents < 0]
    biggest = min(expenses, key=lambda t: t.amount_cents, default=None)
    biggest_expense = (
        {
            "amount_eur": -biggest.amount_cents / 100,
            "label": (biggest.purpose or biggest.counterparty_name or "—").strip(),
        }
        if biggest is not None
        else None
    )
    # Največji prejemnik po skupni porabi.
    merchant_totals: dict[str, int] = {}
    for t in expenses:
        key = (t.counterparty_name or t.purpose or "—").strip()
        merchant_totals[key] = merchant_totals.get(key, 0) + (-t.amount_cents)
    top_merchant = None
    if merchant_totals:
        name, cents = max(merchant_totals.items(), key=lambda kv: kv[1])
        top_merchant = {"name": name, "amount_eur": cents / 100}

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "tx_count": len(txns),
            "income": income,
            "expense": expense,
            "od": od or "",
            "do": do or "",
            "data_from": data_from,
            "data_to": data_to,
            "period_from": period_from,
            "period_to": period_to,
            "is_filtered": bool(date_from or date_to),
            "avg_monthly_expense": avg_monthly_expense,
            "savings_rate": savings_rate,
            "biggest_expense": biggest_expense,
            "top_merchant": top_merchant,
            "cat_labels": [s.name for s in by_cat],
            "cat_values": [s.amount_eur for s in by_cat],
            "cat_colors": [s.color for s in by_cat],
            "month_labels": [m.month for m in months],
            "month_income": [m.income_eur for m in months],
            "month_expense": [m.expense_eur for m in months],
            "month_saldo": month_saldo,
            "granularity": granularity,
            "yoy": yoy,
            "gaps": gaps,
        },
    )


@router.get("/transactions", response_class=HTMLResponse)
def transactions(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    txns = session.exec(
        _user_txns_query(user).order_by(
            Transaction.booking_date.desc(), Transaction.id.desc()
        )
    ).all()
    account = session.exec(select(Account).where(Account.user_id == user.id)).first()
    categories = session.exec(select(Category).order_by(Category.kind, Category.name)).all()
    txns_json = [
        {
            "id": t.id,
            "date": t.booking_date.strftime("%Y-%m-%d"),
            "dateLabel": t.booking_date.strftime("%d.%m.%Y"),
            "desc": t.purpose or "",
            "cp": t.counterparty_name
            if (t.counterparty_name and t.counterparty_name != t.purpose)
            else "",
            "cents": t.amount_cents,
            "catId": t.category_id,
        }
        for t in txns
    ]
    cats_json = [{"id": c.id, "name": c.name} for c in categories]
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "user": user,
            "transactions": txns,
            "account": account,
            "categories": categories,
            "txns_json": txns_json,
            "cats_json": cats_json,
        },
    )


@router.post("/transactions/{txn_id}/categorize")
def categorize_txn(
    txn_id: int,
    category_id: int | None = Form(None),
    create_rule: bool = Form(False),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    set_category(session, user, txn_id, category_id, create_rule=create_rule)
    return RedirectResponse(url="/transactions", status_code=303)


@router.post("/recategorize")
def recategorize(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    apply_rules(session, user, only_uncategorized=True)
    return RedirectResponse(url="/transactions", status_code=303)


@router.get("/categorize/suggestions", response_class=HTMLResponse)
def suggestions_page(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    groups = uncategorized_groups(session, user)
    categories = session.exec(
        select(Category).where(Category.kind == "expense").order_by(Category.name)
    ).all()
    return templates.TemplateResponse(
        request,
        "categorize_suggestions.html",
        {"user": user, "groups": groups, "categories": categories},
    )


@router.post("/categorize/suggestions")
def apply_suggestions(
    txn_id: list[int] = Form(default=[]),
    category_id: list[str] = Form(default=[]),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    # txn_id in category_id sta poravnana po vrstnem redu vrstic; prazne preskočimo.
    for tid, cid in zip(txn_id, category_id):
        if cid:
            set_category(session, user, tid, int(cid), create_rule=True)
    return RedirectResponse(url="/categorize/suggestions", status_code=303)


@router.get("/subscriptions", response_class=HTMLResponse)
def subscriptions(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    report = detect_recurring(session, user.id)
    return templates.TemplateResponse(
        request,
        "subscriptions.html",
        {"user": user, "report": report},
    )


# ---------------------------------------------------------------- statistika


_GRAN_OPTIONS = [
    ("auto", "Samodejno"),
    ("week", "Teden"),
    ("month", "Mesec"),
    ("quarter", "Četrtletje"),
    ("year", "Leto"),
]


@router.get("/stats", response_class=HTMLResponse)
def stats_page(
    request: Request,
    od: str | None = None,
    do: str | None = None,
    gran: str | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    bounds = session.exec(
        select(func.min(Transaction.booking_date), func.max(Transaction.booking_date)).where(
            Transaction.account_id.in_(select(Account.id).where(Account.user_id == user.id))
        )
    ).one()
    data_from, data_to = bounds

    date_from = _parse_date(od)
    date_to = _parse_date(do)
    period_from = date_from or data_from
    period_to = date_to or data_to

    span_months = 0
    if period_from and period_to:
        span_months = (
            (period_to.year - period_from.year) * 12
            + (period_to.month - period_from.month)
            + 1
        )

    # Granularnost: uporabnikova izbira, sicer samodejno glede na dolžino obdobja.
    gran = (gran or "auto").lower()
    if gran not in {"auto", "week", "month", "quarter", "year"}:
        gran = "auto"
    if gran == "auto":
        if span_months > 36:
            granularity = "year"
        elif span_months > 18:
            granularity = "quarter"
        elif span_months <= 4:
            granularity = "week"
        else:
            granularity = "month"
    else:
        granularity = gran

    # Kartice vedno na mesečnih točkah → stabilne, smiselne vrednosti.
    monthly_points = period_series(session, user.id, date_from, date_to, "month")
    summary = stats_summary(monthly_points)

    # Grafi v izbrani granularnosti.
    points = period_series(session, user.id, date_from, date_to, granularity)
    cumulative: list[float] = []
    running = 0.0
    for p in points:
        running += p.net_eur
        cumulative.append(round(running, 2))

    weekday_labels, weekday_values = spending_by_weekday(
        session, user.id, period_from, period_to, date_from, date_to
    )
    merchants = top_merchants(session, user.id, date_from, date_to)

    # Hitre časovne predloge, sidrane na zadnji uvožen datum.
    presets = []
    if data_to:
        for label, days in [("30 dni", 30), ("3 mesece", 90), ("6 mesecev", 180), ("1 leto", 365)]:
            start = max(data_from, data_to - timedelta(days=days)) if data_from else data_to - timedelta(days=days)
            presets.append({"label": label, "od": start.isoformat(), "do": data_to.isoformat()})
        presets.append({"label": "Vse", "od": "", "do": ""})

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "user": user,
            "data_from": data_from,
            "data_to": data_to,
            "period_from": period_from,
            "period_to": period_to,
            "od": od or "",
            "do": do or "",
            "gran": gran,
            "granularity": granularity,
            "gran_options": _GRAN_OPTIONS,
            "presets": presets,
            "is_filtered": bool(date_from or date_to),
            "summary": summary,
            "merchants": merchants,
            "chart_labels": [p.label for p in points],
            "chart_income": [p.income_eur for p in points],
            "chart_expense": [p.expense_eur for p in points],
            "chart_net": [p.net_eur for p in points],
            "chart_savings": [p.savings_rate for p in points],
            "chart_cumulative": cumulative,
            "weekday_labels": weekday_labels,
            "weekday_values": weekday_values,
            "merchant_names": [m.name for m in merchants],
            "merchant_values": [m.total_eur for m in merchants],
            "merchant_counts": [m.tx_count for m in merchants],
        },
    )


# ---------------------------------------------------------------- uvoz


def _user_import_batches(session: Session, user: User) -> list[dict]:
    batches = session.exec(
        select(ImportBatch)
        .where(ImportBatch.user_id == user.id)
        .order_by(ImportBatch.imported_at.desc())
    ).all()
    result = []
    for b in batches:
        bounds = session.exec(
            select(
                func.min(Transaction.booking_date), func.max(Transaction.booking_date)
            ).where(Transaction.import_batch_id == b.id)
        ).one()
        result.append({"batch": b, "date_from": bounds[0], "date_to": bounds[1]})
    return result


@router.get("/import", response_class=HTMLResponse)
def import_page(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request, "import.html", {"user": user, "batches": _user_import_batches(session, user)}
    )


@router.post("/import", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    raw = await file.read()
    ctx: dict = {"user": user}
    try:
        source = NkbmCsvSource(raw)
        batch = import_source(session, source, user, filename=file.filename or "")
        ctx["result"] = batch
        groups = uncategorized_groups(session, user)
        ctx["uncat_merchants"] = len(groups)
        ctx["uncat_txns"] = sum(g.count for g in groups)
    except NkbmParseError as exc:
        ctx["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 — uporabniku prijazno sporočilo namesto 500
        ctx["error"] = f"Nepričakovana napaka pri uvozu: {exc}"
    ctx["batches"] = _user_import_batches(session, user)
    return templates.TemplateResponse(request, "import.html", ctx)


@router.post("/import/{batch_id}/delete")
def delete_import_batch(
    batch_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    batch = session.get(ImportBatch, batch_id)
    if batch is not None and batch.user_id == user.id:
        for txn in session.exec(
            select(Transaction).where(Transaction.import_batch_id == batch_id)
        ).all():
            session.delete(txn)
        session.delete(batch)
        session.commit()
    return RedirectResponse(url="/import", status_code=303)
