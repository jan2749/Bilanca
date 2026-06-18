"""Nastavitve aplikacije in poti."""

from __future__ import annotations

import os
from pathlib import Path

# Korenska mapa projekta (kjer je pyproject.toml).
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Preprost nalagalnik .env (brez zunanje odvisnosti).

    Prebere KEY=VALUE vrstice iz .env v korenu projekta in jih vstavi v okolje,
    ne da bi povozil že nastavljene spremenljivke. Prazne vrstice in komentarje (#)
    preskoči; odstrani morebitne narekovaje okrog vrednosti.
    """
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# Mapa za lokalne podatke (baza, nalozene datoteke). Ni v gitu.
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Pot do SQLite baze. Lahko se prepise prek okoljske spremenljivke BILANCA_DB.
DB_PATH = Path(os.environ.get("BILANCA_DB", DATA_DIR / "bilanca.db"))
DATABASE_URL = f"sqlite:///{DB_PATH}"

# Poti znotraj web paketa.
WEB_DIR = Path(__file__).resolve().parent / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Privzeta valuta (slovenske banke vodijo EUR).
DEFAULT_CURRENCY = "EUR"

# ---------------------------------------------------------------- GoCardless (PSD2)
# Poverilnice agregatorja GoCardless Bank Account Data (prej Nordigen). Pridobiš jih
# brezplačno na https://bankaccountdata.gocardless.com → Developers → User secrets.
GOCARDLESS_SECRET_ID = os.environ.get("GOCARDLESS_SECRET_ID", "").strip()
GOCARDLESS_SECRET_KEY = os.environ.get("GOCARDLESS_SECRET_KEY", "").strip()
GOCARDLESS_BASE_URL = os.environ.get(
    "GOCARDLESS_BASE_URL", "https://bankaccountdata.gocardless.com"
).rstrip("/")


def gocardless_configured() -> bool:
    """True, če sta nastavljena oba GoCardless ključa (sicer je povezava z banko skrita)."""
    return bool(GOCARDLESS_SECRET_ID and GOCARDLESS_SECRET_KEY)
