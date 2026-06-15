"""Testi za pravilni stroj in učenje pravil."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.categorize.defaults import seed_rules
from bilanca.categorize.rules import apply_rules, set_category
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.models import Category, Transaction
from bilanca.seed import seed_categories


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_categories(s)
    seed_rules(s)
    return s


def _cat_name(session: Session, txn: Transaction) -> str | None:
    if txn.category_id is None:
        return None
    return session.get(Category, txn.category_id).name


def test_default_rules_categorize_on_import(nkbm_csv_bytes):
    with _session() as s:
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        by_purpose = {t.purpose: _cat_name(s, t) for t in s.exec(select(Transaction)).all()}
        assert by_purpose["APPLE.COM/BILL"] == "Naročnine"
        assert by_purpose["SPAR ŠENTJUR"] == "Hrana in pijača"
        assert by_purpose["DVIG GOTOVINE BA02126S"] == "Gotovina (dvig)"
        # štipendija prepoznana iz naziva nasprotne stranke
        assert by_purpose["PRILIV NA RAČUN"] == "Štipendija"


def test_manual_set_locks_and_survives_recategorize(nkbm_csv_bytes):
    with _session() as s:
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        spar = s.exec(select(Transaction).where(Transaction.purpose == "SPAR ŠENTJUR")).first()
        zabava = s.exec(select(Category).where(Category.name == "Zabava in prosti čas")).first()

        set_category(s, spar.id, zabava.id, create_rule=False)
        s.refresh(spar)
        assert spar.category_locked is True
        assert spar.category_id == zabava.id

        # ponovno razvrščanje ne sme prepisati ročno zaklenjene
        apply_rules(s, only_uncategorized=False)
        s.refresh(spar)
        assert spar.category_id == zabava.id


def test_learn_rule_applies_to_others(nkbm_csv_bytes):
    with _session() as s:
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), "promet.csv")
        # DVIG je privzeto Gotovina; prekvalificiraj enega in ustvari pravilo "za vse"
        dvigi = s.exec(
            select(Transaction).where(Transaction.purpose == "DVIG GOTOVINE BA02126S")
        ).all()
        assert len(dvigi) == 2
        drugo = s.exec(select(Category).where(Category.name == "Drugo (odhodki)")).first()

        set_category(s, dvigi[0].id, drugo.id, create_rule=True)
        # drugi dvig (nezaklenjen) naj se prerazvrsti prek naučenega pravila
        for d in s.exec(
            select(Transaction).where(Transaction.purpose == "DVIG GOTOVINE BA02126S")
        ).all():
            assert d.category_id == drugo.id
