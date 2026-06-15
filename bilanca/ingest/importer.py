"""Cevovod uvoza: vir → dedup → vstavljanje v bazo + zapis o uvozu (ImportBatch)."""

from __future__ import annotations

from sqlmodel import Session, select

from bilanca.ingest.base import NormalizedTxn, TransactionSource
from bilanca.ingest.dedup import assign_hashes
from bilanca.models import Account, ImportBatch, Transaction, User


def get_or_create_account(session: Session, user: User, iban: str) -> Account:
    """Poišče uporabnikov račun po IBAN ali ga ustvari."""
    iban = (iban or "").strip()
    acc = session.exec(
        select(Account).where(Account.user_id == user.id, Account.iban == iban)
    ).first()
    if acc:
        return acc
    acc = Account(user_id=user.id, name=iban or "Moj račun", iban=iban)
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


def import_source(
    session: Session,
    source: TransactionSource,
    user: User,
    filename: str = "",
) -> ImportBatch:
    """Uvozi transakcije iz vira za uporabnika; preskoči dvojnike. Vrne zapis o uvozu."""
    txns: list[NormalizedTxn] = list(source.fetch())

    batch = ImportBatch(
        user_id=user.id,
        source_type=getattr(source, "source_type", "unknown"),
        filename=filename,
        row_count=len(txns),
    )
    session.add(batch)
    session.commit()
    session.refresh(batch)

    inserted = 0
    duplicates = 0
    for txn, dedup_hash, occurrence in assign_hashes(txns):
        account = get_or_create_account(session, user, txn.account_iban)
        existing = session.exec(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.dedup_hash == dedup_hash,
            )
        ).first()
        if existing:
            duplicates += 1
            continue

        session.add(
            Transaction(
                account_id=account.id,
                booking_date=txn.booking_date,
                value_date=txn.value_date,
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                purpose=txn.purpose,
                counterparty_name=txn.counterparty_name,
                counterparty_iban=txn.counterparty_iban,
                reference=txn.reference,
                purpose_code=txn.purpose_code,
                import_batch_id=batch.id,
                dedup_hash=dedup_hash,
                occurrence=occurrence,
            )
        )
        inserted += 1

    batch.inserted_count = inserted
    batch.duplicate_count = duplicates
    session.add(batch)
    session.commit()
    session.refresh(batch)

    # Samodejno kategoriziraj novo uvožene (zaklenjenih ročnih ne dira).
    if inserted:
        from bilanca.categorize.rules import apply_rules

        apply_rules(session, user, only_uncategorized=True)

    return batch
