# Historical EOD backfill plan

**Status:** proposed operational plan only. No bulk download or implementation in this milestone.

## Locked universe and separation from current ingestion

Historical point-in-time eligibility is restricted to ordinary equity shares confirmed on the NSE or BSE mainboard for the effective period. SME/Emerge, ETFs, mutual funds, REITs, InvITs, preference shares, warrants, rights instruments, debt, and all other non-ordinary-equity instruments are excluded from HAMSA's eligible universe. They may be counted as reconciliation-only exclusions; ambiguous platform/instrument classifications are quarantined. Use official classification and status, not company size or market capitalization.

For SME-to-mainboard migrations, keep the earlier SME listing and its history separately excluded. Admit the mainboard listing only from its verified effective migration/listing date, with source provenance. Never backdate eligibility. Record source snapshot date independently from effective listing date.

This is a separate workstream from the current-universe path. Current mainboard master ingestion, current identity resolution, current EOD ingestion, and current reconciliation can be delivered without waiting for historical masters or EOD backfill. The preconditions below apply only to historical batches.

## Preconditions

Before a historical batch is authorized:

1. The mainboard-only ordinary-equity scope is locked. For historical measurement, define the treatment of inactive periods (suspended, delisted, relisted) and confirm which official series/platform fields distinguish mainboard ordinary shares from excluded instruments.
2. Obtain tiny, published or user-provided source samples from recent, middle and oldest discoverable dates for each exchange/report. Record page/source identifier, requested and actual date, exact byte count, checksum, header, row count and observed field definitions.
3. Confirm source coverage limits and history start by report; do not infer the start of one report from another. BSE needs an established route for a full security set, not just a per-scrip export.
4. Load and reconcile official exchange calendars, including holidays and special sessions, sufficient for the claimed measurement range. Preserve calendar revisions.
5. Review the identity candidate rules and unresolved mappings before prices are admitted to normalized observations.

## Proposed stages

### A. Source catalog and scope ledger

Create a human-reviewed manifest of each acquired source file: exchange, dataset/report, source identifier, report date/session, trade date if distinct, original filename, checksum, byte size, source page/reference, retrieval timestamp, publication timestamp/precision if reliable, and coverage scope. Mark each report format/parser version. No generated URL patterns or undocumented endpoints are used; acquisition remains through documented pages or user-supplied files.

### B. Dated master snapshots, then history reconstruction

Ingest every obtainable NSE/BSE master snapshot as its own raw document and extracted snapshot, without treating the newest file as the historical truth. Measure fields, record counts and active/inactive state coverage. Compare adjacent snapshots to propose identifier, symbol, code, series and status changes. Automatic diff output is only a review queue: it cannot create approved mappings for ambiguous changes. Use dated notices, filings and corporate-action records to support effective intervals. Keep unknown bounds unknown and quarantine collisions.

If there is no official historical master sequence for a period, mark the interval as unresolved. Historical EOD rows can still be archived, but cannot enter a security-level history until a reviewed listing mapping and eligible mainboard classification exist for that effective date. Do not infer old listings solely from current securities, names, ticker suffixes, market capitalization, or later annual reports. For an SME migration, preserve the SME listing separately and start mainboard eligibility only at the verified migration/listing effective date.

### C. Bounded historical file backfill

After coverage and size are reported, process source files in bounded date batches (initially one month per exchange/report, then expand after reconciliation). For each original file:

1. Copy exact bytes into immutable raw archive and verify SHA-256 before parse.
2. Parse into a versioned extraction preserving original row/column locator and original values/units.
3. Validate headers, expected dates, record structure, numeric ranges, duplicate keys, row counts and source-specific definitions.
4. Resolve each row through venue listing + effective-dated identity policy. Out-of-scope is distinct from invalid/rejected; unresolved/ambiguous identity is quarantined with source location.
5. Persist accepted observations and provenance in a file-level transaction. A failed batch is retriable; already archived files are discoverable and reconcile by checksum/source identity.
6. Emit a reconciliation report comparing archive files, extracted row totals, accepted/rejected/quarantined/duplicate/revised/out-of-scope records, excluded SME/non-equity counts, listing mapping coverage and expected trading sessions.

