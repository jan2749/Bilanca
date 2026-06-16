"""Ustvari demo uporabnika z realističnim 4-letnim prometom (sintetično, brez pravih podatkov).

Namen: varna predstavitev aplikacije drugim, brez razkrivanja osebnih podatkov.
Promet se generira kot NKBM CSV in uvozi skozi pravi cevovod, zato se transakcije
samodejno kategorizirajo in nastane zapis o uvozu (ImportBatch).

Zagon (iz korena projekta, z .venv):
    python -m scripts.seed_demo

Skripta je idempotentna: če demo uporabnik že obstaja, se njegovi podatki najprej
pobrišejo in na novo zgenerirajo. Privzeto deluje nad lokalno bazo (data/bilanca.db);
prepiši z okoljsko spremenljivko BILANCA_DB.
"""

from __future__ import annotations

import calendar
import random
from datetime import date, timedelta

from sqlmodel import Session, select

from bilanca.auth import hash_password
from bilanca.categorize.rules import apply_rules
from bilanca.db import engine, init_db
from bilanca.ingest.csv_import import NkbmCsvSource
from bilanca.ingest.importer import import_source
from bilanca.models import (
    Account,
    Category,
    ImportBatch,
    MatchType,
    Rule,
    RuleSource,
    Transaction,
    User,
    UserSession,
)

DEMO_EMAIL = "demo@bilanca.si"
DEMO_PASSWORD = "demo1234"
ACC = "SI56020170012345678"

HEADER = (
    "ŠT. IZPISKA;POGODBA;RAČUN;DATUM KNJIŽENJA;DATUM VALUTE;DOBRO;BREME;VALUTA;NAMEN;"
    "SKLIC V DOBRO;SKLIC V BREME;UDELEŽENEC - RAČUN;UDELEŽENEC - NAZIV;UDELEŽENEC - BIC;"
    "KODA NAMENA;PRILIV V IZVORNI VALUTI;ODLIV V IZVORNI VALUTI;IZVORNA VALUTA"
)


def _fmt(eur: float) -> str:
    """Evre formatira v slovenski zapis: '1.234,56'."""
    s = f"{eur:,.2f}"  # ameriški zapis '1,234.56'
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _row(booking: date, *, credit: float = 0.0, debit: float = 0.0, purpose: str = "", name: str = "") -> str:
    f = [""] * 18
    f[2] = ACC
    f[3] = booking.strftime("%d.%m.%Y")
    f[4] = booking.strftime("%d.%m.%Y")
    f[5] = _fmt(credit) if credit else ""
    f[6] = _fmt(debit) if debit else ""
    f[7] = "EUR"
    f[8] = purpose
    f[12] = name
    return ";".join(f)


def _day(year: int, month: int, rng: random.Random, weekend_bias: bool = False) -> date:
    """Naključen dan v mesecu; z weekend_bias pogosteje pade na petek/soboto."""
    last = calendar.monthrange(year, month)[1]
    for _ in range(8 if weekend_bias else 1):
        d = date(year, month, rng.randint(1, last))
        if not weekend_bias or d.weekday() in (4, 5):
            return d
    return d


# Trgovci po skupinah (NAMEN del se prepiše posebej, ime nasprotne stranke v poseben stolpec).
GROCERIES = [
    "MERCATOR LJUBLJANA", "SPAR MARIBOR", "HOFER KRANJ", "LIDL CELJE",
    "TUŠ KOPER", "EUROSPIN NOVO MESTO", "INTERSPAR LJUBLJANA",
]
FUEL = ["PETROL D.D. LJUBLJANA", "OMV BTC", "BS MOL DOMŽALE", "SHELL LJUBLJANA"]
RESTAURANTS = [
    "GOSTILNA PRI MARI", "PIZZERIA FOCONTI", "MCDONALD'S CITYPARK",
    "KAVARNA ČOKL", "BURGER SHOP", "OKREPČEVALNICA HOOD", "SLAŠČIČARNA LE PETIT",
]
SHOPPING = ["AMAZON.DE", "MIMOVRSTE.COM", "BIG BANG NAKUP", "DM DROGERIE MARKT", "IKEA LJUBLJANA"]
CLOTHES = ["H&M LJUBLJANA", "ZARA CITYPARK", "DEICHMANN", "INTERSPORT", "SINSAY"]
PHARMACY = ["LEKARNA LJUBLJANA", "LEKARNA MARIBOR", "OPTIKA CLARUS"]
TRANSPORT = ["ARRIVA D.O.O.", "LPP LJUBLJANA", "SLOVENSKE ŽELEZNICE"]
ENTERTAINMENT = ["KOLOSEJ", "CINEPLEXX", "STEAM GAMES", "FITNES KLUB ŠIŠKA"]


