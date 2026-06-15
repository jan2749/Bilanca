"""Pravilni stroj za kategorizacijo.

Pravila se preverjajo po padajočem priority (prvo ujemanje zmaga). Ujemanje teče nad
združenim besedilom opisa (NAMEN) in naziva nasprotne stranke, razen IBAN ujemanja.
"""

from __future__ import annotations

import re

from sqlmodel import Session, select

from bilanca.models import MatchType, Rule, RuleSource, Transaction

# Naučena uporabniška pravila imajo visoko prioriteto, da prehitijo sistemska.
USER_RULE_PRIORITY = 500


def _haystack(txn: Transaction) -> str:
    return f"{txn.purpose} {txn.counterparty_name}".casefold()


def _matches(rule: Rule, txn: Transaction) -> bool:
    if rule.match_type == MatchType.IBAN:
        return bool(rule.pattern) and rule.pattern.strip() in (txn.counterparty_iban or "")
    text = _haystack(txn)
    pat = rule.pattern.casefold()
    if rule.match_type == MatchType.CONTAINS:
        return pat in text
    if rule.match_type == MatchType.EXACT:
        return pat == text.strip()
    if rule.match_type == MatchType.REGEX:
        try:
            return re.search(rule.pattern, text, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def load_rules(session: Session) -> list[Rule]:
    """Naloži pravila, urejena po prioriteti (najprej najvišja)."""
    return list(
        session.exec(select(Rule).order_by(Rule.priority.desc(), Rule.id.asc())).all()
    )


def categorize_one(txn: Transaction, rules: list[Rule]) -> int | None:
    """Vrne category_id prvega ujemajočega pravila ali None."""
    for rule in rules:
        if _matches(rule, txn):
            return rule.category_id
    return None


def apply_rules(session: Session, only_uncategorized: bool = True) -> int:
    """Kategorizira transakcije po pravilih. Zaklenjenih (ročnih) ne dira.

    Vrne število spremenjenih transakcij.
    """
    rules = load_rules(session)
    if not rules:
        return 0

    query = select(Transaction).where(Transaction.category_locked == False)  # noqa: E712
    if only_uncategorized:
        query = query.where(Transaction.category_id == None)  # noqa: E711

    changed = 0
    for txn in session.exec(query).all():
        new_cat = categorize_one(txn, rules)
        if new_cat is not None and new_cat != txn.category_id:
            txn.category_id = new_cat
            session.add(txn)
            changed += 1
    if changed:
        session.commit()
    return changed


def set_category(
    session: Session,
    txn_id: int,
    category_id: int | None,
    create_rule: bool = False,
) -> int:
    """Ročno nastavi kategorijo transakcije (in jo zakleni).

    Če create_rule=True, iz naziva nasprotne stranke (ali opisa) ustvari naučeno pravilo
    in ga uporabi na ostalih nezaklenjenih transakcijah. Vrne število dodatno spremenjenih.
    """
    txn = session.get(Transaction, txn_id)
    if txn is None:
        return 0
    txn.category_id = category_id
    txn.category_locked = True
    session.add(txn)

    extra_changed = 0
    if create_rule and category_id is not None:
        pattern = (txn.counterparty_name or txn.purpose or "").strip()
        if pattern:
            existing = session.exec(
                select(Rule).where(Rule.pattern == pattern, Rule.source == RuleSource.USER)
            ).first()
            if existing:
                existing.category_id = category_id
                session.add(existing)
            else:
                session.add(
                    Rule(
                        match_type=MatchType.CONTAINS,
                        pattern=pattern,
                        category_id=category_id,
                        priority=USER_RULE_PRIORITY,
                        source=RuleSource.USER,
                    )
                )
            session.commit()
            extra_changed = apply_rules(session, only_uncategorized=False)
    else:
        session.commit()
    return extra_changed
