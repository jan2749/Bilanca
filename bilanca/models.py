"""Podatkovni model (SQLModel tabele).

Denarni zneski so povsod shranjeni kot celo število centov (predznak: odhodki negativni,
prihodki pozitivni), da se izognemo napakam s plavajočo vejico.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(UTC)


class User(SQLModel, table=True):
    """Uporabnik aplikacije (prijava/registracija)."""

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=_utcnow)


class UserSession(SQLModel, table=True):
    """Sejni žeton, shranjen v bazi; ujema se s piškotkom v brskalniku."""

    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(index=True, unique=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime


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
    """Bančni račun (pripada uporabniku)."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
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
    # NULL = sistemska (skupna vsem); sicer lastna kategorija uporabnika.
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)


class Rule(SQLModel, table=True):
    """Pravilo, ki transakcijo razvrsti v kategorijo. Višji priority = preverjeno prej."""

    id: int | None = Field(default=None, primary_key=True)
    match_type: MatchType = MatchType.CONTAINS
    pattern: str
    category_id: int = Field(foreign_key="category.id")
    priority: int = 100
    source: RuleSource = RuleSource.SYSTEM
    # NULL = sistemsko (skupno vsem); sicer naučeno pravilo uporabnika.
    user_id: int | None = Field(default=None, foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=_utcnow)


class ImportBatch(SQLModel, table=True):
    """En uvoz datoteke (za sledljivost in statistiko)."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    source_type: str = "nkbm_csv"
    filename: str = ""
    imported_at: datetime = Field(default_factory=_utcnow)
    row_count: int = 0  # vrstic v datoteki
    inserted_count: int = 0  # novih vnesenih
    duplicate_count: int = 0  # preskočenih dvojnikov


class BankConnection(SQLModel, table=True):
    """Povezava na banko prek PSD2 agregatorja (GoCardless) — ena vrstica na povezan račun.

    Tok: ustvarimo "requisition" (privolitev) → uporabnik potrdi pri banki → banka preusmeri
    nazaj → dobimo account_id. Privolitev velja 90 dni (expires_at), nato je status "expired".
    """

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str = "gocardless"
    institution_id: str = ""  # npr. "SANDBOXFINANCE_SFIN0000" ali ID prave banke
    institution_name: str = ""
    requisition_id: str = Field(default="", index=True)
    # Naključen ključ, ki ga pošljemo GoCardless in dobimo nazaj v callbacku (povratno preverjanje).
    reference: str = Field(default="", index=True)
    # account_id je znan šele po potrjeni privolitvi.
    account_id: str | None = None
    account_iban: str = ""
    # created → privolitev ustvarjena; linked → račun povezan; expired → potekla; error → napaka.
    status: str = "created"
    created_at: datetime = Field(default_factory=_utcnow)
    expires_at: datetime | None = None


class Transaction(SQLModel, table=True):
    """Posamezna bančna transakcija (normalizirana)."""

    # dedup_hash je unikaten znotraj računa (ne globalno): dva uporabnika imata lahko
    # vsebinsko identično transakcijo, ki se ne sme zaleteti.
    __table_args__ = (UniqueConstraint("account_id", "dedup_hash", name="uq_txn_account_dedup"),)

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
    dedup_hash: str = Field(index=True)
    # Zaporedna številka znotraj skupine identičnih transakcij istega dne (npr. dva enaka dviga).
    occurrence: int = 0

    created_at: datetime = Field(default_factory=_utcnow)
