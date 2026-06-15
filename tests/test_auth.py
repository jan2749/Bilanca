"""Testi za avtentikacijo in ločenost podatkov med uporabniki."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.auth import (
    _user_for_token,
    create_session,
    destroy_session,
    hash_password,
    verify_password,
)
from bilanca.categorize.defaults import seed_rules
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.insights.trends import spending_by_category
from bilanca.models import Account, Transaction, UserSession
from bilanca.seed import seed_categories
from tests.conftest import make_user


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_categories(s)
    seed_rules(s)
    return s


def test_hash_and_verify_password():
    stored = hash_password("skrivnost123")
    assert stored != "skrivnost123"
    assert verify_password("skrivnost123", stored) is True
    assert verify_password("napacno", stored) is False
    assert verify_password("karkoli", "pokvarjen-zapis") is False


def test_session_lifecycle():
    with _session() as s:
        user = make_user(s)
        token = create_session(s, user)
        assert _user_for_token(s, token).id == user.id
        assert _user_for_token(s, "neobstojec") is None

        destroy_session(s, token)
        assert _user_for_token(s, token) is None


def test_expired_session_rejected():
    with _session() as s:
        user = make_user(s)
        token = create_session(s, user)
        row = s.exec(select(UserSession).where(UserSession.token == token)).first()
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        s.add(row)
        s.commit()
        assert _user_for_token(s, token) is None


def test_data_isolation_and_per_user_dedup(nkbm_csv_bytes):
    with _session() as s:
        alice = make_user(s, email="alice@example.com")
        bob = make_user(s, email="bob@example.com")

        import_source(s, NkbmCsvSource(nkbm_csv_bytes), alice, "promet.csv")
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), bob, "promet.csv")

        # Skupno 10 transakcij (5 na uporabnika): dedup deluje po uporabniku, ne globalno.
        assert len(s.exec(select(Transaction)).all()) == 10

        def user_txns(user):
            return s.exec(
                select(Transaction).where(
                    Transaction.account_id.in_(
                        select(Account.id).where(Account.user_id == user.id)
                    )
                )
            ).all()

        assert len(user_txns(alice)) == 5
        assert len(user_txns(bob)) == 5

        # Ponovni uvoz pri Alice ne sme dodati ničesar (dedup znotraj njenih računov).
        import_source(s, NkbmCsvSource(nkbm_csv_bytes), alice, "promet.csv")
        assert len(user_txns(alice)) == 5

        # Agregacije so prav tako omejene na uporabnika.
        alice_total = sum(sl.amount_eur for sl in spending_by_category(s, alice.id))
        bob_total = sum(sl.amount_eur for sl in spending_by_category(s, bob.id))
        assert alice_total == bob_total  # enak vhod
        assert alice_total > 0
