# NSE Mainboard Master Intake — Local Reconciliation Report

**Run date:** 2026-11-11 (Asia/Kolkata)
**Database schema:** v3
**Parser:** `nse-mii-master-v2`
**Decision:** intake is technically complete; no instrument is admitted to the investment universe.

## Source files and provenance

The files were supplied locally by the user. Their official origin and publication time were not independently authenticated. The filename follows NSE's documented daily MII naming pattern, but the date in the name remains a claimed source/snapshot date. NSE's circular describes daily website dissemination of `NSE_CM_security_ddmmyyyy.csv.gz`; it does not verify these particular bytes or their receipt time. The official specification and circular are cited in [the source qualification report](nse-cm-master-qualification.md).

| Input | Size | SHA-256 | Parsed | Archived filename | Source document revision |
|---|---:|---|---:|---|---:|
| `NSE_CM_security_09112026 (1).csv.gz` | 1,282,023 bytes | `99cd4f092d1f14a749ba3cb7a98c1bedb5d9d4c74b9bd71bc3b3a0c1baf75c28` | 38,415 rows × 120 columns | Preserved exactly | 1 |
| `NSE_CM_security_09112026 (2).csv.gz` | 1,567,217 bytes | `f8232a07a9a815bda8873fa9b179278030b7ace85acf07f42a90aacdc6be48c8` | 48,056 rows × 120 columns | Preserved exactly | 2 |
| `EQUITY_L.csv` | 186,852 bytes | `2c05ea3dbe51b6b727b8dce4973cee9fc2a0064bd1ac869328c825e5acece75e` | 2,645 rows × 8 columns | Preserved exactly as cross-check | Raw-file record only; no publication date assigned |

All original files were copied to the checksum-addressed raw archive before parsing. Their original filenames, SHA-256 values, local capture/ingestion timestamps, source identifiers, parser versions, and row extraction locations are retained. The CM source document uses `publication_date=2026-11-11` only as a conservative date-only local capture bound because no reliable publication timestamp was supplied; `published_at` is NULL. The `09112026` filename token is stored separately as the claimed source/snapshot date. The EQUITY_L file is recorded as a user-supplied cross-check with no invented publication metadata.

## Reconciliation counts

Counts below are for one complete extraction under parser v2. The row categories are mutually exclusive. `accepted` means a listing-classification snapshot was persisted against an existing reviewed listing/ISIN identity; it does not mean that a security passed HAMSA eligibility. `quarantined` is the number of new row-level quarantine records written for that parser version. `duplicate` is a retry/no-op count and does not represent another source row. `revised` is reported separately at file/source revision level.

| File | Parsed rows | Accepted snapshot | Unresolved identity | Conflicting | Deleted flag | Out of scope | Rejected malformed | New quarantine rows | Duplicate rows on first v2 extraction |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CM file (1) | 38,415 | 0 | 2,087 | 0 | 9,699 | 26,629 | 0 | 38,415 | 0 |
| CM file (2) | 48,056 | 0 | 2,087 | 0 | 9,699 | 36,270 | 0 | 48,056 | 0 |
| **Total row occurrences** | **86,471** | **0** | **4,174** | **0** | **19,398** | **62,899** | **0** | **86,471** | **0** |

Out-of-scope breakdown:

| Reason | File (1) | File (2) |
|---|---:|---:|
| `PrtdToTrad=0` — documented analogous legacy “listed, not permitted to trade” flag; retained as source fact | 26,570 | 26,570 |
| Normal-market status `3` — documented analogous legacy “suspended” flag; retained as source fact | 36 | 36 |
| `TckrSymb` ending `NSETEST` — NSE specification's documented dummy/test marker | 23 | 23 |
| `PrtdToTrad=2` — documented analogous legacy BSE-listed/exclusive flag, pending current MII crosswalk | 0 | 9,641 |

Deleted rows are classified first by `DelFlg=Y` and are not double-counted under other status flags. The unresolved total consists of 2,055 valid-ISIN rows without exactly one existing exchange-instrument/listing mapping and 32 missing/invalid-ISIN rows per file. No mapping, identity, instrument class, platform class, listing effective date, or review approval was created from these files.

An identical completed import with the same source bytes and parser version is an idempotent no-op: it reports those input rows as duplicates and writes no additional quarantine observations. Parser v1 quarantine records remain preserved; parser v2 created a separate extraction revision with improved status categorization. These parser-version records are historical extraction results, not new source-file revisions.

Across both source-document revisions, the database retains **172,942 quarantine extraction records**: one full extraction per file under parser v1 and another under parser v2. This is deliberately larger than the 86,471 source row occurrences because both parser revisions are preserved. File (2) also has one interrupted parser-v1 processing attempt left with status `started`; a subsequent v1 attempt and the v2 attempt completed successfully. The interrupted attempt added no partial classification snapshots, and its source/quarantine records are retained rather than rewritten. This stale operational status is a known cleanup limitation; it does not change the row-level outcomes above.

