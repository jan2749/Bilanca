"""Predlogi kategorij za nerazvrščene odhodke (po uvozu).

Nerazvrščene, nezaklenjene odhodke združimo po normaliziranem prejemniku in jih
ponudimo uporabniku v razvrstitev. Ko razvrsti enega predstavnika skupine z
"ustvari pravilo za vse", se prek naučenega pravila razvrstijo še ostali.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from bilanca.insights.recurring import normalize_merchant
from bilanca.models import Account, Transaction, User


@dataclass
class UncategorizedGroup:
    label: str  # najpogostejši izvirni naziv prejemnika
    count: int
    total_eur: float
    txn_id: int  # predstavnik skupine (za set_category z učenjem pravila)


def uncategorized_groups(session: Session, user: User) -> list[UncategorizedGroup]:
    """Skupine nerazvrščenih odhodkov uporabnika, padajoče po skupni porabi."""
    txns = session.exec(
        select(Transaction).where(
            Transaction.account_id.in_(select(Account.id).where(Account.user_id == user.id)),
            Transaction.category_id == None,  # noqa: E711
            Transaction.category_locked == False,  # noqa: E712
            Transaction.amount_cents < 0,
        )
    ).all()

    groups: dict[str, dict] = {}
    for t in txns:
        raw = (t.counterparty_name or t.purpose or "").strip()
        key = normalize_merchant(t.counterparty_name or t.purpose)
        g = groups.setdefault(key, {"count": 0, "total": 0, "txn_id": t.id, "labels": {}})
        g["count"] += 1
        g["total"] += -t.amount_cents
        g["labels"][raw] = g["labels"].get(raw, 0) + 1

    result = [
        UncategorizedGroup(
            label=(max(g["labels"], key=g["labels"].get) if g["labels"] else key),
            count=g["count"],
            total_eur=round(g["total"] / 100, 2),
            txn_id=g["txn_id"],
        )
        for key, g in groups.items()
    ]
    result.sort(key=lambda x: x.total_eur, reverse=True)
    return result
