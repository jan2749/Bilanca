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
    ("ICLOUD", "Naročnine", 300),
    ("GOOGLE", "Naročnine", 300),
    ("YOUTUBE", "Naročnine", 300),
    ("NETFLIX", "Naročnine", 300),
    ("SPOTIFY", "Naročnine", 300),
    ("CLAUDE.AI", "Naročnine", 300),
    ("ANTHROPIC", "Naročnine", 300),
    ("OPENAI", "Naročnine", 300),
    ("CLOUDFLARE", "Naročnine", 300),
    ("DISNEY", "Naročnine", 300),
    ("HBO", "Naročnine", 300),
    ("MICROSOFT", "Naročnine", 300),
    ("ADOBE", "Naročnine", 300),
    ("DROPBOX", "Naročnine", 300),
    ("PATREON", "Naročnine", 300),
    ("TWITCH", "Naročnine", 300),
    ("AUDIBLE", "Naročnine", 300),
    ("LINKEDIN", "Naročnine", 300),
    ("GITHUB", "Naročnine", 300),
    ("NOTION", "Naročnine", 300),
    ("CANVA", "Naročnine", 300),
    ("NORDVPN", "Naročnine", 300),
    ("PLAYSTATION NETWORK", "Naročnine", 300),
    ("XBOX", "Naročnine", 300),
    # Zavarovanja (specifično pred trgovci z istim korenom, npr. MERKUR)
    ("ZAVAROVALNICA", "Zavarovanja", 296),
    ("MERKUR ZAVAROVALNICA", "Zavarovanja", 297),
    ("TRIGLAV", "Zavarovanja", 296),
    ("VZAJEMNA", "Zavarovanja", 296),
    ("ADRIATIC SLOVENICA", "Zavarovanja", 296),
    ("GENERALI", "Zavarovanja", 296),
    ("SAVA ZAVAROVAL", "Zavarovanja", 296),
    ("MODRA ZAVAROVAL", "Zavarovanja", 296),
    ("NLB VITA", "Zavarovanja", 296),
    # Položnice in komunala
    ("PETROL PLIN", "Položnice in komunala", 295),
    ("TELEMACH", "Položnice in komunala", 290),
    ("TELEKOM", "Položnice in komunala", 290),
    ("A1.SI", "Položnice in komunala", 290),
    ("A1 SLOVENIJA", "Položnice in komunala", 290),
    ("T-2", "Položnice in komunala", 290),
    ("SIOL", "Položnice in komunala", 290),
    ("ELEKTRO", "Položnice in komunala", 290),
    ("KOMUNALA", "Položnice in komunala", 290),
    ("VODOVOD", "Položnice in komunala", 290),
    ("TOPLARNA", "Položnice in komunala", 290),
    ("ENERGETIKA", "Položnice in komunala", 285),
    ("RTV SLOVENIJA", "Položnice in komunala", 290),
    ("RTV PRISPEVEK", "Položnice in komunala", 290),
    # Javni prevoz
    ("URBANA", "Javni prevoz", 280),
    ("LPP", "Javni prevoz", 280),
    ("SLOVENSKE ŽELEZNICE", "Javni prevoz", 280),
    ("ARRIVA", "Javni prevoz", 280),
    ("NOMAGO", "Javni prevoz", 280),
    ("FLIXBUS", "Javni prevoz", 280),
    # Promet in gorivo (bencinski servisi, cestnine, parkirnine)
    ("BS MOL", "Promet in gorivo", 270),
    ("BS LOM", "Promet in gorivo", 270),
    ("OMV", "Promet in gorivo", 270),
    ("SHELL", "Promet in gorivo", 270),
    ("AVANT", "Promet in gorivo", 270),
    ("DARS", "Promet in gorivo", 270),
    ("VINJETA", "Promet in gorivo", 270),
    ("AVTOCESTA", "Promet in gorivo", 270),
    ("PARKIR", "Promet in gorivo", 265),
    ("PARKOMAT", "Promet in gorivo", 265),
    ("PETROL", "Promet in gorivo", 260),
    ("MOL ", "Promet in gorivo", 250),
    ("AVRIGO", "Promet in gorivo", 250),
    # Zdravje
    ("LEKARNA", "Zdravje in lekarna", 260),
    ("POLIKL", "Zdravje in lekarna", 260),
    ("ZDRAVSTVE", "Zdravje in lekarna", 260),
    ("ZOBOZDRAV", "Zdravje in lekarna", 260),
    ("OPTIKA", "Zdravje in lekarna", 260),
    ("SANOLABOR", "Zdravje in lekarna", 260),
    ("DIAGNOST", "Zdravje in lekarna", 255),
    # Restavracije, kava, hitra prehrana, pekarne
    ("RESTAVRACIJA", "Restavracije in kava", 240),
    ("PIZZERIA", "Restavracije in kava", 240),
    ("FAST FOOD", "Restavracije in kava", 240),
    ("KAVARNA", "Restavracije in kava", 240),
    ("BURGER", "Restavracije in kava", 240),
    ("GOSTILNA", "Restavracije in kava", 240),
    ("ALPE PANON", "Restavracije in kava", 240),
    ("MCDONALD", "Restavracije in kava", 240),
    ("SUBWAY", "Restavracije in kava", 240),
    ("KFC", "Restavracije in kava", 240),
    ("OKREP", "Restavracije in kava", 235),
    ("SLAŠČIČARNA", "Restavracije in kava", 235),
    ("PEKARNA", "Restavracije in kava", 235),
    ("DELIKOMAT", "Restavracije in kava", 230),
    # Hrana in pijača (trgovine)
    ("INTERSPAR", "Hrana in pijača", 225),
    ("MERCATOR", "Hrana in pijača", 220),
    ("SPAR", "Hrana in pijača", 220),
    ("HOFER", "Hrana in pijača", 220),
    ("LIDL", "Hrana in pijača", 220),
    ("TUŠ", "Hrana in pijača", 220),
    ("EUROSPIN", "Hrana in pijača", 220),
    ("E.LECLERC", "Hrana in pijača", 220),
    ("KGZ", "Hrana in pijača", 205),
    ("MLEKARNA", "Hrana in pijača", 205),
    ("MARKET", "Hrana in pijača", 200),
    ("SAMOPOSTREZBA", "Hrana in pijača", 200),
    ("ŽITO", "Hrana in pijača", 200),
    # Oblačila in obutev
    ("H&M", "Oblačila in obutev", 215),
    ("ZARA", "Oblačila in obutev", 215),
    ("C&A", "Oblačila in obutev", 215),
    ("SINSAY", "Oblačila in obutev", 215),
    ("SPORTINA", "Oblačila in obutev", 215),
    ("DEICHMANN", "Oblačila in obutev", 215),
    ("NEW YORKER", "Oblačila in obutev", 215),
    ("TAKKO", "Oblačila in obutev", 215),
    ("PRIMARK", "Oblačila in obutev", 215),
    ("HERVIS", "Oblačila in obutev", 215),
    ("INTERSPORT", "Oblačila in obutev", 215),
    ("DECATHLON", "Oblačila in obutev", 215),
    ("ZALANDO", "Oblačila in obutev", 215),
    # Trgovine in nakupi (tehnika, dom, splet)
    ("MERKUR", "Trgovine in nakupi", 205),
    ("BIG BANG", "Trgovine in nakupi", 210),
    ("HARVEY NORMAN", "Trgovine in nakupi", 210),
    ("MIMOVRSTE", "Trgovine in nakupi", 210),
    ("BAUHAUS", "Trgovine in nakupi", 210),
    ("OBI ", "Trgovine in nakupi", 210),
    ("JYSK", "Trgovine in nakupi", 210),
    ("LESNINA", "Trgovine in nakupi", 210),
    ("IKEA", "Trgovine in nakupi", 210),
    ("DM DROGERIE", "Trgovine in nakupi", 210),
    ("MÜLLER", "Trgovine in nakupi", 210),
    ("MUELLER", "Trgovine in nakupi", 210),
    ("TEDI", "Trgovine in nakupi", 210),
    ("PEPCO", "Trgovine in nakupi", 210),
    ("AMAZON", "Trgovine in nakupi", 210),
    ("ALIEXPRESS", "Trgovine in nakupi", 210),
    ("EBAY", "Trgovine in nakupi", 210),
    # Zabava in prosti čas
    ("KOLOSEJ", "Zabava in prosti čas", 215),
    ("CINEPLEXX", "Zabava in prosti čas", 215),
    ("KINO", "Zabava in prosti čas", 210),
    ("GLEDALIŠČE", "Zabava in prosti čas", 210),
    ("STEAM GAMES", "Zabava in prosti čas", 215),
    ("FITNES", "Zabava in prosti čas", 210),
    ("WELLNESS", "Zabava in prosti čas", 210),
    # Bančni stroški
    ("NADOMESTILO ZA", "Bančni stroški", 250),
    ("STROŠEK VODENJA", "Bančni stroški", 250),
    ("VODENJE RAČUNA", "Bančni stroški", 250),
    ("VZDRŽEVANJE RAČUNA", "Bančni stroški", 250),
    ("PROVIZIJA", "Bančni stroški", 245),
    # Gotovina
    ("DVIG GOTOVINE", "Gotovina (dvig)", 280),
    ("BANKOMAT", "Gotovina (dvig)", 280),
    # Prihodki
    ("ŠTIPENDIJE", "Štipendija", 300),
    ("STIPENDIJE", "Štipendija", 300),
    ("PLAČA", "Plača in honorarji", 300),
    ("PLACA", "Plača in honorarji", 300),
    ("REGRES", "Plača in honorarji", 290),
    ("POVRAČILO", "Nakazila in vračila", 280),
    ("VRAČILO", "Nakazila in vračila", 280),
    ("DIVIDENDA", "Drugo (prihodki)", 280),
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
