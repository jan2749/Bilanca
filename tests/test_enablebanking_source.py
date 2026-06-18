"""Testi za Enable Banking vir: mapiranje (snake_case + credit_debit_indicator) in dedup.

Brez pravih omrežnih klicev — klient je nadomeščen z lažnim, ki vrne fiksen JSON.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.ingest.enablebanking_source import (
    EnableBankingSource,
    _to_cents,
    account_iban,
    normalize_txn,
)
from bilanca.ingest.importer import import_source
from bilanca.models import Transaction
from tests.conftest import make_user

ACC_IBAN = "SI56040010047301554"

# Oblika, kot jo vrne Enable Banking GET /accounts/{uid}/transactions.
SAMPLE = {
    "transactions": [
        {
            "entry_reference": "e1",
            "booking_date": "2026-06-14",
            "value_date": "2026-06-14",
            "transaction_amount": {"amount": "3.99", "currency": "EUR"},
            "credit_debit_indicator": "DBIT",
            "creditor": {"name": "APPLE.COM/BILL"},
            "creditor_account": {"iban": "DE89370400440532013000"},
            "remittance_information": ["APPLE.COM/BILL"],
        },
        {
            "entry_reference": "e2",
            "booking_date": "2026-06-10",
            "transaction_amount": {"amount": "78.35", "currency": "EUR"},
            "credit_debit_indicator": "CRDT",
            "debtor": {"name": "MDDSZ"},
            "debtor_account": {"iban": "SI56011006000039211"},
            "remittance_information": ["PRILIV", "NA RAČUN"],
        },
        {
            "entry_reference": "e3",
            "booking_date": "2026-06-15",
            "transaction_amount": {"amount": "6.89", "currency": "EUR"},
            "credit_debit_indicator": "DBIT",
            "creditor": {"name": "SPAR"},
        },
    ]
}


class FakeClient:
    """Nadomestek EnableBankingClient — vrne fiksen JSON brez omrežja."""

    def get_account_details(self, account_uid):
        return {"account_id": {"iban": ACC_IBAN}}

    def get_account_transactions(self, account_uid, date_from=None):
        return SAMPLE


def _memory_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_to_cents():
    assert _to_cents("3.99") == 399
    assert _to_cents("78.35") == 7835
    assert _to_cents("0") == 0
    assert _to_cents("") == 0


def test_account_iban_extraction():
    assert account_iban({"account_id": {"iban": ACC_IBAN}}) == ACC_IBAN
    assert account_iban({"iban": ACC_IBAN}) == ACC_IBAN
    assert account_iban({}) == ""


def test_normalize_debit_is_negative_and_picks_creditor():
    t = normalize_txn(SAMPLE["transactions"][0], iban=ACC_IBAN)
    assert t.amount_cents == -399  # DBIT → negativno
    assert t.counterparty_name == "APPLE.COM/BILL"
    assert t.counterparty_iban == "DE89370400440532013000"
    assert t.purpose == "APPLE.COM/BILL"
    assert t.booking_date == date(2026, 6, 14)
    assert t.account_iban == ACC_IBAN


def test_normalize_credit_is_positive_and_picks_debtor():
    t = normalize_txn(SAMPLE["transactions"][1])
    assert t.amount_cents == 7835  # CRDT → pozitivno
    assert t.counterparty_name == "MDDSZ"
    assert t.counterparty_iban == "SI56011006000039211"
    assert t.purpose == "PRILIV NA RAČUN"
    # value_date manjka → pade nazaj na booking_date
    assert t.value_date == date(2026, 6, 10)


def test_source_fetch_returns_all_rows():
    source = EnableBankingSource(FakeClient(), account_uid="acc-1")
    txns = list(source.fetch())
    assert len(txns) == 3
    # IBAN pridobljen iz get_account_details, ker ni bil podan
    assert all(t.account_iban == ACC_IBAN for t in txns)


def test_import_source_dedups_on_resync():
    with _memory_session() as session:
        user = make_user(session)
        b1 = import_source(session, EnableBankingSource(FakeClient(), "acc-1"), user, "EB")
        assert b1.inserted_count == 3
        assert b1.duplicate_count == 0
        assert len(session.exec(select(Transaction)).all()) == 3

        # ponovna sinhronizacija istih podatkov → vse preskočeno
        b2 = import_source(session, EnableBankingSource(FakeClient(), "acc-1"), user, "EB")
        assert b2.inserted_count == 0
        assert b2.duplicate_count == 3
        assert len(session.exec(select(Transaction)).all()) == 3
