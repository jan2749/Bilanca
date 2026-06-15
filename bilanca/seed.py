"""Privzete kategorije ob inicializaciji baze."""

from __future__ import annotations

from sqlmodel import Session, select

from bilanca.models import Category, CategoryKind

# (ime, vrsta, barva) — slovenske kategorije za začetek.
DEFAULT_CATEGORIES: list[tuple[str, CategoryKind, str]] = [
    # Odhodki
    ("Hrana in pijača", CategoryKind.EXPENSE, "#22c55e"),
    ("Restavracije in kava", CategoryKind.EXPENSE, "#f97316"),
    ("Promet in gorivo", CategoryKind.EXPENSE, "#eab308"),
    ("Javni prevoz", CategoryKind.EXPENSE, "#06b6d4"),
    ("Naročnine", CategoryKind.EXPENSE, "#a855f7"),
    ("Zdravje in lekarna", CategoryKind.EXPENSE, "#ef4444"),
    ("Trgovine in nakupi", CategoryKind.EXPENSE, "#ec4899"),
    ("Oblačila in obutev", CategoryKind.EXPENSE, "#f472b6"),
    ("Zabava in prosti čas", CategoryKind.EXPENSE, "#8b5cf6"),
    ("Položnice in komunala", CategoryKind.EXPENSE, "#0ea5e9"),
    ("Zavarovanja", CategoryKind.EXPENSE, "#14b8a6"),
    ("Bančni stroški", CategoryKind.EXPENSE, "#78716c"),
    ("Gotovina (dvig)", CategoryKind.EXPENSE, "#64748b"),
    ("Drugo (odhodki)", CategoryKind.EXPENSE, "#9ca3af"),
    # Prihodki
    ("Plača in honorarji", CategoryKind.INCOME, "#16a34a"),
    ("Štipendija", CategoryKind.INCOME, "#15803d"),
    ("Nakazila in vračila", CategoryKind.INCOME, "#65a30d"),
    ("Drugo (prihodki)", CategoryKind.INCOME, "#84cc16"),
    # Prenosi
    ("Prenosi med računi", CategoryKind.TRANSFER, "#94a3b8"),
]

# Imena, na katera se sklicujemo drugje (privzeta pravila, fallback).
UNCATEGORIZED_NAME = "Nerazvrščeno"


def seed_categories(session: Session) -> None:
    """Vstavi privzete kategorije, če baza še nima nobene (idempotentno)."""
    existing = session.exec(select(Category).limit(1)).first()
    if existing is not None:
        return

    cats = [
        Category(name=name, kind=kind, color=color, is_system=True)
        for name, kind, color in DEFAULT_CATEGORIES
    ]
    # Posebna fallback kategorija za nerazvrščene.
    cats.append(
        Category(name=UNCATEGORIZED_NAME, kind=CategoryKind.EXPENSE, color="#d1d5db", is_system=True)
    )
    session.add_all(cats)
    session.commit()
