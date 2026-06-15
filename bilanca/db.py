"""Povezava z bazo in upravljanje sej (SQLModel/SQLAlchemy nad SQLite)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from bilanca.config import DATABASE_URL

# check_same_thread=False, ker FastAPI lahko dela z razlicnih niti.
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Ustvari tabele, ce se ne obstajajo."""
    # Uvoz modelov registrira tabele na SQLModel.metadata.
    import bilanca.models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: ena seja na zahtevo."""
    with Session(engine) as session:
        yield session
