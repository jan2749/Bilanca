"""Testi za statistiko: top prejemniki (odhodki) in top viri prihodkov (prilivi)."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.insights.stats import top_merchants, top_payers
from tests.conftest import make_user


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_top_merchants_are_expenses_only(nkbm_csv_bytes):
    with _session() as s:
        user = make_user(s)
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), user, "promet.csv")
        rows = top_merchants(s, user.id)
        assert rows
        # padajoče urejeno po vrednosti
        values = [r.total_eur for r in rows]
        assert values == sorted(values, reverse=True)
        # priliv (MDDSZ) ne sme biti med prejemniki odhodkov
        assert all("MDDSZ" not in r.name for r in rows)
        # dva dviga po 30 € (counterparty "142J0") se združita v en zapis z 2 transakcijama
        dvig = next((r for r in rows if r.name == "142J0"), None)
        assert dvig is not None
        assert dvig.total_eur == 60.0
        assert dvig.tx_count == 2


def test_top_payers_are_income_only(nkbm_csv_bytes):
    with _session() as s:
        user = make_user(s)
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), user, "promet.csv")
        rows = top_payers(s, user.id)
        assert rows
        # edini priliv v vzorcu: 78,35 € od MDDSZ
        assert rows[0].name == "MDDSZ-DRŽAVNE ŠTIPENDIJE"
        assert rows[0].total_eur == 78.35
        # noben odhodek (npr. SPAR/APPLE) ne sme biti med viri prihodkov
        assert all("SPAR" not in r.name and "APPLE" not in r.name for r in rows)
