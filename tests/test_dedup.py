"""Testi za dedup in cevovod uvoza (vključno s pristnimi dvojniki in ponovnim uvozom)."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.dedup import assign_hashes
from bilanca.ingest.importer import import_source
from bilanca.ingest.profiles import nkbm
from bilanca.models import Transaction


def _memory_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_genuine_duplicates_get_distinct_hashes(nkbm_csv_bytes):
    txns = nkbm.parse(nkbm_csv_bytes)
    hashed = assign_hashes(txns)
    hashes = [h for _, h, _ in hashed]
    # dva enaka dviga gotovine → različna hash-a (occurrence 0 in 1)
    assert len(hashes) == len(set(hashes))
    occurrences = [o for *_, o in hashed]
    assert 1 in occurrences  # vsaj en occurrence == 1 (pristen dvojnik)


def test_import_inserts_and_skips_on_reimport(nkbm_csv_bytes):
    with _memory_session() as session:
        batch1 = import_source(session, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        assert batch1.row_count == 5
        assert batch1.inserted_count == 5
        assert batch1.duplicate_count == 0

        total = len(session.exec(select(Transaction)).all())
        assert total == 5

        # ponovni uvoz iste datoteke → vse preskočeno
        batch2 = import_source(session, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        assert batch2.inserted_count == 0
        assert batch2.duplicate_count == 5

        total_after = len(session.exec(select(Transaction)).all())
        assert total_after == 5  # ni podvojeno
