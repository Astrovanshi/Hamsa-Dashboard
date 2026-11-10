# Local official EOD ingestion

HAMSA supports manual download followed by offline ingestion. No provider is activated and the script makes no network requests.

## Download files

1. On NSE's official All Reports page, download the dated CM-UDiFF Common Bhavcopy Final ZIP and Full Bhavcopy and Security Deliverable data CSV for the same session.
2. On BSE's official Stock Prices history page, query the same date and instrument, then use Download File. Download the dated BSE equity scrip master separately when available and use it to review the listing mapping.
3. Keep the original files unchanged. HAMSA computes SHA-256 and archives exact bytes under `data/raw/archive/`.

The integration was verified with the locally retained 2026-11-09 NSE and BSE SBI examples described in [the source-selection report](real-data-source-selection.md). Do not describe the example mapping or coverage as a full exchange universe.

## Configure reviewed identity

Copy `configs/real_eod.example.json` to `configs/real_eod.local.json` and edit it. The local file is gitignored. Add one `identity_map` entry per **reviewed ISIN**, pairing a stable issuer ID and security ID. Add a BSE `listing_mapping` from a BSE master or listing lookup; include the effective date and evidence reference. The current example is only the observed SBI mapping. Missing or ambiguous identities are quarantined.

The NSE series allowlist must be explicit. The sample config uses `EQ`, and scopes this first verification run to SBI using an explicit ISIN allowlist; all other rows are counted as out of scope. The NSE delivery CSV has no ISIN, so its sample scope uses an explicit symbol allowlist and still resolves through the effective-dated listing table. Expand both allowlists only after adding reviewed identity mappings. The BSE history CSV has no scrip code, symbol or ISIN, so BSE ingestion stops unless the mapping is present.

## Run

From the repository root, use the project Python environment (DuckDB 2.0.0 is already declared):

```powershell
Copy-Item configs/real_eod.example.json configs/real_eod.local.json
.\.venv\Scripts\python.exe scripts/ingest_official_eod.py `
  --config configs/real_eod.local.json `
  --trade-date 2026-11-09 `
  --nse-udiff data/raw/real/eod/nse/BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv.zip `
  --nse-delivery data/raw/real/eod/nse/sec_bhavdata_full_09112026.csv `
  --bse-prices data/raw/real/eod/bse/bse_sbin_2026-11-09.csv
```

The CLI prints per-file accepted, rejected, out-of-scope, quarantined, duplicate and revised counts. These categories are separate: explicit series/security allowlists increment `out_of_scope`; malformed or invalid records increment `rejected`; unresolved identities increment `quarantined`; repeats after a successful same-parser run increment `duplicates`; corrections increment `revised`. Same bytes plus same parser are idempotent; changed bytes create a source-document revision, while parser versions are stored on extraction records. When the file has no reliable publication timestamp, the CLI records the actual local ingestion date with `published_at=NULL` as a conservative date-only availability bound; it never assumes the historical trade date is the publication date. This can understate earlier public availability, but avoids historical look-ahead until the source provides a reliable publication timestamp. The original source stays archived, and `license_status=pending` records that technical access has not been treated as a license conclusion.

For a clean checkout with the declared dependencies installed, run the portable suite with `python scripts/run_tests.py`. Real-file checks in `tests/test_real_eod_ingestion.py` run only when the ignored files under `data/raw/real/eod/` are present; synthetic parser fixtures always run and do not use exchange files.

## Validation boundaries

Prices, volume, turnover and delivery are preserved per venue. NSE UDiFF supplies exact traded value; NSE's full bhavcopy turnover is rounded in lakh rupees and is not used to replace the UDiFF value. Missing delivery values remain null. In-file identical duplicate rows are rejected; conflicting values for the same listing/session are quarantined together. A repeated successful file/parser is counted as duplicate ingestion and creates no new observations. Malformed ZIP/CSV structure fails that file after raw archival; row-level invalid values and unresolved listing identities are retained in quarantine. The report's accepted count includes both price and delivery observations as separate records. No corporate-action price factors are applied to raw EOD prices.
