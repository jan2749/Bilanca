"""Testi za GoCardless vir: mapiranje JSON → NormalizedTxn in dedup prek import_source.

Brez pravih omrežnih klicev — klient je nadomeščen z lažnim, ki vrne fiksen JSON.
"""

from __future__ import annotations

from datetime import date

from sqlmodel import Session, SQLModel, create_engine, select

from bilanca.ingest.gocardless_source import GoCardlessSource, _amount_to_cents, normalize_txn
from bilanca.ingest.importer import import_source
from bilanca.models import Transaction
from tests.conftest import make_user

ACC_IBAN = "SI56040010047301554"

# Vzorčni odgovor v obliki, kot ga vrne GoCardless /accounts/{id}/transactions/.
SAMPLE = {
    "transactions": {
        "booked": [
            {
                "transactionId": "g1",
                "bookingDate": "2026-06-14",
                "valueDate": "2026-06-14",
                "transactionAmount": {"amount": "-3.99", "currency": "EUR"},
                "creditorName": "APPLE.COM/BILL",
                "creditorAccount": {"iban": "DE89370400440532013000"},
                "remittanceInformationUnstructured": "APPLE.COM/BILL",
            },
            {
                "transactionId": "g2",
                "bookingDate": "2026-06-10",
                "transactionAmount": {"amount": "78.35", "currency": "EUR"},
                "debtorName": "MDDSZ",
                "debtorAccount": {"iban": "SI56011006000039211"},
                "remittanceInformationUnstructuredArray": ["PRILIV", "NA RAČUN"],
            },
        ],
        "pending": [
            {
                "transactionId": "g3",
                "bookingDate": "2026-06-15",
                "transactionAmount": {"amount": "-6.89", "currency": "EUR"},
                "creditorName": "SPAR",
            },
        ],
    }
}


class FakeClient:
    """Nadomestek GoCardlessClient — vrne fiksen JSON brez omrežja."""

    def get_account_details(self, account_id):
        return {"iban": ACC_IBAN}

    def get_account_transactions(self, account_id, date_from=None):
        return SAMPLE


def _memory_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_amount_to_cents():
    assert _amount_to_cents("-3.99") == -399
    assert _amount_to_cents("78.35") == 7835
    assert _amount_to_cents("0") == 0
    assert _amount_to_cents("") == 0


def test_normalize_expense_picks_creditor():
    t = normalize_txn(SAMPLE["transactions"]["booked"][0], account_iban=ACC_IBAN)
    assert t.amount_cents == -399
    assert t.counterparty_name == "APPLE.COM/BILL"
    assert t.counterparty_iban == "DE89370400440532013000"
    assert t.purpose == "APPLE.COM/BILL"
    assert t.booking_date == date(2026, 6, 14)
    assert t.account_iban == ACC_IBAN


def test_normalize_income_picks_debtor():
    t = normalize_txn(SAMPLE["transactions"]["booked"][1])
    assert t.amount_cents == 7835  # priliv pozitiven
    assert t.counterparty_name == "MDDSZ"
    assert t.counterparty_iban == "SI56011006000039211"
    assert t.purpose == "PRILIV NA RAČUN"
    # value_date manjka → pade nazaj na booking_date
    assert t.value_date == date(2026, 6, 10)


def test_source_fetch_returns_all_rows():
    source = GoCardlessSource(FakeClient(), account_id="acc-1")
    txns = list(source.fetch())
    assert len(txns) == 3  # 2 booked + 1 pending
    # IBAN pridobljen iz get_account_details, ker ni bil podan
    assert all(t.account_iban == ACC_IBAN for t in txns)


def test_import_source_dedups_on_resync():
    with _memory_session() as session:
        user = make_user(session)
        b1 = import_source(session, GoCardlessSource(FakeClient(), "acc-1"), user, "GoCardless")
        assert b1.inserted_count == 3
        assert b1.duplicate_count == 0
        assert len(session.exec(select(Transaction)).all()) == 3

        # ponovna sinhronizacija istih podatkov → vse preskočeno
        b2 = import_source(session, GoCardlessSource(FakeClient(), "acc-1"), user, "GoCardless")
        assert b2.inserted_count == 0
        assert b2.duplicate_count == 3
        assert len(session.exec(select(Transaction)).all()) == 3
