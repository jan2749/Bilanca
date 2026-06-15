"""Testi za agregacije nadzorne plošče."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine

from bilanca.categorize.defaults import seed_rules
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.insights.trends import monthly_summary, spending_by_category
from bilanca.seed import seed_categories
from tests.conftest import make_user


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_categories(s)
    seed_rules(s)
    return s


def test_spending_by_category(nkbm_csv_bytes):
    with _session() as s:
        user = make_user(s)
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), user, "promet.csv")
        slices = spending_by_category(s, user.id)
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
        user = make_user(s)
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), user, "promet.csv")
        rows = monthly_summary(s, user.id)
        months = [r.month for r in rows]
        assert months == sorted(months)
        # priliv 78,35 € v juniju 2026
        jun = next(r for r in rows if r.month == "2026-06")
        assert jun.income_eur == 78.35


def test_date_range_filters_out_of_window(nkbm_csv_bytes):
    with _session() as s:
        user = make_user(s)
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), user, "promet.csv")
        # samo junij 2026 → aprilska dviga gotovine sta izključena
        slices = spending_by_category(
            s, user.id, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30)
        )
        names = {sl.name for sl in slices}
        assert "Gotovina (dvig)" not in names
        # brez okna pa je gotovina prisotna (dva aprilska dviga)
        all_names = {sl.name for sl in spending_by_category(s, user.id)}
        assert "Gotovina (dvig)" in all_names
