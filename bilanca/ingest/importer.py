"""Cevovod uvoza: vir → dedup → vstavljanje v bazo + zapis o uvozu (ImportBatch)."""

from __future__ import annotations

from sqlmodel import Session, select

from bilanca.ingest.base import NormalizedTxn, TransactionSource
from bilanca.ingest.dedup import assign_hashes
from bilanca.models import Account, ImportBatch, Transaction


def get_or_create_account(session: Session, iban: str) -> Account:
    """Poišče račun po IBAN ali ga ustvari."""
    iban = (iban or "").strip()
    acc = session.exec(select(Account).where(Account.iban == iban)).first()
    if acc:
        return acc
    acc = Account(name=iban or "Moj račun", iban=iban)
    session.add(acc)
    session.commit()
    session.refresh(acc)
    return acc


def import_source(
    session: Session,
    source: TransactionSource,
    filename: str = "",
) -> ImportBatch:
    """Uvozi transakcije iz vira; preskoči dvojnike. Vrne zapis o uvozu."""
    txns: list[NormalizedTxn] = list(source.fetch())

    batch = ImportBatch(
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
        existing = session.exec(
            select(Transaction).where(Transaction.dedup_hash == dedup_hash)
        ).first()
        if existing:
            duplicates += 1
            continue

        account = get_or_create_account(session, txn.account_iban)
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
    return batch
