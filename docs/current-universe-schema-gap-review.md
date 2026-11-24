# Current-Universe Schema Gap Review

**Scope:** Read-only review of the existing DuckDB schema, ingestion repository and EOD command against current mainboard ordinary-equity membership. No code or schema was changed.

## Existing representation

The DuckDB schema already separates:

- `issuer_entity` (legal issuer),
- `equity_security` (security/share class),
- `security_identifier_revision` (effective-dated, reviewable ISIN mapping),
- `exchange_listing` (venue-specific instrument identity), and
- `exchange_listing_revision` (symbol, series, status, effective dates, source document, supersession).

`raw_source_file` stores archive path, checksum, provider/dataset, capture time and `source_as_of_date`. `source_document_revision` retains document/checksum/revision/publication/ingestion/parser/extraction provenance. `normalized_observation_registry`, `observation_quarantine` and direct observation source/extraction fields preserve lineage and unresolved rows. These structures support retaining immutable source snapshots, ISIN-based securities, separate NSE/BSE listing IDs, and quarantining invalid mappings without merging by name.

The existing source adapter is pilot-oriented: NSE UDiFF has allowlist-based filtering and no master-file classification join; BSE accepts the older per-scrip export with an explicit listing mapping, not the current all-security UDiFF bhavcopy. No application changes are proposed here.

## Gaps that block a trustworthy current universe

### 1. Snapshot membership versus effective dating

`source_as_of_date` on `raw_source_file` can identify the master snapshot, but `exchange_listing_revision.effective_from` is required and describes when a listing revision applies. Setting `effective_from` equal to a current snapshot date would invent a listing start. The architecture documentation already warns against this.

**Gap:** No separate normalized “classification/status observed in source snapshot” record keyed by listing + snapshot document/date. A current active/listed membership fact must be representable without pretending the snapshot date is the listing effective date. A source document can be retained today, but the schema does not currently give a typed, queryable membership observation distinct from an effective-dated listing revision.

### 2. Mainboard and ordinary-share classification

`exchange_listing_revision` contains `symbol`, `series`, `status`, effective dates and source reference, but no documented board/platform classification (`mainboard`, `SME`, other) or instrument class (`ordinary_equity`, ETF, preference, debt, etc.). `equity_security.share_class` is nullable and does not carry source-level field/code, point-in-time status, or review state. An issuer/business `issuer_classification_revision` is not a substitute for security/listing instrument or venue platform classification.

Observed evidence reinforces this gap: NSE daily EOD reports `FinInstrmTp=STK` and series `EQ` for NIFTYBEES; BSE reports `FinInstrmTp=STK` for NIFTYBEES as well. These instruments must be excluded under the locked scope. Series/market product fields cannot be used as the sole ordinary-equity filter.

### 3. Review state for classification

`security_identifier_revision.mapping_review_status` supports review of identifier mapping, but listing revisions have no review status, classification field, codebook version, reviewer, or reviewed timestamp. Existing source/provenance tables establish where data came from; they do not express a human-approved interpretation of an ambiguous source code. `observation_quarantine` can preserve rejected/unresolved raw rows but is not an approved membership ledger.

### 4. Mainboard migration boundary

The existing effective-dated listing revisions can retain a sourced mainboard-effective date once it is verified. However, there is no field distinguishing the earlier SME-platform listing from later mainboard classification on the same venue listing record, nor a snapshot membership history separate from listing validity. Mainboard eligibility must not be backdated; for SME-to-mainboard migrations, historical SME status and the verified mainboard effective date need distinct sourced/reviewed facts.

### 5. Master/EOD linkage and non-traded listings

EOD observation tables link to `listing_id`, which is appropriate. The current schema does not contain an exchange-specific raw master record table, but raw file + source-document lineage can preserve raw rows; normalized listing records require mappings. A BSE bhavcopy lists traded rows only and cannot establish absence, active status, suspension, or full listing coverage for records not present in the daily file. The current master snapshot is therefore a distinct required input.

