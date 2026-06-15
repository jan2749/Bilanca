"""Testi za razčlenjevanje NKBM CSV in pretvorbo zneskov/datumov."""

from __future__ import annotations

from datetime import date

from bilanca.ingest.profiles import nkbm


def test_parse_amount_slovenian_format():
    assert nkbm.parse_amount("3,99") == 399
    assert nkbm.parse_amount("1.234,56") == 123456
    assert nkbm.parse_amount("0,49") == 49
    assert nkbm.parse_amount("") == 0
    assert nkbm.parse_amount("100,00") == 10000


def test_parse_date():
    assert nkbm.parse_date("14.06.2026") == date(2026, 6, 14)


def test_parse_basic_rows(nkbm_csv_bytes):
    txns = nkbm.parse(nkbm_csv_bytes)
    # 5 transakcij (6. prazna vrstica preskočena)
    assert len(txns) == 5

    apple = txns[0]
    assert apple.amount_cents == -399  # BREME → negativno
    assert apple.purpose == "APPLE.COM/BILL"  # končni presledki odrezani
    assert apple.currency == "EUR"
    assert apple.booking_date == date(2026, 6, 14)

    spar = txns[1]
    assert spar.purpose == "SPAR ŠENTJUR"  # slovenski znaki (cp1250)

    priliv = txns[2]
    assert priliv.amount_cents == 7835  # DOBRO → pozitivno
    assert priliv.counterparty_name == "MDDSZ-DRŽAVNE ŠTIPENDIJE"
    assert priliv.purpose_code == "STDY"


def test_decode_cp1250(nkbm_csv_bytes):
    text = nkbm.decode_bytes(nkbm_csv_bytes)
    assert "ŠENTJUR" in text
    assert "DRŽAVNE" in text


def test_missing_columns_raises():
    bad = "A;B;C\r\n1;2;3\r\n".encode("cp1250")
    try:
        nkbm.parse(bad)
        assert False, "pričakovana NkbmParseError"
    except nkbm.NkbmParseError:
        pass
