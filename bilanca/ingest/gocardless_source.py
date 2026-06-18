"""Vir transakcij iz GoCardless Bank Account Data (PSD2).

Implementira isti TransactionSource protokol kot CSV uvoz: pretvori GoCardless JSON v
NormalizedTxn, vse navzdol (dedup, import_source, kategorizacija) ostane enako.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from bilanca.ingest.base import NormalizedTxn
from bilanca.ingest.gocardless import GoCardlessClient

SOURCE_TYPE = "gocardless"


def _amount_to_cents(value: str | float) -> int:
    """Pretvori GoCardless znesek (decimalni niz s piko, npr. '-12.34') v cente s predznakom."""
    s = str(value).strip()
    if not s:
        return 0
    cents = (Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def _parse_date(value: str | None, fallback: date | None = None) -> date | None:
    if not value:
        return fallback
    try:
        # GoCardless vrača ISO (YYYY-MM-DD), lahko tudi z časom.
        return date.fromisoformat(value[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return fallback


def _remittance(txn: dict[str, Any]) -> str:
    """Sestavi opis (namen) iz nestrukturiranih polj, ki jih banke različno polnijo."""
    unstructured = txn.get("remittanceInformationUnstructured")
    if unstructured:
        return str(unstructured).strip()
    arr = txn.get("remittanceInformationUnstructuredArray")
    if isinstance(arr, list) and arr:
        return " ".join(str(x).strip() for x in arr if x).strip()
    # Zadnja možnost: dodatni opis ali koda namena.
    return str(txn.get("additionalInformation") or "").strip()


def normalize_txn(txn: dict[str, Any], account_iban: str = "") -> NormalizedTxn:
    """Pretvori en GoCardless transakcijski zapis v NormalizedTxn."""
    amount_info = txn.get("transactionAmount", {}) or {}
    amount_cents = _amount_to_cents(amount_info.get("amount", "0"))
    currency = (amount_info.get("currency") or "EUR").strip() or "EUR"

    booking = _parse_date(txn.get("bookingDate") or txn.get("bookingDateTime"))
    value = _parse_date(txn.get("valueDate") or txn.get("valueDateTime"), fallback=booking)
    if booking is None:
        booking = value  # vsaj eno polje mora obstajati

    # Pri odlivu je nasprotna stranka prejemnik (creditor), pri prilivu plačnik (debtor).
    if amount_cents < 0:
        cp_name = txn.get("creditorName") or ""
        cp_iban = (txn.get("creditorAccount") or {}).get("iban", "")
    else:
        cp_name = txn.get("debtorName") or ""
        cp_iban = (txn.get("debtorAccount") or {}).get("iban", "")

    return NormalizedTxn(
        booking_date=booking,
        value_date=value or booking,
        amount_cents=amount_cents,
        account_iban=account_iban,
        currency=currency,
        purpose=_remittance(txn),
        counterparty_name=str(cp_name).strip(),
        counterparty_iban=str(cp_iban).strip(),
        reference=str(txn.get("endToEndId") or "").strip(),
        purpose_code=str(txn.get("bankTransactionCode") or txn.get("purposeCode") or "").strip(),
        extra={"gocardless_id": txn.get("transactionId") or txn.get("internalTransactionId")},
    )


class GoCardlessSource:
    """TransactionSource, ki prebere transakcije enega povezanega računa prek GoCardless."""

    source_type = SOURCE_TYPE

    def __init__(
        self,
        client: GoCardlessClient,
        account_id: str,
        account_iban: str = "",
        date_from: str | None = None,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._account_iban = account_iban
        self._date_from = date_from

    def fetch(self) -> Iterable[NormalizedTxn]:
        iban = self._account_iban
        if not iban:
            details = self._client.get_account_details(self._account_id)
            iban = details.get("iban", "")

        data = self._client.get_account_transactions(self._account_id, self._date_from)
        block = (data or {}).get("transactions", {}) or {}
        rows = list(block.get("booked", [])) + list(block.get("pending", []))

        out: list[NormalizedTxn] = []
        for txn in rows:
            normalized = normalize_txn(txn, account_iban=iban)
            if normalized.booking_date is None:
                continue  # brez datuma ni uporabne transakcije
            out.append(normalized)
        return out
