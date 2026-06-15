"""Podatkovni model (SQLModel tabele).

Denarni zneski so povsod shranjeni kot celo število centov (predznak: odhodki negativni,
prihodki pozitivni), da se izognemo napakam s plavajočo vejico.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CategoryKind(StrEnum):
    """Vrsta kategorije."""

    EXPENSE = "expense"
    INCOME = "income"
    TRANSFER = "transfer"


class MatchType(StrEnum):
    """Način ujemanja pravila za kategorizacijo."""

    CONTAINS = "contains"  # podniz v opisu/nazivu (neobčutljivo na velikost črk)
    REGEX = "regex"  # regularni izraz
    IBAN = "iban"  # ujemanje IBAN nasprotne stranke
    EXACT = "exact"  # natančen niz


class RuleSource(StrEnum):
    """Izvor pravila."""

    SYSTEM = "system"  # privzeto vgrajeno
    USER = "user"  # naučeno iz uporabnikovega popravka


class Account(SQLModel, table=True):
    """Bančni račun."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    bank: str = "NKBM / OTP"
    iban: str = Field(index=True)
    currency: str = "EUR"
    # Začetni saldo (centi) za projekcijo konca meseca; NKBM izvoz salda ne vsebuje.
    opening_balance_cents: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class Category(SQLModel, table=True):
    """Kategorija porabe/prihodka (z možnostjo hierarhije prek parent_id)."""

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    parent_id: int | None = Field(default=None, foreign_key="category.id")
    kind: CategoryKind = CategoryKind.EXPENSE
    color: str = "#9ca3af"  # za grafe
    is_system: bool = True


class Rule(SQLModel, table=True):
    """Pravilo, ki transakcijo razvrsti v kategorijo. Višji priority = preverjeno prej."""

    id: int | None = Field(default=None, primary_key=True)
    match_type: MatchType = MatchType.CONTAINS
    pattern: str
    category_id: int = Field(foreign_key="category.id")
    priority: int = 100
    source: RuleSource = RuleSource.SYSTEM
    created_at: datetime = Field(default_factory=_utcnow)


class ImportBatch(SQLModel, table=True):
    """En uvoz datoteke (za sledljivost in statistiko)."""

    id: int | None = Field(default=None, primary_key=True)
    source_type: str = "nkbm_csv"
    filename: str = ""
    imported_at: datetime = Field(default_factory=_utcnow)
    row_count: int = 0  # vrstic v datoteki
    inserted_count: int = 0  # novih vnesenih
    duplicate_count: int = 0  # preskočenih dvojnikov


class Transaction(SQLModel, table=True):
    """Posamezna bančna transakcija (normalizirana)."""

    id: int | None = Field(default=None, primary_key=True)
    account_id: int = Field(foreign_key="account.id", index=True)

    booking_date: date = Field(index=True)  # DATUM KNJIŽENJA
    value_date: date  # DATUM VALUTE

    # Predznak: odhodek negativen, prihodek pozitiven.
    amount_cents: int
    currency: str = "EUR"

    purpose: str = ""  # NAMEN (opis)
    counterparty_name: str = ""  # UDELEŽENEC - NAZIV
    counterparty_iban: str = ""  # UDELEŽENEC - RAČUN
    reference: str = ""  # SKLIC V DOBRO/BREME
    purpose_code: str = ""  # KODA NAMENA

    category_id: int | None = Field(default=None, foreign_key="category.id", index=True)
    # Če je uporabnik ročno določil kategorijo, je ne prepisujemo samodejno.
    category_locked: bool = False

    import_batch_id: int | None = Field(default=None, foreign_key="importbatch.id")

    # Key za odkrivanje dvojnikov ob ponovnem uvozu prekrivajočih obdobij.
    dedup_hash: str = Field(index=True, unique=True)
    # Zaporedna številka znotraj skupine identičnih transakcij istega dne (npr. dva enaka dviga).
    occurrence: int = 0

    created_at: datetime = Field(default_factory=_utcnow)
