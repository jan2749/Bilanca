"""Agregacije za nadzorno ploščo: poraba po kategorijah in mesečni trendi.

Zneski so v centih; vrednosti za prikaz se pretvorijo v evre v predlogi/grafih.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

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
) -> list[MonthRow]:
    """Prihodki in odhodki po mesecih (po datumu knjiženja), naraščajoče po mesecu."""
    income: dict[str, int] = defaultdict(int)
    expense: dict[str, int] = defaultdict(int)
    for t in session.exec(_scoped_txns(user_id, date_from, date_to)).all():
        month = t.booking_date.strftime("%Y-%m")
        if t.amount_cents >= 0:
            income[month] += t.amount_cents
        else:
            expense[month] += -t.amount_cents

    months = sorted(set(income) | set(expense))
    return [
        MonthRow(
            month=m,
            income_eur=round(income[m] / 100, 2),
            expense_eur=round(expense[m] / 100, 2),
        )
        for m in months
    ]