## Cross-file comparison

The two CM files were compared by `FinInstrmId` (only as a within-file record key):

| Result | Count |
|---|---:|
| Common IDs | 38,415 |
| Added in file (2) | 9,641 |
| Removed | 0 |
| Changed common records | 3,296 |
| Changed field | `UpdDt` only |

The 9,641 rows added by file (2) have `PrtdToTrad=2`. They are retained as NSE-file source records but conservatively quarantined from NSE listing identity intake; they are not treated as BSE listing records or merged into another venue's listing identity.

`EQUITY_L.csv` contains 2,645 rows and 2,645 unique valid ISINs. Every one of those ISINs appears in CM file (2), and the symbol matches the CM candidate symbol for all 2,645. This is a useful NSE-file consistency check only. It does not independently establish publication date, completeness, instrument class, platform, active listing status, or mainboard eligibility.

## Timestamp interpretation

The previous qualification report's Unix-epoch interpretation of `UpdDt` was incorrect and has been corrected. The NSE Master Data Specification v1.6 documents an epoch of 1 January 1980 for analogous legacy master time/date values and defines `Local DB Update Date Time` as a per-record local database update time. Under that documented clock convention, the observed maximum `UpdDt` values are:

- File (1): `2026-11-09 18:50:42`.
- File (2): `2026-11-09 20:31:29`.

These are consistent with the filename's claimed date, but are record-update clocks, not file publication dates. A complete MII tag-to-legacy-field crosswalk and a source receipt/publication timestamp are still unavailable. Gzip MTIME is zero.

`ListgDt` values decode under the 1980 epoch from `1995-02-08` through `2026-11-11`, with 616 zero sentinels; 18 positive values fall after the filename's claimed `2026-11-09` date. This is an observed data condition, not proof that the file date is false, because the MII date-field crosswalk and file publication timestamp remain incomplete. These values remain source fields rather than approved effective listing revisions. A current file date, record update time, or observed listing-date field does not by itself establish a reviewed historical listing interval.

## What was persisted and what was not

- Schema remained v3; no migration was applied.
- Exact source bytes and provenance were retained in the raw archive and `raw_source_file` / `source_document_revision` records.
- The parser preserved all 120 source fields and CSV line locators in row-level quarantines.
- Both source revisions and parser-v1/parser-v2 extraction histories remain available.
- The existing local DuckDB was augmented non-destructively. No existing normalized observation was overwritten.
- The database contained no approved NSE listing/ISIN mappings before intake. Therefore the number of accepted listing-classification snapshots is zero, and no security was admitted.
- The NSE MII series, raw numeric codes, symbol/name, and EQUITY_L match were not used to infer mainboard or ordinary-equity status.

## BSE parser: exact next input needed

The existing `parse_bse_published_scrip_master()` in `src/hamsa/ingestion/exchange_master.py` is strict and has not been run against a current BSE SCRIP master. It accepts either a local CSV/TXT or a ZIP containing exactly one CSV/TXT member. The header must contain these exact published-format labels:

```text
Scrip Code
ISIN CODE
Instrument Code
Scrip Name
Security Type Flag
Instrument status flag
Instrument Type
```

The parser preserves the BSE scrip code as the exchange instrument identifier, ISIN as a candidate security identity, `Instrument Code` as a candidate symbol, and `Instrument status flag` as raw listing-status text. It does not derive BSE series, platform, ordinary-equity type, or effective dates.

To proceed with BSE ingestion, the missing inputs are:

1. The actual current official `SCRIP.ZIP` (or current officially supplied equivalent) obtained through the documented BSE Members Help Desk/official route, provided locally with its original filename and any accompanying receipt/date.
2. The current file's official field specification/codebook, especially definitions for `Security Type Flag`, `Instrument status flag`, `Instrument Type`, group/platform, and any mainboard/SME or ordinary-equity distinction.
3. Authoritative effective-date evidence for listing, suspension, delisting/relisting, and any SME-to-mainboard migration where relevant.

Do not assume the current file matches the documented 2022 CSV format. Supply the file first; the parser must be checked against its actual archive member, headers, encodings, row shape, and code meanings before BSE records can be ingested or classified. `EQUITY_L.csv` is an NSE cross-check and cannot substitute for the BSE master.

## Outcome

The NSE intake path is verified for archive-first ingestion, parser-v2 reconciliation, row-level preservation, source/parser revision history, and idempotent retries. It has not produced an approved current mainboard universe. The next practical step is evidence review of NSE instrument/platform/listing classifications and receipt of the current BSE master plus its current codebook—not broader backfill.
