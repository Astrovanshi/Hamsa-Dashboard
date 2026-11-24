# HAMSA

HAMSA is a local, end-of-day Indian equity investment research workspace. It preserves NSE and BSE listings separately, keys security identity by reviewed ISIN mappings, and admits only officially evidenced mainboard ordinary equity. It produces research flags, never automatic buy/sell recommendations.

## Run locally

Use Python 3.11 and the declared project dependencies. In an environment where the already-declared Streamlit dependency is available:

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The app creates its local analytical DuckDB at `data/processed/hamsa.duckdb` and human-review SQLite ledger at `data/processed/hamsa_reviews.sqlite3`. Both paths can be changed with `HAMSA_DUCKDB_PATH` and `HAMSA_REVIEW_DB_PATH`. Raw input and database files are ignored by Git.

Copy `configs/screening.example.json` to the ignored `configs/screening.local.json` to map source financial metric codes and configure local thresholds. The numerical liquidity thresholds are deliberately unset: HAMSA does not define “unusual” by an unapproved default. Financial-sector screens are also blocked until a separate approved profile exists.

## Data operation

Data access is local-file-only. No exchange endpoint is called by the app. The supported official EOD and calendar command examples are in [docs/real-eod-ingestion.md](docs/real-eod-ingestion.md) and [docs/exchange-calendar-ingestion.md](docs/exchange-calendar-ingestion.md). A selected EOD file remains quarantined or unresolved until its identity and classification evidence is reviewed. TejHQ remains a bounded secondary pilot; no bulk backfill is run.

Run the portable suite with:

```powershell
.\.venv\Scripts\python.exe scripts\run_tests.py
```

## Current data limitations

This workspace currently has one-session NSE/BSE SBI EOD examples and retained source samples, but no production exchange calendar versions, no approved complete current mainboard universe, and no normalized financial history. NSE ordinary-equity classification and BSE current mainboard/ordinary-equity evidence remain unresolved. In that state the app shows data and blockers but runs no discovery engine against unqualified securities.

The product architecture and current milestone status are maintained in [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) and [docs/MILESTONE_TRACKER.md](docs/MILESTONE_TRACKER.md).
