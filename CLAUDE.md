# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow

- After completing each meaningful chunk of work (a feature, fix, or milestone), commit it
  to git with a short descriptive message and push to `origin master`. Don't batch up many
  unrelated changes into one commit — commit as you go so the history shows what happened.

## Project

Bilanca is a personal finance app: import real bank transactions, auto-categorize spending,
show trends, and proactively flag things people miss (forgotten subscriptions, silent price
hikes, a month heading into the red). MVP targets a single Slovenian bank (NKBM/OTP) with
manual CSV import; the architecture is designed so automatic PSD2 import can be added later
as just another source.

## Commands

```bash
# Install deps (uv has a TLS issue on this machine without --system-certs, and must be
# pointed at .venv explicitly or it installs into the global Python instead)
python -m uv pip install --system-certs --python .venv/Scripts/python.exe -e ".[dev]"

# Run the app
python -m uvicorn bilanca.main:app --reload   # http://127.0.0.1:8000

# Run tests
python -m pytest -q

# Run a single test file / test
python -m pytest tests/test_recurring.py -q
python -m pytest tests/test_recurring.py::test_detect_silent_price_hike -q
```

The SQLite DB lives at `data/bilanca.db` (gitignored). Delete it to reset local state —
`init_db()` recreates tables and reseeds categories/rules on next app startup.

## Architecture

### Ingest pipeline (source-agnostic by design)

```
Source (NkbmCsvSource, ...) → NormalizedTxn → dedup hashing → Transaction rows → auto-categorize
```

- `bilanca/ingest/base.py` — `TransactionSource` protocol and `NormalizedTxn` dataclass.
  Any new source (e.g. a future PSD2/GoCardless source) just needs to implement `fetch()`
  returning `NormalizedTxn` objects; everything downstream is unchanged.
- `bilanca/ingest/profiles/nkbm.py` — NKBM/OTP Bank@Net CSV parser. Key gotchas: file is
  **cp1250**-encoded (decoded via `decode_bytes`, tries utf-8 variants then cp1250),
  `;`-delimited, amounts use Slovenian decimal commas (`parse_amount`), and a single
  transaction's amount lives in either the DOBRO (credit, positive) or BREME (debit,
  negative) column — never both.
- `bilanca/ingest/dedup.py` — NKBM exports have no unique transaction ID, but genuine
  duplicates exist (e.g. two identical cash withdrawals same day). `assign_hashes` builds a
  content-based key per transaction and appends an `occurrence` counter for repeats within
  the same import, so re-importing an overlapping date range skips already-stored rows
  while still allowing genuine same-day duplicates.
- `bilanca/ingest/importer.py` — `import_source()` orchestrates: fetch → hash/dedup →
  insert new `Transaction` rows → record an `ImportBatch` → run `apply_rules()` on newly
  inserted, uncategorized transactions.

### Data model (`bilanca/models.py`)

All monetary amounts are stored as **integer cents** (`amount_cents`), signed: negative =
expense, positive = income. Never use floats for money. Key tables: `Account`, `Category`
(hierarchical via `parent_id`, has a `kind`: expense/income/transfer), `Rule`, `Transaction`
(has `dedup_hash` unique constraint, `category_locked` flag), `ImportBatch`.

### Categorization (`bilanca/categorize/`)

- `defaults.py` — seeded system rules (`DEFAULT_RULES`) matching real Slovenian merchant
  strings (Mercator, Spar, Hofer, Petrol, Telemach, etc.) to category names. Seeded once via
  `seed_rules()`, called from `init_db()`.
- `rules.py` — `apply_rules()` runs rules ordered by `priority` desc (first match wins),
  skipping transactions where `category_locked=True`. `set_category()` is the manual
  override path: locks the transaction, and optionally (`create_rule=True`) learns a new
  USER-sourced rule from the counterparty name (priority `USER_RULE_PRIORITY=500`, so
  learned rules always outrank system defaults) and immediately re-applies it to other
  matching, unlocked transactions.

### Insights (`bilanca/insights/`)

- `trends.py` — spending-by-category and monthly income/expense aggregates for the
  dashboard charts.
- `recurring.py` — subscription/recurring-charge detection. Groups expenses by
  `(normalized merchant, exact amount)`, infers a period from the median gap between dates
  (only **monthly** and **yearly** periods are considered — weekly habitual purchases like
  lunch are deliberately excluded to avoid false positives), and flags a subscription
  inactive if too long has passed since `last_date`. Also detects "silent price hikes":
  same merchant, a later series at a higher amount starting after the earlier series ends.
  Detection accuracy improves with more months of history — with only ~2 months, the
  `min_occurrences=2` threshold can produce false positives.

### Web (`bilanca/web/`)

FastAPI routes in `routes.py` render Jinja2 templates (`web/templates/`) styled via
`web/static/style.css`, with Chart.js for the dashboard charts and a plain HTML5
drag-and-drop file input for CSV upload (no JS framework/build step).

## Testing conventions

`tests/conftest.py` provides `nkbm_csv_bytes` — a synthetic cp1250-encoded NKBM CSV fixture
(not a real export; real exports contain personal data and must never be committed). It
deliberately includes Slovenian characters, trailing-space-padded descriptions, a genuine
same-day duplicate pair, and a blank row, to exercise the parser/dedup edge cases.
