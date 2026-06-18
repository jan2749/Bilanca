"""Vir transakcij iz Enable Banking (PSD2).

Implementira isti TransactionSource protokol kot CSV uvoz: pretvori Enable Banking zapis v
NormalizedTxn, vse navzdol (dedup, import_source, kategorizacija) ostane enako.

Enable Banking shema (snake_case) se rahlo razlikuje od surovega Berlin Group:
znesek (transaction_amount.amount) je pozitiven, predznak pa nosi credit_debit_indicator
(CRDT = priliv, DBIT = odliv).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bilanca.ingest.base import NormalizedTxn
from bilanca.ingest.enablebanking import EnableBankingClient

SOURCE_TYPE = "enablebanking"


def _to_cents(value: str | float) -> int:
    s = str(value or "").strip()
    if not s:
        return 0
    cents = (Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _parse_date(value: str | None, fallback: date | None = None) -> date | None:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return fallback


def _remittance(txn: dict[str, Any]) -> str:
    info = txn.get("remittance_information")
    if isinstance(info, list):
        return " ".join(str(x).strip() for x in info if x).strip()
    if info:
        return str(info).strip()
    return ""


def account_iban(account: dict[str, Any]) -> str:
    """Izlušči IBAN iz Enable Banking računa (iz seje ali iz /details)."""
    acc_id = account.get("account_id") or {}
    return str(acc_id.get("iban") or account.get("iban") or "").strip()


def normalize_txn(txn: dict[str, Any], iban: str = "") -> NormalizedTxn:
    """Pretvori en Enable Banking transakcijski zapis v NormalizedTxn."""
    amount_info = txn.get("transaction_amount", {}) or {}
    cents = abs(_to_cents(amount_info.get("amount", "0")))
    if str(txn.get("credit_debit_indicator", "")).upper() == "DBIT":
        cents = -cents
    currency = (amount_info.get("currency") or "EUR").strip() or "EUR"

    booking = _parse_date(txn.get("booking_date") or txn.get("transaction_date"))
    value = _parse_date(txn.get("value_date"), fallback=booking)
    if booking is None:
        booking = value

    # Pri odlivu je nasprotna stranka prejemnik (creditor), pri prilivu plačnik (debtor).
    if cents < 0:
        cp = txn.get("creditor") or {}
        cp_acc = txn.get("creditor_account") or {}
    else:
        cp = txn.get("debtor") or {}
        cp_acc = txn.get("debtor_account") or {}

    return NormalizedTxn(
        booking_date=booking,
        value_date=value or booking,
        amount_cents=cents,
        account_iban=iban,
        currency=currency,
        purpose=_remittance(txn),
        counterparty_name=str(cp.get("name") or "").strip(),
        counterparty_iban=str(cp_acc.get("iban") or "").strip(),
        reference=str(txn.get("entry_reference") or "").strip(),
        purpose_code=str(txn.get("merchant_category_code") or "").strip(),
        extra={"provider_id": txn.get("transaction_id") or txn.get("entry_reference")},
    )


class EnableBankingSource:
    """TransactionSource, ki prebere transakcije enega povezanega računa prek Enable Banking."""

    source_type = SOURCE_TYPE

    def __init__(
        self,
        client: EnableBankingClient,
        account_uid: str,
        iban: str = "",
        date_from: str | None = None,
    ) -> None:
        self._client = client
        self._account_uid = account_uid
        self._iban = iban
        self._date_from = date_from

    def fetch(self) -> Iterable[NormalizedTxn]:
        iban = self._iban
        if not iban:
            details = self._client.get_account_details(self._account_uid)
            iban = account_iban(details.get("account", details) if isinstance(details, dict) else {})

        data = self._client.get_account_transactions(self._account_uid, self._date_from)
        rows = (data or {}).get("transactions", []) or []

        out: list[NormalizedTxn] = []
        for txn in rows:
            normalized = normalize_txn(txn, iban=iban)
            if normalized.booking_date is None:
                continue
            out.append(normalized)
        return out
