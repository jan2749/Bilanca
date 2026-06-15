"""Testi za zaznavo naročnin in tihih podražitev."""

from __future__ import annotations

from datetime import date, timedelta

from sqlmodel import Session, SQLModel, create_engine

from bilanca.insights.recurring import detect, normalize_merchant
from bilanca.models import Transaction


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _add(session, purpose, amount_eur, d, h=None):
    h = h or f"{purpose}-{d}"
    session.add(
        Transaction(
            account_id=1,
            booking_date=d,
            value_date=d,
            amount_cents=int(round(-amount_eur * 100)),
            purpose=purpose,
            dedup_hash=h,
        )
    )


def test_normalize_merchant_strips_and_collapses():
    assert normalize_merchant("APPLE.COM/BILL   ") == "apple.com/bill"
    assert normalize_merchant("SPAR   ŠENTJUR") == "spar šentjur"


def test_detect_monthly_subscription():
    with _session() as s:
        base = date(2026, 1, 5)
        for i in range(4):  # 4 mesečne bremenitve po 9,99
            _add(s, "NETFLIX.COM", 9.99, base + timedelta(days=30 * i), h=f"nf{i}")
        s.commit()
        report = detect(s, as_of=date(2026, 4, 10))
        netflix = [x for x in report.subscriptions if "NETFLIX" in x.label.upper()]
        assert len(netflix) == 1
        sub = netflix[0]
        assert sub.period_label == "mesečno"
        assert sub.amount_eur == 9.99
        assert sub.count == 4
        assert sub.is_active is True


def test_detect_silent_price_hike():
    with _session() as s:
        base = date(2026, 1, 10)
        # 3 mesece po 12,99, nato 3 mesece po 15,99
        for i in range(3):
            _add(s, "SPOTIFY", 12.99, base + timedelta(days=30 * i), h=f"sp_old{i}")
        for i in range(3, 6):
            _add(s, "SPOTIFY", 15.99, base + timedelta(days=30 * i), h=f"sp_new{i}")
        s.commit()
        report = detect(s, as_of=date(2026, 7, 1))
        assert len(report.price_hikes) == 1
        hike = report.price_hikes[0]
        assert hike.old_eur == 12.99
        assert hike.new_eur == 15.99
        assert hike.pct > 0


def test_inactive_subscription_flagged():
    with _session() as s:
        base = date(2026, 1, 1)
        for i in range(3):
            _add(s, "OLDSERVICE", 5.00, base + timedelta(days=30 * i), h=f"old{i}")
        s.commit()
        # ocenjeno dolgo po zadnji bremenitvi → ni več aktivna
        report = detect(s, as_of=date(2026, 8, 1))
        old = [x for x in report.subscriptions if "OLDSERVICE" in x.label.upper()][0]
        assert old.is_active is False