Rows from NSE and BSE remain separate. A same-day same-security observation pair is not a duplicate. Venue prices are never averaged; combined traded value/volume is a later derived calculation only when both rows meet explicit validity/comparability rules. Delivery stays venue-specific.

### D. Corrections and parser changes

Same source identifier + identical bytes + same parser version is idempotent. Same identifier with changed bytes creates a new source-document revision and preserves the previous file and observations. Reparse of identical bytes with a new parser creates a new extraction/parser revision, not a false source revision. Supersession/correction is append-only with lineage. Parser outputs must be reproducible from the archived bytes and recorded parser version.

### E. Daily incremental operation

Initially the operator downloads dated official reports and masters manually from published pages and runs local ingestion. Record actual ingestion timestamp; do not backdate it. If the official source provides a reliable publication timestamp, use the point-in-time rules; otherwise retain conservative date-only/unknown availability. A subsequent approved step may add automated retrieval only through an officially documented and permitted route. Retry/recovery should scan raw files with no completed database processing record and reconcile them by checksum.

### F. Gap detection and reconciliation

Use the versioned exchange calendar as expected sessions. For each listing interval and EOD dataset, calculate expected vs observed dates, but report reasons separately: not listed yet, listing suspended/delisted, source report unavailable, source row absent, unresolved identity, out of scope, ingestion failure, or exchange non-session. A missing row is not a zero-price/zero-volume observation. Compare report date and trade date and validate on special sessions.

Compare at least:

- Source file count/checksum and archive manifest.
- Extracted rows against CSV/ZIP record counts.
- Source-specific OHLCV/turnover/delivery fields and units.
- Cross-file same-exchange/date instruments and duplicates/conflicts.
- Dated master membership against mapped listing rows.
- NSE/BSE overlapping ISIN pairs while preserving their distinct prices and volumes.
- Raw price jumps around corporate actions; do not adjust until event, terms and method are reviewed.

## Operational sizing and complexity

No bulk archive sizes, full-universe row totals or historical field coverage have been measured, so a storage commitment or completion date would be invented. The local 2026-11-09 examples are small-date samples only: NSE UDiFF 3,704 rows (2,743 EQ); NSE full/delivery 3,551 rows; one BSE per-scrip file with one date. They establish parser shape and a single mapping, not universe size.

Use these sizing formulas after measuring actual official files:

`raw_bytes = sum(original file byte sizes)`

`venue_observations = sum(accepted listing-session rows per venue)`

`normalized_storage ≈ observation_count × measured bytes/row + indexes + revisions + lineage`

Measure DuckDB bytes/row on a representative, privacy-safe local copy before projecting. Run a one-month pilot with actual raw size, row count, mapping/quarantine rate and runtime. Extrapolate only within the same product/era, with the assumptions reported. Revisions and raw archive retention can exceed a single normalized snapshot because all source vintages are retained.

Complexity is **high** for point-in-time completeness: bulk file acquisition, two venue-specific master histories, identity review, calendar/session accounting, changing formats, historical inactive securities, corrected reports and corporate actions. Parser runtime is likely a smaller concern than identifying the correct historical listing and verifying coverage. A manual BSE per-security route does not scale to an all-security multiyear backfill unless a bulk route is confirmed.

## Batch acceptance gates

A date batch is accepted only when:

- Every source file has a checksum, source identifier, source date, actual ingestion time and parser/extraction version.
- The same input replays idempotently; a changed source file creates a preserved revision.
- All parsed rows reconcile to explicit outcome categories, including quarantine and out-of-scope.
- No accepted row has an ambiguous or unapproved listing mapping.
- Expected source session is established from the versioned calendar; absence is reported rather than filled.
- Sample rows reconcile exactly to the original raw file and venue-specific source units.
- Any factor-adjusted series is separately versioned and not used in historical screening before public availability.
