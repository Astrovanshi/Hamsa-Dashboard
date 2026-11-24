# TejHQ Real-Data Pilot Report

**Outcome:** bounded raw-data intake completed for NSE only. The pilot did not admit any normalized price observations because this database contains no approved identity, listing-status, instrument-class, or platform-class evidence for these rows. BSE was not ingested because the retained Parquet bytes cannot be tied to a verified immutable dataset commit.

## Scope and source files

| Venue / partition | Immutable dataset revision | Dataset path | Local SHA-256 | Selected rows | Result |
|---|---|---|---|---:|---|
| NSE 2026 | `408bab9d85371d333cc18572a428934f4fad0112` | `nse/year=2026/nse_2026.parquet` | `3a51ca886a9b54febf8ecd07042a6728e4adadbc3f55335091a0258ad6335934` | 10 (5 symbols × 2 dates) | Archived; 10 quarantines for unresolved approved ISIN/listing/classification mapping |
| NSE 2010 | `62a4096f74bc79f34be2a9d848e7831b51d9808b` | `nse/year=2010/nse_2010.parquet` | `3508faa6dc007783c61324bdfdab40aa7a224cd895662544d1aa139d0e2e7017` | 2 | Archived; 2 quarantines because source ISIN is NULL |
| BSE 2026 | Exact revision unknown | `bse/year=2026/bse_2026.parquet` | retained bytes: `0427749cc74a40fcdc93a2a0fab1acc9f9a588a5b15ef436408785da5a5739f6` | 0 ingested | Not ingested; retained-byte checksum differs from the currently published file at commit `12ba6b3495817adcd442828519189bdbc610890c` (`875aa3e3…`), and that version does not contain the retained Nov 9 sample |

The NSE 2026 partition has 572,992 rows covering 2026-01-01 through 2026-11-09 in the inspected local file; the 2010 partition has 347,026 rows covering 2010-01-04 through 2010-12-31. Those are partition-level observations, not claims of complete daily or universe coverage. The retained BSE 2026 partition has 526,959 rows over the same displayed date range in the compatibility inspection, but it was not admitted or imported in this pilot.

The 2026 selection was `HDFCBANK`, `INFY`, `NPST`, `SBIN`, and `NIFTYBEES`, on 2026-11-06 and 2026-11-09. The 2010 selection was `SBIN` and `NIFTYBEES` on 2010-01-04. Symbols only selected rows; they did not resolve identity. No company-size classification was applied. NIFTYBEES remains quarantined in the production intake; its ETF identity means it is outside the locked investment universe, but the pilot did not create or approve a classification record.

## Ingestion report

| Count | Initial bounded intake |
|---|---:|
| Accepted normalized EOD observations | 0 |
| Rejected malformed/invalid rows | 0 |
| Quarantined rows | 12 |
| Duplicates | 0 |
| Revised accepted observations | 0 |
| Out of scope | 0 |
| Reconciliation records | 0 |

Quarantine reasons: 10 rows `unresolved_isin_mapping`; 2 rows `missing_or_invalid_isin`. The 10 valid-format 2026 ISINs were not mapped to an approved HAMSA security/listing with approved effective listing status and instrument/platform classifications. The 2010 rows had NULL ISIN; no symbol-based substitute was used.

An exact repeat of the NSE 2026-11-09 selection reported 5 quarantines at attempt level, but the persisted quarantine count remained 12; it created no new quarantine rows, source-document revision, or price observation. The report counts the three unique date selections once, and treats the repeat as an idempotency check rather than additional pilot rows.

Database state after intake: schema version 3; 2 TejHQ source-document revisions; 12 TejHQ quarantine records; 0 TejHQ normalized EOD observations; 0 reconciliation records. Existing raw archive entries are content-addressed under `data/raw/archive/tejhq/<hash-prefix>/<sha256>` and retain source identifiers, original filenames, checksums, dataset revision/path, schema fingerprint, parser version, and actual archive/ingestion timestamps. The local raw Parquet files and database remain ignored by Git.

## Point-in-time and recovery notes

