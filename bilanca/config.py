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

# ---------------------------------------------------------------- Enable Banking (PSD2)
# Poverilnice agregatorja Enable Banking. Pridobiš jih brezplačno (tudi kot posameznik prek
# "Restricted Mode") na https://enablebanking.com → Control Panel → registracija aplikacije:
# dobiš Application ID (kid) in zasebni ključ (.pem), ki ga shraniš lokalno.
ENABLE_BANKING_APP_ID = os.environ.get("ENABLE_BANKING_APP_ID", "").strip()
# Pot do zasebnega ključa; privzeto datoteka v korenu projekta (ni v gitu).
ENABLE_BANKING_KEY_PATH = os.environ.get(
    "ENABLE_BANKING_KEY_PATH", str(BASE_DIR / "enablebanking_private.pem")
).strip()
ENABLE_BANKING_BASE_URL = os.environ.get(
    "ENABLE_BANKING_BASE_URL", "https://api.enablebanking.com"
).rstrip("/")
# Privzeta država za seznam bank.
ENABLE_BANKING_COUNTRY = os.environ.get("ENABLE_BANKING_COUNTRY", "SI").strip().upper()


def enablebanking_configured() -> bool:
    """True, če sta nastavljena Application ID in obstoječ zasebni ključ (sicer je povezava skrita)."""
    return bool(ENABLE_BANKING_APP_ID and ENABLE_BANKING_KEY_PATH and Path(ENABLE_BANKING_KEY_PATH).is_file())
