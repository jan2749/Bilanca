"""Zaznava ponavljajočih bremenitev (naročnin), tihih podražitev in pozabljenih naročnin.

Pristop:
- Odhodke združimo po (normaliziran prejemnik, znesek). Stalen znesek pri istem prejemniku
  v rednem ritmu je močan znak naročnine.
- Period ocenimo iz mediane razmikov med datumi (mesečno/tedensko/14-dnevno/letno).
- Tiho podražitev zaznamo, ko ima isti prejemnik starejšo (zaključeno) serijo in novejšo
  serijo z višjim zneskom, ki se začne po koncu starejše.

Več zgodovine = boljša zaznava; z malo meseci so serije kratke.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlmodel import Session, select

from bilanca.models import Account, Transaction

MIN_OCCURRENCES = 2  # naročnina se pri mesečnem ritmu pokaže že v 2–3 mesecih

# Razponi razmikov (v dnevih) → oznaka periode in tipično trajanje.
# Namenoma zajemamo le mesečni in letni ritem: naročnine so periodične bremenitve,
# medtem ko so tedenski enaki nakupi (kosilo, avtomat) navada, ne naročnina.
PERIODS = [
    ("mesečno", (24, 37), 30),
    ("letno", (330, 400), 365),
]


@dataclass
class Subscription:
    label: str
    merchant_key: str
    amount_eur: float
    period_label: str
    period_days: int
    count: int
    first_date: date
    last_date: date
    next_expected: date
    is_active: bool


@dataclass
class PriceHike:
    label: str
    old_eur: float
    new_eur: float
    changed_around: date
    pct: float


@dataclass
class RecurringReport:
    subscriptions: list[Subscription] = field(default_factory=list)
    price_hikes: list[PriceHike] = field(default_factory=list)

    @property
    def active(self) -> list[Subscription]:
        return [s for s in self.subscriptions if s.is_active]

    @property
    def monthly_cost_eur(self) -> float:
        """Ocena mesečnega stroška aktivnih naročnin (preračunano na mesec)."""
        total = 0.0
        for s in self.active:
            total += s.amount_eur * (30 / s.period_days)
        return round(total, 2)


def normalize_merchant(text: str) -> str:
    t = (text or "").casefold().strip()
    return re.sub(r"\s+", " ", t)


def _classify(median_gap: float) -> tuple[str, int] | None:
    for label, (lo, hi), days in PERIODS:
        if lo <= median_gap <= hi:
            return label, days
    return None


def detect(
    session: Session,
    user_id: int | None = None,
    min_occurrences: int = MIN_OCCURRENCES,
    as_of: date | None = None,
) -> RecurringReport:
    """Zazna naročnine in podražitve. Če je podan user_id, le za tega uporabnika."""
    query = select(Transaction).where(Transaction.amount_cents < 0)
    if user_id is not None:
        query = query.where(
            Transaction.account_id.in_(select(Account.id).where(Account.user_id == user_id))
        )
    txns = list(session.exec(query).all())
    if not txns:
        return RecurringReport()

    reference = as_of or max(t.booking_date for t in txns)

    # Združi po (prejemnik, znesek).
    groups: dict[tuple[str, int], list[Transaction]] = {}
    labels: dict[str, dict[str, int]] = {}  # merchant_key -> {original_purpose: count}
    for t in txns:
        key = normalize_merchant(t.purpose or t.counterparty_name)
        groups.setdefault((key, t.amount_cents), []).append(t)
        labels.setdefault(key, {})
        orig = (t.purpose or t.counterparty_name).strip()
        labels[key][orig] = labels[key].get(orig, 0) + 1

    def label_for(merchant_key: str) -> str:
        opts = labels.get(merchant_key, {})
        return max(opts, key=opts.get) if opts else merchant_key

    subs: list[Subscription] = []
    for (merchant_key, amount_cents), items in groups.items():
        if len(items) < min_occurrences:
            continue
        dates = sorted(t.booking_date for t in items)
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue
        period = _classify(statistics.median(gaps))
        if period is None:
            continue
        period_label, period_days = period
        last_date = dates[-1]
        subs.append(
            Subscription(
                label=label_for(merchant_key),
                merchant_key=merchant_key,
                amount_eur=round(-amount_cents / 100, 2),
                period_label=period_label,
                period_days=period_days,
                count=len(items),
                first_date=dates[0],
                last_date=last_date,
                next_expected=last_date + timedelta(days=period_days),
                is_active=(reference - last_date).days <= period_days * 1.5,
            )
        )

    subs.sort(key=lambda s: s.amount_eur, reverse=True)

    # Tihe podražitve: isti prejemnik, novejša serija z višjim zneskom po koncu starejše.
    hikes: list[PriceHike] = []
    by_merchant: dict[str, list[Subscription]] = {}
    for s in subs:
        by_merchant.setdefault(s.merchant_key, []).append(s)
    for merchant_key, series in by_merchant.items():
        if len(series) < 2:
            continue
        ordered = sorted(series, key=lambda s: s.first_date)
        for older, newer in zip(ordered, ordered[1:]):
            if newer.amount_eur > older.amount_eur and newer.first_date >= older.last_date:
                hikes.append(
                    PriceHike(
                        label=label_for(merchant_key),
                        old_eur=older.amount_eur,
                        new_eur=newer.amount_eur,
                        changed_around=newer.first_date,
                        pct=round((newer.amount_eur / older.amount_eur - 1) * 100, 1),
                    )
                )

    return RecurringReport(subscriptions=subs, price_hikes=hikes)