def build_csv(start: date, end: date, rng: random.Random) -> bytes:
    rows: list[str] = []

    def add(d: date, *, credit: float = 0.0, debit: float = 0.0, purpose: str = "", name: str = "") -> None:
        if start <= d <= end:
            rows.append(_row(d, credit=credit, debit=debit, purpose=purpose, name=name))

    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        # --- Prihodki ---
        salary = round(rng.uniform(1380, 1620), 2)
        add(date(year, month, min(5, calendar.monthrange(year, month)[1])),
            credit=salary, purpose="PLAČA ZA TEKOČI MESEC", name="PODJETJE NOVA VIZIJA D.O.O.")
        if month in (6, 7):  # regres poleti
            add(_day(year, month, rng), credit=round(rng.uniform(1050, 1250), 2),
                purpose="REGRES ZA LETNI DOPUST", name="PODJETJE NOVA VIZIJA D.O.O.")
        if rng.random() < 0.15:  # občasno vračilo
            add(_day(year, month, rng), credit=round(rng.uniform(8, 90), 2),
                purpose="VRAČILO PREVEČ PLAČANO", name="FURS")

        # --- Fiksni mesečni stroški (z vmesnimi tihimi podražitvami) ---
        netflix = 12.99 if date(year, month, 1) < date(2024, 3, 1) else 13.99
        add(_day(year, month, rng), debit=netflix, purpose="NAROČNINA", name="NETFLIX.COM")
        add(_day(year, month, rng), debit=10.99, purpose="NAROČNINA", name="SPOTIFY AB")
        telemach = 29.90 if date(year, month, 1) < date(2024, 9, 1) else 32.90
        add(_day(year, month, rng), debit=telemach, purpose="INTERNET IN TV", name="TELEMACH D.O.O.")
        add(_day(year, month, rng), debit=round(rng.uniform(48, 78), 2), purpose="ELEKTRIČNA ENERGIJA", name="ELEKTRO ENERGIJA D.O.O.")
        add(_day(year, month, rng), debit=round(rng.uniform(30, 44), 2), purpose="KOMUNALNE STORITVE", name="KOMUNALA LJUBLJANA")
        add(_day(year, month, rng), debit=12.75, purpose="RTV PRISPEVEK", name="RTV SLOVENIJA")
        add(_day(year, month, rng), debit=550.00, purpose="NAJEMNINA STANOVANJA", name="NAJEMODAJALEC")
        if month == 1:  # letno zavarovanje
            add(_day(year, month, rng), debit=round(rng.uniform(210, 240), 2),
                purpose="LETNA PREMIJA", name="ZAVAROVALNICA TRIGLAV D.D.")

        # --- Živila (vikend-pristranskost) ---
        for _ in range(rng.randint(6, 10)):
            add(_day(year, month, rng, weekend_bias=True),
                debit=round(rng.uniform(7, 68), 2), purpose="POS NAKUP", name=rng.choice(GROCERIES))
        # --- Gorivo ---
        for _ in range(rng.randint(1, 3)):
            add(_day(year, month, rng), debit=round(rng.uniform(45, 78), 2),
                purpose="POS NAKUP GORIVO", name=rng.choice(FUEL))
        # --- Restavracije / kava (vikend-pristranskost) ---
        for _ in range(rng.randint(4, 8)):
            add(_day(year, month, rng, weekend_bias=True),
                debit=round(rng.uniform(2.2, 27), 2), purpose="POS NAKUP", name=rng.choice(RESTAURANTS))
        # --- Gotovina ---
        if rng.random() < 0.7:
            add(_day(year, month, rng), debit=float(rng.choice([20, 30, 50, 50, 100])),
                purpose="DVIG GOTOVINE BANKOMAT", name="BANKOMAT NLB")
        # --- Občasni nakupi ---
        if rng.random() < 0.5:
            add(_day(year, month, rng), debit=round(rng.uniform(9, 140), 2),
                purpose="SPLETNI NAKUP", name=rng.choice(SHOPPING))
        if rng.random() < 0.3:
            add(_day(year, month, rng, weekend_bias=True), debit=round(rng.uniform(15, 95), 2),
                purpose="POS NAKUP", name=rng.choice(CLOTHES))
        if rng.random() < 0.35:
            add(_day(year, month, rng), debit=round(rng.uniform(6, 45), 2),
                purpose="POS NAKUP", name=rng.choice(PHARMACY))
        if rng.random() < 0.4:
            add(_day(year, month, rng), debit=round(rng.uniform(1.3, 9), 2),
                purpose="VOZOVNICA", name=rng.choice(TRANSPORT))
        if rng.random() < 0.3:
            add(_day(year, month, rng, weekend_bias=True), debit=round(rng.uniform(8, 60), 2),
                purpose="POS NAKUP", name=rng.choice(ENTERTAINMENT))

        month += 1
        if month > 12:
            month = 1
            year += 1

    text = "\r\n".join([HEADER, *rows]) + "\r\n"
    return text.encode("cp1250")


