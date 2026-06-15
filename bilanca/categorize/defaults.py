"""Privzeta vgrajena pravila za kategorizacijo (slovenski trgovci/storitve).

Vzorci so izpeljani iz resničnih NKBM/OTP opisov. Ujemanje je neobčutljivo na velikost črk
in deluje kot podniz nad "NAMEN + naziv nasprotne stranke".
"""

from __future__ import annotations

from sqlmodel import Session, select

from bilanca.models import Category, MatchType, Rule, RuleSource

# (vzorec, ime_kategorije, prioriteta). Višja prioriteta = preverjeno prej.
# Bolj specifične vzorce postavimo višje, da prehitijo splošne.
DEFAULT_RULES: list[tuple[str, str, int]] = [
    # Naročnine (digitalne) — specifične, visoka prioriteta
    ("APPLE.COM/BILL", "Naročnine", 300),
    ("GOOGLE", "Naročnine", 300),
    ("YOUTUBE", "Naročnine", 300),
    ("NETFLIX", "Naročnine", 300),
    ("SPOTIFY", "Naročnine", 300),
    ("CLAUDE.AI", "Naročnine", 300),
    ("OPENAI", "Naročnine", 300),
    ("CLOUDFLARE", "Naročnine", 300),
    ("DISNEY", "Naročnine", 300),
    ("HBO", "Naročnine", 300),
    # Položnice in komunala
    ("TELEMACH", "Položnice in komunala", 290),
    ("TELEKOM", "Položnice in komunala", 290),
    ("A1.SI", "Položnice in komunala", 290),
    ("ELEKTRO", "Položnice in komunala", 290),
    ("PETROL PLIN", "Položnice in komunala", 295),
    # Javni prevoz
    ("URBANA", "Javni prevoz", 280),
    ("LPP", "Javni prevoz", 280),
    ("SLOVENSKE ŽELEZNICE", "Javni prevoz", 280),
    ("ARRIVA", "Javni prevoz", 280),
    # Promet in gorivo (bencinski servisi)
    ("BS MOL", "Promet in gorivo", 270),
    ("BS LOM", "Promet in gorivo", 270),
    ("PETROL", "Promet in gorivo", 260),
    ("OMV", "Promet in gorivo", 270),
    ("MOL ", "Promet in gorivo", 250),
    ("AVRIGO", "Promet in gorivo", 250),
    # Zdravje
    ("LEKARNA", "Zdravje in lekarna", 260),
    ("POLIKL", "Zdravje in lekarna", 260),
    ("ZDRAVSTVE", "Zdravje in lekarna", 260),
    ("ZOBOZDRAV", "Zdravje in lekarna", 260),
    # Restavracije, kava, hitra prehrana
    ("RESTAVRACIJA", "Restavracije in kava", 240),
    ("PIZZERIA", "Restavracije in kava", 240),
    ("FAST FOOD", "Restavracije in kava", 240),
    ("KAVARNA", "Restavracije in kava", 240),
    ("BURGER", "Restavracije in kava", 240),
    ("GOSTILNA", "Restavracije in kava", 240),
    ("ALPE PANON", "Restavracije in kava", 240),
    ("DELIKOMAT", "Restavracije in kava", 230),
    ("MCDONALD", "Restavracije in kava", 240),
    # Hrana in pijača (trgovine)
    ("MERCATOR", "Hrana in pijača", 220),
    ("INTERSPAR", "Hrana in pijača", 225),
    ("SPAR", "Hrana in pijača", 220),
    ("HOFER", "Hrana in pijača", 220),
    ("LIDL", "Hrana in pijača", 220),
    ("TUŠ", "Hrana in pijača", 220),
    ("E.LECLERC", "Hrana in pijača", 220),
    ("MARKET", "Hrana in pijača", 200),
    ("SAMOPOSTREZBA", "Hrana in pijača", 200),
    ("ŽITO", "Hrana in pijača", 200),
    # Gotovina
    ("DVIG GOTOVINE", "Gotovina (dvig)", 280),
    ("BANKOMAT", "Gotovina (dvig)", 280),
    # Prihodki
    ("ŠTIPENDIJE", "Štipendija", 300),
    ("STIPENDIJE", "Štipendija", 300),
    ("PLAČA", "Plača in honorarji", 300),
    ("PLACA", "Plača in honorarji", 300),
]


def seed_rules(session: Session) -> None:
    """Vstavi privzeta pravila, če sistemskih še ni (idempotentno)."""
    existing = session.exec(
        select(Rule).where(Rule.source == RuleSource.SYSTEM).limit(1)
    ).first()
    if existing is not None:
        return

    cat_by_name = {c.name: c.id for c in session.exec(select(Category)).all()}
    rules: list[Rule] = []
    for pattern, cat_name, priority in DEFAULT_RULES:
        cat_id = cat_by_name.get(cat_name)
        if cat_id is None:
            continue
        rules.append(
            Rule(
                match_type=MatchType.CONTAINS,
                pattern=pattern,
                category_id=cat_id,
                priority=priority,
                source=RuleSource.SYSTEM,
            )
        )
    session.add_all(rules)
    session.commit()
