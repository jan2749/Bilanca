"""Podrobna statistika za /stats stran: razčlenitev po kategorijah, trendi, prejemniki."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from bilanca.insights.trends import UNCATEGORIZED_COLOR, _scoped_txns
from bilanca.models import Category, Transaction
from bilanca.seed import UNCATEGORIZED_NAME


@dataclass
class MerchantRow:
    name: str
    total_eur: float
    tx_count: int
    pct: float  # delež celotnih odhodkov (0–100)


@dataclass
class CategoryTrend:
    period_labels: list[str]  # "YYYY-MM" ali "YYYY"
    datasets: list[dict]      # [{label, color, data: [eur, ...]}, ...]


@dataclass
class StatsSummary:
    months_count: int
    avg_income_eur: float
    avg_expense_eur: float
    best_month: str | None      # oznaka obdobja
    best_month_net: float
    worst_month: str | None
    worst_month_net: float


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
    total_expense = 0

    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        name = (t.counterparty_name or t.purpose or "—").strip()
        totals[name] += -t.amount_cents
        counts[name] += 1
        total_expense += -t.amount_cents

    top = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [
        MerchantRow(
            name=name,
            total_eur=round(cents / 100, 2),
            tx_count=counts[name],
            pct=round(cents / total_expense * 100, 1) if total_expense > 0 else 0.0,
        )
        for name, cents in top
    ]


def monthly_by_category(
    session: Session,
    user_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    granularity: str = "month",
    top_n: int = 7,
) -> CategoryTrend:
    """Odhodki po kategorijah in obdobjih za zloženi stolpčni graf.

    Vrne top `top_n` kategorij po skupni porabi; preostanek združi v 'Ostalo'.
    """
    fmt = "%Y" if granularity == "year" else "%Y-%m"
    cats = {c.id: c for c in session.exec(select(Category)).all()}

    period_totals: dict[tuple[str, int | None], int] = defaultdict(int)
    all_periods: set[str] = set()

    query = _scoped_txns(user_id, date_from, date_to).where(Transaction.amount_cents < 0)
    for t in session.exec(query).all():
        period = t.booking_date.strftime(fmt)
        all_periods.add(period)
        period_totals[(period, t.category_id)] += -t.amount_cents

    periods = sorted(all_periods)

    # Skupna poraba po kategoriji (za razvrščanje).
    cat_totals: dict[int | None, int] = defaultdict(int)
    for (_, cat_id), amt in period_totals.items():
        cat_totals[cat_id] += amt

    top_pairs = sorted(cat_totals.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    top_cat_ids = {cat_id for cat_id, _ in top_pairs}
    has_other = len(cat_totals) > top_n

    datasets: list[dict] = []
    for cat_id, _ in top_pairs:
        if cat_id is None:
            name, color = UNCATEGORIZED_NAME, UNCATEGORIZED_COLOR
        else:
            cat = cats.get(cat_id)
            name = cat.name if cat else UNCATEGORIZED_NAME
            color = (cat.color if cat else None) or UNCATEGORIZED_COLOR
        data = [round(period_totals.get((p, cat_id), 0) / 100, 2) for p in periods]
        datasets.append({"label": name, "color": color, "data": data})

    if has_other:
        other_by_period: dict[str, int] = defaultdict(int)
        for (period, cat_id), amt in period_totals.items():
            if cat_id not in top_cat_ids:
                other_by_period[period] += amt
        datasets.append({
            "label": "Ostalo",
            "color": "#6b7280",
            "data": [round(other_by_period.get(p, 0) / 100, 2) for p in periods],
        })

    return CategoryTrend(period_labels=periods, datasets=datasets)


def stats_summary(monthly_rows: list) -> StatsSummary:
    """Povzetek za stat kartice iz že izračunanih mesečnih vrstic (MonthRow)."""
    if not monthly_rows:
        return StatsSummary(0, 0.0, 0.0, None, 0.0, None, 0.0)

    n = len(monthly_rows)
    avg_inc = round(sum(r.income_eur for r in monthly_rows) / n, 2)
    avg_exp = round(sum(r.expense_eur for r in monthly_rows) / n, 2)

    nets = [(r.month, round(r.income_eur - r.expense_eur, 2)) for r in monthly_rows]
    best = max(nets, key=lambda x: x[1])
    worst = min(nets, key=lambda x: x[1])

    return StatsSummary(
        months_count=n,
        avg_income_eur=avg_inc,
        avg_expense_eur=avg_exp,
        best_month=best[0],
        best_month_net=best[1],
        worst_month=worst[0],
        worst_month_net=worst[1],
    )
