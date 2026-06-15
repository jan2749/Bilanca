"""Testi za agregacije nadzorne plošče."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from bilanca.categorize.defaults import seed_rules
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.insights.trends import monthly_summary, spending_by_category
from bilanca.seed import seed_categories


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_categories(s)
    seed_rules(s)
    return s


def test_spending_by_category(nkbm_csv_bytes):
    with _session() as s:
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        slices = spending_by_category(s)
        # samo odhodki; padajoče urejeno
        assert slices
        amounts = [sl.amount_eur for sl in slices]
        assert amounts == sorted(amounts, reverse=True)
        # dva dviga po 30 € → Gotovina 60 €
        gotovina = next((sl for sl in slices if sl.name == "Gotovina (dvig)"), None)
        assert gotovina is not None
        assert gotovina.amount_eur == 60.0


def test_monthly_summary(nkbm_csv_bytes):
    with _session() as s:
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        rows = monthly_summary(s)
        months = [r.month for r in rows]
        assert months == sorted(months)
        # priliv 78,35 € v juniju 2026
        jun = next(r for r in rows if r.month == "2026-06")
        assert jun.income_eur == 78.35
