# Full-universe implementation plan

**Purpose:** turn the verified single-security official EOD path into measured, reviewable NSE/BSE coverage. This is a planning document; the implementation is not authorized by this milestone.

## Locked universe and workstream boundary

The HAMSA investment universe is exclusively ordinary equity shares officially classified and confirmed as listed on the NSE or BSE mainboard. One ISIN resolves to one security across venues, with separate NSE and BSE listing identities. Excluded are NSE Emerge, BSE SME, all other SME-platform listings, ETFs, mutual funds, REITs, InvITs, preference shares, warrants, rights instruments, debt securities, and every other non-ordinary-equity instrument. Eligibility is determined using official exchange classification and listing status, never company size or market capitalization. Excluded SME/non-equity rows may be recorded for reconciliation only and must never enter the eligible universe or discovery engines. Ambiguous classifications are quarantined.

For an SME-to-mainboard migration, preserve the earlier SME listing and history separately. The mainboard listing becomes eligible only from the verified effective migration/listing date. Keep source snapshot date separate from effective date and never backdate eligibility.

Current-universe ingestion is its own deliverable and does not depend on historical master reconstruction or historical EOD backfill. The same eligibility rule applies to both workstreams; only the evidence depth differs.

## Current baseline

The committed local-file adapter is in `scripts/ingest_official_eod.py`; DuckDB schema and point-in-time/revision rules are in `sql/duckdb_schema.sql` and [data-model.md](data-model.md). The current demonstrated identity is SBI: one canonical security, separate NSE/BSE listings, venue-specific prices and delivery. The inspected NSE UDiFF has ISIN/symbol/series/instrument ID; the BSE per-scrip CSV has no code/symbol/ISIN and requires an explicit listing map. Raw archives, checksums, provenance, idempotency, parser revisions and quarantine exist. Existing pilot scope/allowlist configuration is deliberately narrower than the exchange universe.

No schema extension is proposed until a concrete requirement fails against the existing model. A full-universe project should first extend provider/parser configuration and repository workflows, not redesign the identity tables.

## Implementation sequence and dependencies

| Step | Work | Dependency / exit evidence |
|---|---|---|
| 0. Current-source check | Verify actual current NSE and BSE master/EOD files and official fields/codes for mainboard classification, ordinary-share instrument class and active listing status. Obtain small current samples only; resolve whether BSE has a usable all-security current EOD route. | Current-source manifest with headers, row counts and file sizes. No historical samples or bulk data are prerequisites. |
| 1. Current master ingestion | Parse and archive current dated masters with source snapshot date, checksum, parser/extraction provenance and explicit per-row outcomes. Excluded SME/non-equity rows are reconciliation-only; ambiguous classifications are quarantined. | Actual input rows reconcile to accepted, excluded, duplicate, rejected and quarantined counts. No assertion that snapshot date is listing effective-from date. |
| 2. Current identity resolution | Resolve each eligible mainboard ordinary share by ISIN to one security and separate venue listings. Preserve exchange-specific instrument IDs. Apply only source-supported current validity; require reviewed identity decisions and quarantine ambiguous mappings. | Every admitted current listing maps uniquely; dual listings deduplicate by ISIN; no name/size/market-cap inference. |
| 3. Current full-universe EOD ingestion | Ingest current NSE/BSE EOD files, preserving venue-specific data and existing raw archive/revision/idempotency behavior. | Real-file samples for each current source shape reconcile exactly; BSE work does not assume per-scrip data is an all-security feed. |
| 4. Current coverage and reconciliation report | Report security-master coverage, mappings, excluded rows, EOD row/session gaps, duplicates/conflicts, provenance and unresolved identities by venue and scope. | All input rows and all in-scope master listings accounted for; unresolved and missing EOD are visible. Owner approves any operational tolerance before calling coverage complete. |
| 5. Historical master reconstruction | Separately assemble dated master snapshots/notices and reconstruct effective-dated mainboard eligibility. Preserve SME history separately and begin eligibility only on verified mainboard migration/listing date. | Each claimed historical interval has source evidence; unresolved intervals remain explicit. Does not block steps 0–4. |
| 6. Historical EOD backfill | Backfill only within verified source bounds and effective-dated identity coverage; use bounded batches and append-only revisions. | Historical batch gates in [historical-backfill-plan.md](historical-backfill-plan.md); incomplete periods permitted and reported. |
| 7. Historical point-in-time validation | Validate public-as-of/HAMSA-known-as-of membership, publication cutoff, ingestion time, calendar, corporate-action availability and survivorship controls independently from current coverage. | Historical snapshots reproduce eligible mainboard universe as-of each cutoff; gaps and exceptions remain measurable. |