def _purge_existing(session: Session, user: User) -> None:
    acc_ids = session.exec(select(Account.id).where(Account.user_id == user.id)).all()
    if acc_ids:
        for t in session.exec(select(Transaction).where(Transaction.account_id.in_(acc_ids))).all():
            session.delete(t)
    for batch in session.exec(select(ImportBatch).where(ImportBatch.user_id == user.id)).all():
        session.delete(batch)
    for acc in session.exec(select(Account).where(Account.user_id == user.id)).all():
        session.delete(acc)
    for rule in session.exec(select(Rule).where(Rule.user_id == user.id, Rule.source == RuleSource.USER)).all():
        session.delete(rule)
    for sess in session.exec(select(UserSession).where(UserSession.user_id == user.id)).all():
        session.delete(sess)
    session.commit()


def main() -> None:
    init_db()
    rng = random.Random(42)

    end = date.today() - timedelta(days=5)
    start = date(end.year - 4, end.month, 1)
    csv_bytes = build_csv(start, end, rng)

    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == DEMO_EMAIL)).first()
        if user:
            _purge_existing(session, user)
            user.password_hash = hash_password(DEMO_PASSWORD)
            session.add(user)
            session.commit()
        else:
            user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
            session.add(user)
            session.commit()
            session.refresh(user)

        batch = import_source(
            session, NkbmCsvSource(csv_bytes), user, f"demo-promet-{start:%Y%m}-{end:%Y%m}.csv"
        )
        inserted = batch.inserted_count

        # Najemnina nima sistemskega pravila → razvrstimo jo z uporabniškim pravilom,
        # da prikaz ni preplavljen z "Nerazvrščeno".
        rent_cat = session.exec(
            select(Category).where(Category.name == "Položnice in komunala")
        ).first()
        if rent_cat:
            session.add(Rule(
                match_type=MatchType.CONTAINS, pattern="NAJEMNINA",
                category_id=rent_cat.id, priority=500, source=RuleSource.USER, user_id=user.id,
            ))
            session.commit()
            apply_rules(session, user, only_uncategorized=True)

        total = len(session.exec(
            select(Transaction).where(
                Transaction.account_id.in_(select(Account.id).where(Account.user_id == user.id))
            )
        ).all())

    print("Demo uporabnik pripravljen.")
    print(f"  Obdobje:     {start:%d.%m.%Y} – {end:%d.%m.%Y}")
    print(f"  Transakcij:  {total} (uvoženih {inserted})")
    print(f"  E-pošta:     {DEMO_EMAIL}")
    print(f"  Geslo:       {DEMO_PASSWORD}")


if __name__ == "__main__":
    main()
