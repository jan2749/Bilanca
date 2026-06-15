"""Odkrivanje dvojnikov ob (ponovnem) uvozu.

NKBM izvoz nima unikatnega ID-ja transakcije, hkrati pa lahko obstajajo pristni dvojniki
(npr. dva enaka dviga gotovine isti dan). Zato:

1. Iz vsebine transakcije sestavimo "base key".
2. Znotraj uvoza identičnim transakcijam dodelimo zaporedno številko (occurrence) 0,1,2…
3. Končni dedup_hash = hash(base_key + occurrence).

Ob ponovnem uvozu prekrivajočega obdobja se isti nabor transakcij preslika v iste hash-e,
zato se obstoječi preskočijo, pristni dvojniki pa ostanejo ločeni.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from bilanca.ingest.base import NormalizedTxn


def _base_key(txn: NormalizedTxn) -> str:
    parts = [
        txn.account_iban,
        txn.booking_date.isoformat(),
        txn.value_date.isoformat(),
        str(txn.amount_cents),
        txn.purpose.strip().casefold(),
        txn.counterparty_iban.strip(),
        txn.reference.strip(),
    ]
    return "|".join(parts)


def compute_hash(base_key: str, occurrence: int) -> str:
    return hashlib.sha1(f"{base_key}#{occurrence}".encode()).hexdigest()


def assign_hashes(txns: list[NormalizedTxn]) -> list[tuple[NormalizedTxn, str, int]]:
    """Vsaki transakciji dodeli (dedup_hash, occurrence), stabilno znotraj uvoza."""
    counters: dict[str, int] = defaultdict(int)
    result: list[tuple[NormalizedTxn, str, int]] = []
    for txn in txns:
        key = _base_key(txn)
        occ = counters[key]
        counters[key] += 1
        result.append((txn, compute_hash(key, occ), occ))
    return result