## Existing schema/repository fit and possible gaps

The existing schema already separates issuer, security and venue listing; stores ISIN and listing revisions with source provenance; and represents active/suspended/delisted/relisted status plus explicit reviewed issuer/security relationships. Reuse these structures where they preserve the required meaning.

Two implementation checks remain before current master persistence:

- `exchange_listing_revision` stores series and status but has no explicit normalized mainboard/SME platform classification or ordinary-share instrument-class field. If the official master classifications cannot be represented losslessly in existing fields and source metadata, propose a listing-level classification field or sourced eligibility record for review. Eligibility must be repository-enforced from official classification/status; downstream consumers must not infer it from ISIN or series name alone.
- `exchange_listing_revision.effective_from` is required, while a current master may provide only a snapshot date. Preserve the snapshot date through the linked source document. Do not claim it is the effective listing date. For current-only processing, limit the mapping's safe applicability to what the snapshot proves; historical effective intervals require separately sourced dates. Listing revision review state is not an explicit schema column today; preserve any manual identity approval in an auditable repository record, or propose a schema change if that is insufficient.

No schema or repository change is authorized by this plan. Validate these cases against actual current master formats first, then request approval for only the gap that cannot be represented safely.

## Measurable coverage gates

At every release, report the metrics below by exchange, report type, date range and security class:

| Metric | Definition |
|---|---|
| Unique issuer entities / securities / listings | Separate counts; do not call all three “companies.” Include mapping-review state. |
| Venue listing coverage | For current work: count of approved current active mainboard ordinary-share listings per venue divided by in-scope records in the dated official master; label denominator unavailable if source completeness is unproven. For historical work: separately report active/suspended/delisted/relisted/unknown per effective date. |
| Dual-listed securities | Count of approved same-security NSE+BSE listing pairs effective on the date; list unresolved candidate pairs separately. |
| ISIN completeness | Approved applicable ISIN mappings divided by all in-scope listing records; report missing/conflict/pending separately. |
| Session coverage | Observed valid listing-session observations divided by expected listing sessions under the named exchange calendar and listing interval. Explicitly exclude known non-trading status only when supported. |
| Field completeness | Non-null valid OHLC, volume, value, delivery quantity and delivery percentage counts divided by eligible observations, separately by source/venue/era. Null is not zero. |
| Gap coverage | Number of expected sessions absent, by reason, and longest consecutive gap per listing/dataset. |
| Data-quality outcomes | Accepted, rejected, out-of-scope, excluded SME/non-equity, quarantined, duplicate and revised counts under documented accounting semantics. Excluded records are never investment-universe securities. |
| Provenance/revision coverage | Share of normalized observations linked to archived checksum, source identifier, parser/extraction version, timestamp and locator. Target 100% for admitted rows. |
| Historical bound | Earliest/latest actual source file date and earliest/latest fully reconciled eligible-mainboard date, separately. Do not substitute a product brochure date or include SME-period observations as eligible history. |

No 100% universe or complete historical claim unless the denominator is itself evidenced and all exceptions are enumerated.

## Test strategy

Keep portable synthetic tests separate from real-data adapter fixtures and local validation files. Do not commit exchange archives or local database files. Required future tests:

