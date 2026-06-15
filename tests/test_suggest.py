"""Testi za predloge kategorij za nerazvrščene odhodke."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.categorize.defaults import seed_rules
from bilanca.categorize.rules import set_category
from bilanca.categorize.suggest import uncategorized_groups
from bilanca.models import Account, Category, Transaction
from bilanca.seed import seed_categories
from tests.conftest import make_user


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_categories(s)
    seed_rules(s)
    return s


def _add(s, acc, purpose, name, eur, d, h):
    s.add(
        Transaction(
            account_id=acc.id,
            booking_date=d,
            value_date=d,
            amount_cents=int(round(-eur * 100)),
            purpose=purpose,
            counterparty_name=name,
            dedup_hash=h,
        )
    )


def test_groups_sorted_and_learning_clears_group():
    with _session() as s:
        user = make_user(s)
        acc = Account(user_id=user.id, name="x", iban="SI00")
        s.add(acc)
        s.commit()
        s.refresh(acc)

        # dva odhodka istega neznanega prejemnika (skupaj 10 €) + en drug (12 €)
        _add(s, acc, "NEZNAN BIFE", "NEZNAN BIFE d.o.o.", 5.0, date(2026, 6, 1), "a0")
        _add(s, acc, "NEZNAN BIFE", "NEZNAN BIFE d.o.o.", 5.0, date(2026, 6, 2), "a1")
        _add(s, acc, "DRUGA TRGOVINA", "DRUGA TRGOVINA", 12.0, date(2026, 6, 5), "b0")
        s.commit()

        groups = uncategorized_groups(s, user)
        assert len(groups) == 2
        # padajoče po skupni porabi
        assert groups[0].total_eur == 12.0
        bife = next(g for g in groups if "BIFE" in g.label.upper())
        assert bife.count == 2

        # razvrsti predstavnika z učenjem pravila → razvrsti se cela skupina
        cat = s.exec(select(Category).where(Category.name == "Restavracije in kava")).first()
        set_category(s, user, bife.txn_id, cat.id, create_rule=True)

        groups_after = uncategorized_groups(s, user)
        assert all("BIFE" not in g.label.upper() for g in groups_after)
        # vse BIFE transakcije so zdaj v izbrani kategoriji
        bife_txns = s.exec(
            select(Transaction).where(Transaction.purpose == "NEZNAN BIFE")
        ).all()
        assert all(t.category_id == cat.id for t in bife_txns)