## Schema assessment and minimal proposal

The core identity schema is adequate; a broad redesign is unnecessary. Before current-universe persistence is implemented, approve a narrow extension or typed observation model that can store, per venue listing and master snapshot:

1. source-reported listing/trading status as observed on that snapshot;
2. source-reported instrument type and board/platform classification, retaining raw code and source field;
3. normalized HAMSA classification values and quality/review state (`pending`, `approved`, `rejected` or equivalent); and
4. extraction/provenance links to the existing source document and raw row locator.

Keep this snapshot observation separate from `effective_from/effective_to`. Only verified source effective dates or reviewed listing notices should populate effective intervals. If a current master explicitly provides a valid effective date, retain that date with provenance; do not substitute the master snapshot date. Any ambiguous source value remains quarantined or pending review and cannot enter the eligible universe.

Candidate additions could be a separate `listing_classification_snapshot` / `listing_state_snapshot` table keyed by listing and source-document/snapshot observation, or additive classification columns/revisions on listing observations. The exact design should follow actual BSE master inspection and NSE field-code confirmation; this document does not prescribe DDL.

## Repository invariants to retain

- Resolve same-ISIN cross-exchange listings to one security while preserving separate listing IDs and venue prices.
- Do not identify securities by name or symbol alone.
- Do not auto-merge distinct securities when an ISIN changes; require sourced effective-dated mapping and explicit review. Mergers/demergers require explicit reviewed relationships.
- Never treat snapshot date as listing effective date.
- Filter current eligibility only from documented official classification/status rules; unknown codes and conflicts are quarantined.
- Preserve excluded SME and non-equity source rows for reconciliation without admitting them to HAMSA universe or discovery engines.
- Do not equate an absent EOD row with zero price/volume, suspension, or no listing.

## Open decisions / evidence needed

1. Obtain an actual current BSE equity Scrip Master snapshot through its documented official route and inspect its complete header, values, publication/snapshot date, current specification and access requirements.
2. Obtain NSE's official current code dictionary/schema for `SctyTpFlg`, `SctyStsNrmlMkt`, `ElgbltyNrmlMkt`, `DelFlg`, and any normative ordinary-equity/mainboard code fields. Confirm numeric timestamp/date encodings for `ListgDt`, `RmvlDt`, `RadmssnDt`, `UpdDt`.
3. Establish authoritative mainboard versus SME classification for each exchange and the official source of the effective date for SME-to-mainboard migrations.
4. Decide the controlled review workflow and minimum evidence for approving a classification when master fields and listing notices differ.
5. Confirm whether BSE has a separate all-security daily delivery source and whether no-trade/security omissions can be reconciled from an official current master.

## Readiness verdict

- **NSE current-universe implementation:** **Not ready for safe membership filtering or full-universe ingestion.** Official daily master and all-security EOD are publicly retrievable and the EOD has ISIN plus venue references. Blockers: unresolved official code mappings for ordinary-equity/mainboard/status classification, absent/non-populated candidate normative fields in the observed MII file, and schema gap for reviewable snapshot classification. NSE EOD parser exists for UDiFF but does not join the master or derive authorized universe membership.
- **BSE current-universe implementation:** **Not ready.** A public current all-security EOD file is retrievable and contains ISIN/security code/symbol/OHLCV/value, but there is no inspected current master to validate all listings, status, or mainboard/ordinary-share classification. Published older format docs indicate useful identifiers and broad instrument/status fields but do not prove mainboard/ordinary-equity membership; current format changed in 2026. The existing adapter also does not parse this all-security UDiFF file. Blockers: actual current master acquisition/inspection, authoritative platform/instrument mapping, and adapter compatibility.

These blockers do not prevent a later staged implementation that first ingests and archives current master snapshots, records their unresolved rows, and withholds eligibility until the official semantics and narrow schema support are approved.