- Per-venue security master headers, date/time conventions, units, status values, unknown extra columns, malformed rows and field-presence changes across format versions.
- Same ISIN across exchanges resolves to one security with distinct listings; same symbol/different ISIN remains distinct; no name-only merge.
- Symbol/code reuse, routine ISIN change, effective-date boundary, suspension, delisting, relisting, and explicit merger/demerger relationships preserve separate price histories.
- Missing, multiple, conflicting, stale, unsupported-series and not-yet-public mappings are quarantined, not guessed.
- NSE and BSE EOD parsing independently checks OHLC consistency, quantity/value units, date handling, delivery fields, duplicates and conflicting same-listing/session rows.
- Raw bytes archive before parsing; archive/database crash recovery; same-byte idempotency; changed-source revision; parser v1/v2 extraction lineage; replay in fresh DB yields equivalent normalized values/provenance.
- Point-in-time public and HAMSA-known snapshots apply 15:30 IST and next trading session, including special sessions and date-only timestamps.
- Batch transaction failure leaves no partial observations; successful close/reopen preserves row counts and source lineage.
- Session-gap metrics explain holidays, pre-listing intervals, suspensions, inactive/delisted intervals, unreceived files and unresolved identity separately.
- Per-batch reconciliation ties sampled normalized rows to exact source file rows and reports all input records in explicit outcome categories.

Real-file tests should use small sanitized representative fixtures whose source date and checksum are recorded. A separate optional local validation suite can use ignored real archives; its absence must not fail a clean-checkout test run. Never represent synthetic fixtures as real exchange evidence.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| “Full universe” means different security classes | Make scope explicit and versioned before ingesting broad files. |
| Current masters omit old/inactive listings | Retain dated snapshots; use notices/filings for reviewed reconstruction; leave evidence gaps visible. |
| NSE historical program statement overread as complete dataset bounds | Verify actual files for each report/field/era; label late-1995 statement as framework-level only. |
| BSE public per-scrip route does not scale | Confirm an official all-security file before committing to BSE bulk backfill; otherwise limit/sequence scope and disclose. |
| Reused symbols/codes or changed ISINs cause false continuity | Resolve by venue/date and approved evidence; quarantine conflict; no fuzzy matching. |
| Corporate actions distort return history | Preserve raw prices; separately version reviewed factors and protect screen-time availability. |
| Parser/schema format changes | Pin parser version per extraction, test actual version samples, preserve source bytes and old extraction. |
| Large archive and revision growth | Measure real bytes/row and runtime on monthly pilot; batch, index cautiously, retain immutable sources. |
| Survivorship/look-ahead bias from today-only universe | Include historical listing status/master evidence; measure point-in-time membership and expose unresolved intervals. |
| Publicly accessible downloads mistaken for unrestricted retention/use | Follow the current source-access/product review; do not infer storage or distribution rights from technical availability. |

## Decisions requiring owner approval before implementation

1. Whether official exchange master fields alone establish mainboard classification, ordinary-share class and active status for every current row, or whether official listing notices are needed to resolve some records.
2. Whether a documented current BSE all-security EOD file is available and usable. Per-scrip files can validate samples but do not establish a complete current universe.
3. What source evidence qualifies as the effective migration/listing date for an SME-to-mainboard migration when the master gives only a dated snapshot.
4. Whether historical delivery quantity/percentage is required in the later historical backfill or is a separate optional coverage track.
5. What incomplete-coverage tolerances, if any, are acceptable for operational use. No numeric threshold is assumed; no full-coverage claim should be made while an in-scope identity is unresolved or a source row is unexplained.

## Recommended next milestone

After owner review, perform only the small source-coverage probe: inspect/download representative official master and EOD files for recent, middle and oldest-discoverable dates, report byte sizes and formats, and clarify BSE's all-security route. Do not start bulk backfill until that report and the precise instrument scope are approved.
