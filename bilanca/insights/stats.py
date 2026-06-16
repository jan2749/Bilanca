"""Podrobna statistika za /stats stran.

Brez razčlenitve po kategorijah — fokus na denarnih tokovih skozi čas, vzorcih porabe
in prejemnikih. Vse agregacije podpirajo poljubno datumsko okno in granularnost
(teden / mesec / četrtletje / leto), da si uporabnik podatke pogleda kakor želi.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlmodel import Session

from bilanca.insights.trends import _scoped_txns
from bilanca.models import Transaction

SLO_MONTH_ABBR = [
    "jan", "feb", "mar", "apr", "maj", "jun",
    "jul", "avg", "sep", "okt", "nov", "dec",
]
SLO_WEEKDAYS = ["Pon", "Tor", "Sre", "Čet", "Pet", "Sob", "Ned"]


def _period_key_label(d: date, granularity: str) -> tuple[str, str]:
    """Vrne (sortirni ključ, prikazna oznaka) za dan glede na granularnost."""
    if granularity == "week":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}", f"T{iso[1]:02d} {iso[0]}"
    if granularity == "quarter":
        q = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{q}", f"Q{q} {d.year}"
    if granularity == "year":
        return f"{d.year}", f"{d.year}"
    # mesec (privzeto)
    return f"{d.year}-{d.month:02d}", f"{SLO_MONTH_ABBR[d.month - 1]} {d.year}"


@dataclass
class PeriodPoint:
    key: str
    label: str
    income_eur: float
    expense_eur: float
    net_eur: float
    savings_rate: float | None  # delež prihrankov glede na prihodke (%), None če ni prihodkov


def period_series(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    granularity: str = "month",
) -> list[PeriodPoint]:
    """Prihodki, odhodki, neto in stopnja varčevanja po obdobjih, naraščajoče po času."""
    income: dict[str, int] = defaultdict(int)
    expense: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}

    for t in session.exec(_scoped_txns(user_id, date_from, date_to)).all():
        key, label = _period_key_label(t.booking_date, granularity)
        labels[key] = label
        if t.amount_cents >= 0:
            income[key] += t.amount_cents
        else:
            expense[key] += -t.amount_cents

    points: list[PeriodPoint] = []
    for key in sorted(set(income) | set(expense)):
        inc = income[key] / 100
        exp = expense[key] / 100
        net = round(inc - exp, 2)
        savings_rate = round((inc - exp) / inc * 100, 1) if inc > 0 else None
        points.append(
            PeriodPoint(
                key=key,
                label=labels[key],
                income_eur=round(inc, 2),
                expense_eur=round(exp, 2),
                net_eur=net,
                savings_rate=savings_rate,
            )
        )
    return points


@dataclass
class StatsSummary:
    months_count: int
    avg_income_eur: float
    avg_expense_eur: float
    total_income_eur: float
    total_expense_eur: float
    best_month: str | None
    best_month_net: float
    worst_month: str | None
    worst_month_net: float


def stats_summary(monthly_points: list[PeriodPoint]) -> StatsSummary:
    """Povzetek za stat kartice. Vedno računan na MESEČNIH točkah (stabilne kartice)."""
    if not monthly_points:
        return StatsSummary(0, 0.0, 0.0, 0.0, 0.0, None, 0.0, None, 0.0)

    n = len(monthly_points)
    total_inc = round(sum(p.income_eur for p in monthly_points), 2)
    total_exp = round(sum(p.expense_eur for p in monthly_points), 2)
    best = max(monthly_points, key=lambda p: p.net_eur)
    worst = min(monthly_points, key=lambda p: p.net_eur)

    return StatsSummary(
        months_count=n,
        avg_income_eur=round(total_inc / n, 2),
        avg_expense_eur=round(total_exp / n, 2),
        total_income_eur=total_inc,
        total_expense_eur=total_exp,
        best_month=best.label,
        best_month_net=best.net_eur,
        worst_month=worst.label,
        worst_month_net=worst.net_eur,
    )


def spending_by_weekday(
    session: Session,
    user_id: int,
    period_from: date | None,
    period_to: date | None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[str], list[float]]:
    """Povprečna poraba (€) po dnevih v tednu — pokaže, kdaj uporabnik največ zapravlja.

    Povprečimo z dejanskim številom pojavitev posameznega dneva v obdobju, da daljši
    meseci/leta ne popačijo rezultata.
    """
    if period_from is None or period_to is None:
        return SLO_WEEKDAYS, [0.0] * 7

    totals = [0] * 7
    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        totals[t.booking_date.weekday()] += -t.amount_cents

    counts = [0] * 7
    d = period_from
    while d <= period_to:
        counts[d.weekday()] += 1
        d += timedelta(days=1)

    avg = [
        round(totals[i] / 100 / counts[i], 2) if counts[i] else 0.0 for i in range(7)
    ]
    return SLO_WEEKDAYS, avg


@dataclass
class MerchantRow:
    name: str
    total_eur: float
    tx_count: int


def top_merchants(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 10,
) -> list[MerchantRow]:
    """Top `limit` prejemnikov po skupni vrednosti odhodkov, padajoče."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)

    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        name = (t.counterparty_name or t.purpose or "—").strip()
        totals[name] += -t.amount_cents
        counts[name] += 1

    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [
        MerchantRow(name=name, total_eur=round(cents / 100, 2), tx_count=counts[name])
        for name, cents in top
    ]
