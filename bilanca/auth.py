"""Avtentikacija: zgoščevanje gesel (pbkdf2, standardna knjižnica) in sejni žetoni v bazi.

Brez zunanjih odvisnosti — gesla shranimo kot `pbkdf2_sha256$iteracije$sol$zgostek`,
seja je naključen žeton v piškotku, ki kaže na vrstico v `UserSession`.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from sqlmodel import Session, select

from bilanca.db import get_session
from bilanca.models import User, UserSession

COOKIE_NAME = "bilanca_session"
SESSION_DAYS = 30
_ITERATIONS = 240_000


class AuthRedirect(Exception):
    """Neprijavljen dostop do zaščitene strani → preusmeritev na /login."""


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
    return secrets.compare_digest(dk.hex(), hash_hex)


def create_session(session: Session, user: User) -> str:
    """Ustvari sejni žeton za uporabnika in ga shrani; vrne žeton za piškotek."""
    token = secrets.token_urlsafe(32)
    session.add(
        UserSession(
            token=token,
            user_id=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=SESSION_DAYS),
        )
    )
    session.commit()
    return token


def destroy_session(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.exec(select(UserSession).where(UserSession.token == token)).first()
    if row is not None:
        session.delete(row)
        session.commit()


def _user_for_token(session: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = session.exec(select(UserSession).where(UserSession.token == token)).first()
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite vrne naivni datetime
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return None
    return session.get(User, row.user_id)


def optional_current_user(
    request: Request, session: Session = Depends(get_session)
) -> User | None:
    """Vrne prijavljenega uporabnika ali None (za javne strani)."""
    return _user_for_token(session, request.cookies.get(COOKIE_NAME))


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Zahteva prijavo; sicer sproži preusmeritev na /login."""
    user = _user_for_token(session, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise AuthRedirect()
    return user
