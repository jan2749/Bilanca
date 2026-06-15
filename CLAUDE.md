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
- `bilanca/ingest/importer.py` — `import_source(session, source, user, filename)` orchestrates:
  fetch → hash/dedup → insert new `Transaction` rows (into the user's account) → record an
  `ImportBatch` → run `apply_rules()` on the user's newly inserted, uncategorized transactions.

### Users / auth (`bilanca/auth.py`)

The app is multi-user. `User` + `UserSession` (random token in an httponly `bilanca_session`
cookie) back login/registration; passwords use stdlib `pbkdf2_hmac` (no external deps).
`get_current_user` is a FastAPI dependency that raises `AuthRedirect` (handled in `main.py`
→ redirect to `/login`) when not signed in. **All data is scoped per user**: `Account` and
`ImportBatch` carry `user_id`; transactions are reached via the user's accounts. `Category`
and `Rule` have a **nullable** `user_id` — `NULL` means a shared system row (seeded defaults),
non-null means a user's own category/learned rule.

### Data model (`bilanca/models.py`)

All monetary amounts are stored as **integer cents** (`amount_cents`), signed: negative =
expense, positive = income. Never use floats for money. Key tables: `User`, `UserSession`,
`Account` (per-user), `Category` (hierarchical via `parent_id`, `kind`: expense/income/transfer),
`Rule`, `Transaction`, `ImportBatch`. `dedup_hash` is **not** globally unique — uniqueness is
the composite `(account_id, dedup_hash)`, so two users can hold the same transaction.

### Categorization (`bilanca/categorize/`)

- `defaults.py` — seeded system rules (`DEFAULT_RULES`) matching real Slovenian merchant
  strings (Mercator, Spar, Hofer, Petrol, Telemach, etc.) to category names. Seeded once via
  `seed_rules()`, called from `init_db()`.
- `rules.py` — `apply_rules(session, user, ...)` runs system + that user's rules ordered by
  `priority` desc (first match wins), only over the user's transactions, skipping
  `category_locked=True`. `set_category(session, user, txn_id, ...)` is the manual override
  path: verifies ownership, locks the transaction, and optionally (`create_rule=True`) learns
  a USER-sourced rule (tagged with `user_id`, priority `USER_RULE_PRIORITY=500`) from the
  counterparty name and re-applies it to the user's other matching, unlocked transactions.
- `suggest.py` — `uncategorized_groups()` powers the post-import "razvrsti zdaj" screen:
  groups the user's uncategorized expenses by normalized merchant (descending by total spend);
  assigning one representative via `set_category(create_rule=True)` clears the whole group.

### Insights (`bilanca/insights/`)

- `trends.py` — `spending_by_category()` / `monthly_summary()` take `user_id` and an optional
  `date_from`/`date_to` window (the dashboard's from–to filter).
- `recurring.py` — subscription detection. **Currently hidden from the UI** (unreliable with
  little history); the code and tests remain for a future rework. Groups expenses by
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
drag-and-drop file input for CSV upload (no JS framework/build step). All pages except
`/login` and `/register` require a signed-in user (`Depends(get_current_user)`).

## Testing conventions

`tests/conftest.py` provides `nkbm_csv_bytes` — a synthetic cp1250-encoded NKBM CSV fixture
(not a real export; real exports contain personal data and must never be committed). It
deliberately includes Slovenian characters, trailing-space-padded descriptions, a genuine
same-day duplicate pair, and a blank row, to exercise the parser/dedup edge cases.
`conftest.py` also exposes `make_user(session)` — most tests now need a `User` because
`import_source`, `apply_rules`/`set_category`, and the trends aggregates are all user-scoped.