The importer recorded `source_document_date`, first-verified-public date and ingestion timestamp separately. The dataset's first-verified-public date is date-only 2026-11-10, not a proven intraday publication timestamp. Actual ingestion in HAMSA occurred on 2026-11-11 at approximately 02:29 Asia/Kolkata. `hamsa_known_as_of` must use that actual ingestion time; replay/public availability is governed separately. A production exchange calendar version for the relevant cutoffs is not populated, so no historical screen eligibility result is asserted here.

Archive-first flow completed before parser persistence. Reopening the database showed the stored source checksums and immutable archived bytes. Duplicate retry was idempotent for persisted quarantines and observations. No failure-injection was performed during this particular pilot run; transaction and archive-recovery failure modes remain covered by adapter tests.

## Reconciliation against local official EOD files

A separate read-only comparison was run for 2026-11-09 against locally retained official NSE UDiFF ZIP and BSE UDiFF CSV files. For each venue independently, all five selected symbols had matching OHLC, volume and traded value (5/5 exact, zero field mismatches). This compares local source rows only; it did not create database reconciliation records because no normalized HAMSA observations or approved listing mappings existed. The NSE comparison uses the checksum-verified TejHQ NSE partition. The BSE comparison is exploratory only: exact dataset commit membership for the retained TejHQ BSE bytes remains unknown. This sample does not prove broad parity, source licensing, completeness, or eligibility.

No delivery data was imported. The existing adapter is price-only and delivery parity was not established.

## Commands used

These existing commands are bounded to one exchange, one session and no more than ten selected symbols. They do **not** implement a safe full-history backfill. Example from the verified NSE 2026 run:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_tejhq_pilot.py `
  --database data\processed\hamsa.duckdb `
  --archive-root data\raw\archive\tejhq `
  --file data\raw\tejhq-sample\nse\year=2026\nse_2026.parquet `
  --exchange NSE `
  --dataset-id tejhq/indian-markets `
  --dataset-revision 408bab9d85371d333cc18572a428934f4fad0112 `
  --dataset-path nse/year=2026/nse_2026.parquet `
  --source-document-date 2026-11-10 `
  --first-verified-public-date 2026-11-10 `
  --retrieval-date 2026-11-10 `
  --trade-date 2026-11-09 `
  --symbols HDFCBANK,INFY,NPST,SBIN,NIFTYBEES
```

A complete-history command cannot be supplied honestly: the current CLI requires an explicit session and symbol set for each import. The available local samples also do not constitute a verified complete dataset, BSE's retained file revision is unresolved, and no production calendar or approved identity/classification set exists. Do not loop this command over all dates/files until these prerequisites and an explicit backfill scope are resolved.

## Next step: real financial results

The existing CSV ingestion pipeline already archives source files, records source/parser provenance, validates metric names and canonical units, retains missing values as missing, resolves financial subjects via approved ISIN mappings, and appends point-in-time financial revisions. Its quarterly-results input shape is:

`isin,metric,value,unit,period_start,period_end,reporting_scope`

The available examples and tests are synthetic. No real financial filing/result file has been supplied or ingested, and the current database has zero financial observations. The minimum practical next step is a user-supplied official company results CSV or a small, cited extraction from a company filing, with source identifier, checksum, publication date/time precision, period start/end, metric, original value/unit and reporting scope. Any metric/unit mapping or subject mapping must be supported by reviewed evidence. A real-source adapter is needed only if the actual supplied filing format differs from this existing normalized CSV contract; no provider or source was activated here.

## Limitations and next gate

- This was a 12-row NSE archive/quarantine pilot, not a successful observation-admission pilot.
- BSE was not ingested; the retained bytes' immutable revision is unresolved.
- No security/listing/classification approvals were created or inferred.
- No production calendar version is loaded.
- No full historical backfill, delivery import, screening-engine run, dependency change, schema change, or official adapter change occurred.
- Next useful gate is resolving official identity/classification/listing evidence and production calendar data for a small real NSE case; then repeat a bounded admission pilot. Resolve BSE byte-to-revision provenance separately before BSE import.
