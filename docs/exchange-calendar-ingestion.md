# Local NSE/BSE Exchange Calendar Ingestion

## Scope

This is a local-file importer over the existing schema-v3 `exchange_trading_session` table. It performs no network requests and adds no dependencies or schema objects. Each import requires an explicit exchange and calendar version. NSE and BSE rows remain separate.

The supplied source must be a CSV in the explicit-row format below. Its exact original bytes are archived before parsing, checksummed with SHA-256, and registered in `raw_source_file` and `source_document_revision`. PDF and workbook parsing are not implemented; if an official source is published only in those formats, ingestion is blocked until an approved local conversion path exists. Do not replace the original publication with an unarchived transcription. The importer does not infer weekday sessions or fill gaps.

## Calendar CSV format

Required columns:

```csv
exchange,session_date,is_trading_session,session_type
```

`exchange` is exactly `NSE` or `BSE`; dates use ISO `YYYY-MM-DD`; the trading flag is `true` or `false`; `session_type` is `regular`, `special`, or `holiday`. A `holiday` row must be closed. Regular and special rows must be open. Include an explicit row for every date between the first and last imported date. Closed dates, including weekends, use `holiday,false` because schema v3 has no separate weekend-closure type. Unknown or incomplete periods should not be imported as complete calendar coverage.

## Example invocation

```powershell
python scripts/ingest_exchange_calendar.py `
  --exchange NSE `
  --version nse-cm-2026-r1 `
  --source-file C:\data\nse-equity-calendar-2026.csv `
  --source-identifier https://www.nseindia.com/resources/exchange-communication-holidays `
  --source-document-date 2025-12-12 `
  --publication-date 2025-12-12 `
  --parser-version calendar-csv-v1 `
  --database data\processed\hamsa.duckdb `
  --archive-root data\raw\archive\exchange-calendars `
  --authorize-local-retention
```

Supply a `--published-at` timestamp only when the exchange provides a reliable publication time. Otherwise the existing date-only next-trading-session rule applies. Use the exact applicable date and source reference; the example command does not establish that a particular file has been acquired or reviewed.

## Version and retry behavior

- Calendar version is caller-supplied and required; it is not generated from a mutable “latest” alias.
- First import appends all rows in one transaction. Archive/source registration occurs first, so an interrupted parse can leave an archived, registered source with no session rows; retrying is safe.
- Reimporting identical bytes, rows, exchange, and version returns duplicate counts without inserting rows.
- Changing bytes or any session value under an existing version fails closed. Supply a new version for a corrected publication or transcription. Earlier versions remain queryable.
- A repeated date inside one file, malformed values, venue mismatch, invalid status/type combination, or a date gap fails without inserting sessions.

## Point-in-time use

Construct `RepositoryExchangeCalendar(repository, exchange="NSE", version="nse-cm-2026-r1")` (or BSE with its own version) and pass that explicit selector to the existing availability logic. Missing dates do not count as trading sessions. `next_trading_session` refuses to cross a coverage gap. EOD selection and universe eligibility check the selected session’s source document against the requested cutoff and availability mode. Later revisions use a different version and do not modify prior rows or results that selected an earlier version.

## Current source-data blockers

- No official NSE or BSE calendar source file was supplied to this implementation run, so no production calendar rows were loaded.
- NSE publishes official equity-segment holiday information and special-session notices; obtain and archive the applicable original file/circulars, then transcribe all explicit dates needed for the selected coverage.
- The current BSE equity calendar source file is not present in the workspace. Obtain it through BSE’s official published route and use its own source reference and version.
- Schema v3 stores source-document provenance per session but not row-level extraction locators. This importer intentionally keeps the v3 design and does not add calendar review-history infrastructure.
