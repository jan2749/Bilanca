"""Agregacije za nadzorno ploščo: poraba po kategorijah in mesečni trendi.

Zneski so v centih; vrednosti za prikaz se pretvorijo v evre v predlogi/grafih.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from bilanca.models import Account, Category, Transaction
from bilanca.seed import UNCATEGORIZED_NAME

UNCATEGORIZED_COLOR = "#d1d5db"


def _scoped_txns(
    user_id: int, date_from: date | None = None, date_to: date | None = None
):
    """Osnovna poizvedba: transakcije uporabnika v (neobveznem) datumskem oknu."""
    query = select(Transaction).where(
        Transaction.account_id.in_(select(Account.id).where(Account.user_id == user_id))
    )
    if date_from is not None:
        query = query.where(Transaction.booking_date >= date_from)
    if date_to is not None:
        query = query.where(Transaction.booking_date <= date_to)
    return query


@dataclass
class CategorySlice:
    name: str
    color: str
    amount_eur: float


@dataclass
class MonthRow:
    month: str  # 'YYYY-MM'
    income_eur: float
    expense_eur: float


def spending_by_category(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CategorySlice]:
    """Vsota odhodkov (amount < 0) po kategorijah, padajoče. Nerazvrščeno združeno."""
    cats = {c.id: c for c in session.exec(select(Category)).all()}
    totals: dict[int | None, int] = defaultdict(int)
    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        totals[t.category_id] += -t.amount_cents

    slices: list[CategorySlice] = []
    for cat_id, cents in totals.items():
        if cat_id is None:
            name, color = UNCATEGORIZED_NAME, UNCATEGORIZED_COLOR
        else:
            cat = cats.get(cat_id)
            name = cat.name if cat else UNCATEGORIZED_NAME
            color = cat.color if cat else UNCATEGORIZED_COLOR
        slices.append(CategorySlice(name=name, color=color, amount_eur=round(cents / 100, 2)))
    slices.sort(key=lambda s: s.amount_eur, reverse=True)
    return slices


def monthly_summary(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    granularity: str = "month",
) -> list[MonthRow]:
    """Prihodki in odhodki po obdobjih (po datumu knjiženja), naraščajoče.

    `granularity` je "month" (privzeto, oznake "YYYY-MM") ali "year" (oznake "YYYY") -
    slednje se uporabi za daljša obdobja, kjer bi mesečni prikaz bil preveč skrčen.
    """
    fmt = "%Y" if granularity == "year" else "%Y-%m"
    income: dict[str, int] = defaultdict(int)
    expense: dict[str, int] = defaultdict(int)
    for t in session.exec(_scoped_txns(user_id, date_from, date_to)).all():
        period = t.booking_date.strftime(fmt)
        if t.amount_cents >= 0:
            income[period] += t.amount_cents
        else:
            expense[period] += -t.amount_cents

    periods = sorted(set(income) | set(expense))
    return [
        MonthRow(
            month=p,
            income_eur=round(income[p] / 100, 2),
            expense_eur=round(expense[p] / 100, 2),
        )
        for p in periods
    ]


SLO_MONTH_LABELS = [
    "jan", "feb", "mar", "apr", "maj", "jun",
    "jul", "avg", "sep", "okt", "nov", "dec",
]


@dataclass
class YearComparison:
    years: list[int]
    month_labels: list[str]
    expense_by_year: dict[int, list[float]]


def yearly_comparison(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
) -> YearComparison | None:
    """Odhodki po mesecih, primerjani med leti (za prikaz sezonskih vzorcev).

    Vrne None, če podatki pokrivajo manj kot dve leti - primerjava ne bi bila smiselna.
    """
    totals: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        totals[t.booking_date.year][t.booking_date.month] += -t.amount_cents

    years = sorted(totals)
    if len(years) < 2:
        return None

    expense_by_year = {
        year: [round(totals[year].get(m, 0) / 100, 2) for m in range(1, 13)]
        for year in years
    }
    return YearComparison(years=years, month_labels=SLO_MONTH_LABELS, expense_by_year=expense_by_year)


def coverage_gaps(session: Session, user_id: int) -> list[tuple[date, date]]:
    """Najde vrzeli med uvoženimi obdobji - npr. če dva uvoza ne pokrivata zaporednih datumov.

    Za vsak uvozni paket (`import_batch_id`) vzame razpon (min, max) datuma knjiženja
    njegovih transakcij, te razpone združi in vrne manjkajoče datumske razpone med njimi.
    """
    rows = session.exec(
        select(
            Transaction.import_batch_id,
            func.min(Transaction.booking_date),
            func.max(Transaction.booking_date),
        )
        .where(Transaction.account_id.in_(select(Account.id).where(Account.user_id == user_id)))
        .group_by(Transaction.import_batch_id)
    ).all()
    intervals = sorted((lo, hi) for _, lo, hi in rows if lo is not None and hi is not None)
    if len(intervals) < 2:
        return []

    merged = [intervals[0]]
    for lo, hi in intervals[1:]:
        last_lo, last_hi = merged[-1]
        if lo <= last_hi + timedelta(days=1):
            if hi > last_hi:
                merged[-1] = (last_lo, hi)
        else:
            merged.append((lo, hi))

    gaps: list[tuple[date, date]] = []
    for (_, prev_hi), (next_lo, _) in zip(merged, merged[1:]):
        if next_lo > prev_hi + timedelta(days=1):
            gaps.append((prev_hi + timedelta(days=1), next_lo - timedelta(days=1)))
    return gaps
