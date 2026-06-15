"""Skupni vmesnik za vire transakcij.

Vsak vir (ročni CSV uvoz, kasneje avtomatska PSD2 povezava) vrne enako oblikovane
normalizirane zapise (NormalizedTxn), ki gredo skozi isti cevovod dedup → kategorizacija.
Tako je dodajanje novega vira zgolj nova implementacija TransactionSource, brez sprememb
v ostalem delu sistema.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


@dataclass
class NormalizedTxn:
    """Normalizirana transakcija, neodvisna od vira.

    Znesek je v centih s predznakom: odhodek negativen, prihodek pozitiven.
    """

    booking_date: date
    value_date: date
    amount_cents: int
    account_iban: str
    currency: str = "EUR"
    purpose: str = ""
    counterparty_name: str = ""
    counterparty_iban: str = ""
    reference: str = ""
    purpose_code: str = ""
    # Poljubni dodatni podatki, ki jih vir lahko pripne (za razhroščevanje).
    extra: dict = field(default_factory=dict)


@runtime_checkable
class TransactionSource(Protocol):
    """Vir transakcij. Implementacije: CSV uvoz, PSD2 API ipd."""

    source_type: str

    def fetch(self) -> Iterable[NormalizedTxn]:
        """Vrne normalizirane transakcije iz vira."""
        ...
