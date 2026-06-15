# Bilanca

Osebna finančna aplikacija, ki na podlagi resničnih bančnih transakcij **samodejno**
kategorizira porabo, prikazuje vzorce in **proaktivno opozarja** na stvari, ki jih sicer
spregledamo: pozabljene naročnine, tihe podražitve in mesec, ki bo šel v minus.

## Problem

Ročno vodenje financ je dolgočasno, zato ga skoraj nihče ne počne dosledno. Obstoječe
aplikacije so večinoma generične, tuje in slabo pokrijejo uvoz iz slovenskih bank. Sam
"pregled porabe" pa ne spremeni vedenja — manjka napoved in proaktivno opozarjanje.

## Cilji

- **Razumeti denar brez truda** — transakcije se uvozijo in samodejno kategorizirajo.
- **Videti vzorce, ne le številk** — poraba po kategorijah, mesečni trendi, primerjava skozi čas.
- **Najti skrite stroške** — zaznava ponavljajočih bremenitev (naročnin), opozorila na pozabljene
  in podražene.

## Tehnologija

- Python 3.11+, FastAPI, SQLModel nad SQLite
- Jinja2 + HTMX + Chart.js za vmesnik
- Zneski shranjeni v centih (celo število) zaradi finančne pravilnosti

## Arhitektura

Cevovod za zajem s **pluggable viri**: ročni uvoz CSV je prva implementacija, kasnejša
avtomatska PSD2 povezava se priklopi v isti cevovod.

```
Vir: CSV upload (MVP)   ─┐
Vir: PSD2 API (kasneje) ─┼─→ Normalizator → Dedup → Kategorizator → SQLite → Vpogledi
                         ┘
```

## Razvoj

```bash
# Namestitev (uv)
python -m uv venv
python -m uv pip install -e ".[dev]"

# Zagon
python -m uvicorn bilanca.main:app --reload
# → http://127.0.0.1:8000

# Testi
python -m pytest
```

Banka v MVP: **NKBM / OTP (Bank@Net)**. Drugi viri in banke pridejo kasneje.
