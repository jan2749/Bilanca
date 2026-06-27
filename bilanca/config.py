"""Nastavitve aplikacije in poti."""

from __future__ import annotations

import os
from pathlib import Path

# Korenska mapa projekta (kjer je pyproject.toml).
BASE_DIR = Path(__file__).resolve().parent.parent

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
