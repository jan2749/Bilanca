"""Profil za razčlenjevanje izvoza prometa iz NKBM / OTP Bank@Net (CSV).

Format (potrjen na resničnem izvozu):
- kodiranje: Windows-1250 (cp1250)
- ločilo: podpičje (;)
- decimalna vejica, pika kot ločilo tisočic
- datum: DD.MM.YYYY
- en znesek je v stolpcu DOBRO (priliv) ALI BREME (odliv), nikoli oba

Stolpci:
    ŠT. IZPISKA; POGODBA; RAČUN; DATUM KNJIŽENJA; DATUM VALUTE; DOBRO; BREME; VALUTA;
    NAMEN; SKLIC V DOBRO; SKLIC V BREME; UDELEŽENEC - RAČUN; UDELEŽENEC - NAZIV;
    UDELEŽENEC - BIC; KODA NAMENA; PRILIV V IZVORNI VALUTI; ODLIV V IZVORNI VALUTI;
    IZVORNA VALUTA
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

from bilanca.ingest.base import NormalizedTxn

SOURCE_TYPE = "nkbm_csv"
DELIMITER = ";"
# Kodiranja, ki jih poskusimo po vrsti (NKBM izvaža v cp1250).
ENCODINGS = ("utf-8-sig", "utf-8", "cp1250")

# Normalizirano ime stolpca -> ključ polja. Ujemamo po očiščenem (strip+upper) imenu.
COLUMN_MAP = {
    "DATUM KNJIŽENJA": "booking_date",
    "DATUM VALUTE": "value_date",
    "DOBRO": "credit",
    "BREME": "debit",
    "VALUTA": "currency",
    "NAMEN": "purpose",
    "SKLIC V DOBRO": "ref_credit",
    "SKLIC V BREME": "ref_debit",
    "UDELEŽENEC - RAČUN": "counterparty_iban",
    "UDELEŽENEC - NAZIV": "counterparty_name",
    "KODA NAMENA": "purpose_code",
    "RAČUN": "account_iban",
}


class NkbmParseError(ValueError):
    """Napaka pri razčlenjevanju NKBM izvoza."""


def decode_bytes(raw: bytes) -> str:
    """Dekodira surove bajte z znanimi kodiranji (NKBM = cp1250)."""
    for enc in ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # Zadnja možnost: cp1250 z nadomeščanjem, da se uvoz ne sesuje.
    return raw.decode("cp1250", errors="replace")


def parse_amount(value: str) -> int:
    """Pretvori slovenski zapis zneska (npr. '1.234,56' ali '3,99') v cente."""
    s = value.strip()
    if not s:
        return 0
    if "," in s:
        # vejica = decimalka, pika = ločilo tisočic
        s = s.replace(".", "").replace(",", ".")
    # sicer je morda že pika kot decimalka ali celo število
    # zaokroženo na cente brez float napak
    from decimal import ROUND_HALF_UP, Decimal

    cents = (Decimal(s) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def parse_date(value: str) -> date:
    """Pretvori 'DD.MM.YYYY' v date."""
    return datetime.strptime(value.strip(), "%d.%m.%Y").date()


def _normalize_header(name: str) -> str:
    return name.strip().upper()


def parse(raw: bytes) -> list[NormalizedTxn]:
    """Razčleni surovo vsebino NKBM CSV v normalizirane transakcije."""
    text = decode_bytes(raw)
    reader = csv.reader(io.StringIO(text), delimiter=DELIMITER)
    rows = list(reader)
    if not rows:
        return []

    header = [_normalize_header(c) for c in rows[0]]
    # indeks polja -> stolpec
    idx: dict[str, int] = {}
    for i, col in enumerate(header):
        field_name = COLUMN_MAP.get(col)
        if field_name:
            idx[field_name] = i

    required = {"booking_date", "value_date", "purpose"}
    missing = required - idx.keys()
    if missing:
        raise NkbmParseError(
            f"NKBM CSV: manjkajo pričakovani stolpci {sorted(missing)}; "
            f"najdena glava: {header}"
        )

    def cell(row: list[str], key: str) -> str:
        i = idx.get(key)
        if i is None or i >= len(row):
            return ""
        return row[i].strip()

    out: list[NormalizedTxn] = []
    for row in rows[1:]:
        if not any(c.strip() for c in row):
            continue  # prazna vrstica
        booking_raw = cell(row, "booking_date")
        if not booking_raw:
            continue  # vrstica brez datuma ni transakcija

        credit = parse_amount(cell(row, "credit"))
        debit = parse_amount(cell(row, "debit"))
        # predznak: priliv +, odliv -
        amount = credit if credit else -debit

        ref = cell(row, "ref_credit") or cell(row, "ref_debit")

        out.append(
            NormalizedTxn(
                booking_date=parse_date(booking_raw),
                value_date=parse_date(cell(row, "value_date") or booking_raw),
                amount_cents=amount,
                account_iban=cell(row, "account_iban"),
                currency=cell(row, "currency") or "EUR",
                purpose=cell(row, "purpose"),
                counterparty_name=cell(row, "counterparty_name"),
                counterparty_iban=cell(row, "counterparty_iban"),
                reference=ref,
                purpose_code=cell(row, "purpose_code"),
            )
        )
    return out
