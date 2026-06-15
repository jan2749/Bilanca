"""Vir transakcij iz naložene CSV datoteke (trenutno profil NKBM/OTP)."""

from __future__ import annotations

from collections.abc import Iterable

from bilanca.ingest.base import NormalizedTxn
from bilanca.ingest.profiles import nkbm


class NkbmCsvSource:
    """TransactionSource, ki bere NKBM/OTP CSV izvoz iz surovih bajtov."""

    source_type = nkbm.SOURCE_TYPE

    def __init__(self, raw: bytes) -> None:
        self._raw = raw

    def fetch(self) -> Iterable[NormalizedTxn]:
        return nkbm.parse(self._raw)
