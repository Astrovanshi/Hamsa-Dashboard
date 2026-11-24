# TejHQ Historical Import: Schema Migration Review

## Status and scope

This is a schema design proposal only. No migration, adapter, application code, SQL, schema, test, or database file is changed by this review. The proposed target is schema version **3**, migration ID `0003_listing_classification_and_eod_reconciliation`, applied after the current v2 migration `0002_ingestion_processing`.

The proposal adds four tables and leaves all existing tables, v1/v2 migration files, checksums, and historical records unchanged. The four tables are for dated listing-classification source observations, review events, review of effective listing revisions, and append-only source comparisons.

## Inspection of the current implementation

The current SQL schema is `sql/duckdb_schema.sql`. The repository in `src/hamsa/storage/duckdb_repository.py` declares schema version 2, applies `0002_ingestion_processing`, verifies migration checksums, and wraps migration execution in a transaction. The repository documentation says ordinary historical-observation interfaces are append-only; direct database-owner access remains outside that boundary.

Relevant existing relations are:

- `exchange_listing(listing_id, security_id, exchange, exchange_instrument_id, created_at)` identifies an exchange-specific listing.
- `exchange_listing_revision(listing_revision_id, listing_id, symbol, series, status, effective_from, effective_to, source_document_id, supersedes_listing_revision_id)` holds effective-dated listing facts. Its `status` is constrained to `active`, `suspended`, `delisted`, or `relisted`.
- `normalized_observation_registry` has `observation_id VARCHAR PRIMARY KEY` and `UNIQUE (observation_id, observation_type)`.
- `eod_price_observation_revision` already references that exact composite key through `FOREIGN KEY (observation_id, observation_type)`. Thus the proposed composite FK to the registry is valid in the actual v2 schema; no change to the registry is needed.
- Source publication, ingestion, parser, extraction timestamp, and locator are held in `source_document_revision` and the registry. The registry has observation type `classification` available.

The repository currently has no classification-snapshot writer or approval workflow for `exchange_listing_revision`. The proposal therefore uses database-local constraints for row-local rules and requires repository validation for joined identity, venue, interval, source-role, review-chain, and reconciliation invariants.

## Corrections made in this revision

| Correction | Effect on DDL | Effect on repository rules | Effect on synthetic tests |
|---|---|---|---|
| Separate instrument class, platform class, and listing status | Snapshot retains raw status only; reviews carry independent instrument and platform decisions and intervals; no stored `universe_disposition` | Eligibility derives status only from an approved effective listing revision covering the requested date | Add snapshot-status non-projection and independent-dimension tests |
| SME migration needs independent effective-date evidence | Platform review stores its evidence document, locator, and interval | Do not infer migration date from snapshot/review dates or current active status | Add pre-M / from-M cases with and without dated migration evidence |
| Listing revision approval must be evidenced | Approved listing-review row requires evidence document and locator | Validate evidence against exact listing, status, symbols, and interval | Add approval rejection for missing or mismatched evidence |
| Verify registry composite FK | No registry change; use existing unique `(observation_id, observation_type)` | Repository writes registry and target observation atomically | Migration integration test asserts FK target and rejects wrong type/missing registry row |
| Enforce exchange/listing consistency | Row-local `exchange` CHECK only | Join to `exchange_listing`; quarantine/reject mismatch before write | Add mismatched exchange/listing test |
| Validate comparison payload semantics | Reconciliation stores nullable JSON payloads and comparator version | Recompute and validate values, deltas, outcome, and source roles before append | Add exact, discrepancy, incomplete and unmatched payload tests |
| Preserve applicability review history | Review records supersede prior review events; no interval updates | Any interval change requires a new evidence-backed review; overlapping current approved intervals fail closed | Add supersession, overlap, and as-of review-history tests |

## Temporal and classification model

Three facts must remain separate:

1. **Instrument class**: for example ordinary equity, ETF, preference share, debt, or other. Its applicability interval is evidence-backed and reviewed.
2. **Platform class**: for example mainboard, SME, or another platform. Its applicability interval is independently evidence-backed and reviewed.
3. **Listing status**: active, suspended, delisted, or relisted for an exchange listing on a particular date. This comes only from an approved `exchange_listing_revision` whose effective interval covers that date and whose own review is approved.

The raw listing-status string in a classification snapshot is retained as a point-in-time source fact. It may help reconcile the source file, but it is **never** projected through either class review interval and is never used as historical listing-status evidence. Snapshot date is not an effective date.

No persisted `universe_disposition` is proposed. For listing `L` and EOD date `D`, the repository derives the disposition from the independently selected evidence below. A stale snapshot cannot establish status at `D`, and an approved class interval cannot override an inactive listing revision.

### Derived disposition for date D

1. Resolve the observation's validated ISIN to exactly one approved, effective security identifier mapping on `D`; then verify exactly one approved listing/security mapping for the exchange. Never resolve identity from symbol or company name alone.
2. Select exactly one reviewed `exchange_listing_revision` for the listing covering `D`. The review leaf must be approved. Only `active` or `relisted` status is potentially eligible; `suspended` and `delisted` produce `excluded_inactive_non_trading`.
3. Select exactly one approved instrument-class interval covering `D`, with valid evidence and applicable availability. Independently select exactly one approved platform-class interval covering `D` on the same basis.
4. Apply the locked universe policy: ordinary equity + mainboard + active/relisted + approved identity may yield `eligible_mainboard_ordinary_equity`. SME/Emerge yields `excluded_sme`; known non-equity yields `excluded_non_equity`; a known other platform yields `excluded_other_platform`; inactive status yields `excluded_inactive_non_trading`. Missing, unknown, conflicting, overlapping, or unreviewed evidence yields `unresolved_classification` and must not enter the investment universe.

These values are derived outputs, not a manually maintained allowlist. The source snapshot's `raw_listing_status` is intentionally absent from this calculation.

### Availability modes

Use publication and ingestion metadata from the source document, never trade date as a proxy. A reliable publication timestamp at or before the 15:30 Asia/Kolkata session cutoff may qualify for that session; a date-only publication or a publication after cutoff first qualifies at the next official trading session. Calendar version and the calculated availability session must be retained by the consuming as-of query or result.

Both modes require the relevant review event to have been recorded and approved by the screen cutoff. `public_as_of` additionally requires the evidence to have been publicly available by that cutoff. `hamsa_known_as_of` additionally requires the relevant source document's actual ingestion timestamp to be no later than the cutoff. Backfilled evidence is therefore absent from `hamsa_known_as_of` before ingestion. A later review never retroactively changes what HAMSA had reviewed at an earlier cutoff.

## Proposed additive DDL

The following is the proposed v3 migration body. It is not executed in this documentation milestone. Indexes are included after table creation. The column types use DuckDB types already present in the current schema.

```sql
CREATE TABLE listing_classification_snapshot (
    listing_classification_snapshot_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'classification'),
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    source_snapshot_date DATE NOT NULL,
    raw_exchange_instrument_id VARCHAR,
    raw_isin VARCHAR,
    raw_symbol VARCHAR,
    raw_series VARCHAR,
    raw_listing_status VARCHAR,
    raw_instrument_class_value VARCHAR,
    raw_platform_class_value VARCHAR,
    source_fields_json JSON NOT NULL,
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    supersedes_snapshot_id VARCHAR,
    UNIQUE (listing_classification_snapshot_id, listing_id),
    UNIQUE (listing_id, source_document_id, extraction_locator),
    FOREIGN KEY (listing_classification_snapshot_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    FOREIGN KEY (supersedes_snapshot_id, listing_id)
        REFERENCES listing_classification_snapshot(listing_classification_snapshot_id, listing_id)
);

CREATE TABLE listing_classification_review_revision (
    classification_review_revision_id VARCHAR PRIMARY KEY,
    listing_classification_snapshot_id VARCHAR NOT NULL,
    listing_id VARCHAR NOT NULL,
    recorded_by VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    rationale VARCHAR NOT NULL,

    instrument_review_status VARCHAR NOT NULL
        CHECK (instrument_review_status IN ('pending', 'approved', 'rejected')),
    instrument_class VARCHAR CHECK (instrument_class IN (
        'ordinary_equity', 'etf', 'mutual_fund', 'reit', 'invit', 'preference',
        'warrant', 'rights', 'debt', 'other', 'unknown'
    )),
    instrument_valid_from DATE,
    instrument_valid_to DATE,
    instrument_evidence_source_document_id VARCHAR
        REFERENCES source_document_revision(source_document_id),
    instrument_evidence_locator VARCHAR,
    instrument_reviewed_by VARCHAR,
    instrument_reviewed_at TIMESTAMPTZ,

    platform_review_status VARCHAR NOT NULL
        CHECK (platform_review_status IN ('pending', 'approved', 'rejected')),
    platform_class VARCHAR CHECK (platform_class IN ('mainboard', 'sme', 'other_platform', 'unknown')),
    platform_valid_from DATE,
    platform_valid_to DATE,
    platform_evidence_source_document_id VARCHAR
        REFERENCES source_document_revision(source_document_id),
    platform_evidence_locator VARCHAR,
    platform_reviewed_by VARCHAR,
    platform_reviewed_at TIMESTAMPTZ,

    supersedes_review_revision_id VARCHAR,
    UNIQUE (classification_review_revision_id, listing_classification_snapshot_id, listing_id),
    UNIQUE (supersedes_review_revision_id),
    FOREIGN KEY (listing_classification_snapshot_id, listing_id)
        REFERENCES listing_classification_snapshot(listing_classification_snapshot_id, listing_id),
    FOREIGN KEY (supersedes_review_revision_id, listing_classification_snapshot_id, listing_id)
        REFERENCES listing_classification_review_revision(
            classification_review_revision_id, listing_classification_snapshot_id, listing_id
        ),
    CHECK (instrument_valid_to IS NULL OR instrument_valid_from IS NULL
        OR instrument_valid_from <= instrument_valid_to),
    CHECK (platform_valid_to IS NULL OR platform_valid_from IS NULL
        OR platform_valid_from <= platform_valid_to),
    CHECK (
        (instrument_review_status = 'approved'
            AND instrument_class IS NOT NULL AND instrument_valid_from IS NOT NULL
            AND instrument_evidence_source_document_id IS NOT NULL
            AND instrument_evidence_locator IS NOT NULL AND length(instrument_evidence_locator) > 0
            AND instrument_reviewed_by IS NOT NULL AND instrument_reviewed_at IS NOT NULL)
        OR (instrument_review_status = 'pending'
            AND instrument_valid_from IS NULL AND instrument_valid_to IS NULL
            AND instrument_evidence_source_document_id IS NULL AND instrument_evidence_locator IS NULL
            AND instrument_reviewed_by IS NULL AND instrument_reviewed_at IS NULL)
        OR (instrument_review_status = 'rejected'
            AND instrument_valid_from IS NULL AND instrument_valid_to IS NULL
            AND instrument_reviewed_by IS NOT NULL AND instrument_reviewed_at IS NOT NULL)
    ),
    CHECK (
        (platform_review_status = 'approved'
            AND platform_class IS NOT NULL AND platform_valid_from IS NOT NULL
            AND platform_evidence_source_document_id IS NOT NULL
            AND platform_evidence_locator IS NOT NULL AND length(platform_evidence_locator) > 0
            AND platform_reviewed_by IS NOT NULL AND platform_reviewed_at IS NOT NULL)
        OR (platform_review_status = 'pending'
            AND platform_valid_from IS NULL AND platform_valid_to IS NULL
            AND platform_evidence_source_document_id IS NULL AND platform_evidence_locator IS NULL
            AND platform_reviewed_by IS NULL AND platform_reviewed_at IS NULL)
        OR (platform_review_status = 'rejected'
            AND platform_valid_from IS NULL AND platform_valid_to IS NULL
            AND platform_reviewed_by IS NOT NULL AND platform_reviewed_at IS NOT NULL)
    )
);

CREATE TABLE exchange_listing_revision_review (
    listing_revision_review_id VARCHAR PRIMARY KEY,
    listing_revision_id VARCHAR NOT NULL REFERENCES exchange_listing_revision(listing_revision_id),
    review_status VARCHAR NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    recorded_by VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMPTZ,
    evidence_source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    evidence_locator VARCHAR,
    rationale VARCHAR NOT NULL,
    supersedes_review_id VARCHAR,
    UNIQUE (listing_revision_review_id, listing_revision_id),
    UNIQUE (supersedes_review_id),
    FOREIGN KEY (supersedes_review_id, listing_revision_id)
        REFERENCES exchange_listing_revision_review(listing_revision_review_id, listing_revision_id),
    CHECK (
        (review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL
            AND evidence_source_document_id IS NULL AND evidence_locator IS NULL)
        OR (review_status = 'rejected' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR (review_status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND evidence_source_document_id IS NOT NULL
            AND evidence_locator IS NOT NULL AND length(evidence_locator) > 0)
    )
);

CREATE TABLE eod_observation_reconciliation (
    reconciliation_id VARCHAR PRIMARY KEY,
    comparison_stream_id VARCHAR NOT NULL,
    comparator_version VARCHAR NOT NULL,
    official_observation_id VARCHAR REFERENCES eod_price_observation_revision(observation_id),
    secondary_observation_id VARCHAR REFERENCES eod_price_observation_revision(observation_id),
    match_status VARCHAR NOT NULL CHECK (match_status IN (
        'matched', 'unmatched_official', 'unmatched_secondary'
    )),
    comparison_outcome VARCHAR NOT NULL CHECK (comparison_outcome IN (
        'exact_match', 'discrepancy', 'not_compared'
    )),
    compared_fields_json JSON,
    differences_json JSON,
    not_compared_reason_code VARCHAR,
    compared_at TIMESTAMPTZ NOT NULL,
    supersedes_reconciliation_id VARCHAR,
    UNIQUE (reconciliation_id, comparison_stream_id),
    UNIQUE (supersedes_reconciliation_id),
    FOREIGN KEY (supersedes_reconciliation_id, comparison_stream_id)
        REFERENCES eod_observation_reconciliation(reconciliation_id, comparison_stream_id),
    CHECK (
        (match_status = 'matched' AND official_observation_id IS NOT NULL
            AND secondary_observation_id IS NOT NULL
            AND official_observation_id <> secondary_observation_id)
        OR (match_status = 'unmatched_official' AND official_observation_id IS NOT NULL
            AND secondary_observation_id IS NULL)
        OR (match_status = 'unmatched_secondary' AND official_observation_id IS NULL
            AND secondary_observation_id IS NOT NULL)
    ),
    CHECK (
        (comparison_outcome IN ('exact_match', 'discrepancy') AND match_status = 'matched'
            AND compared_fields_json IS NOT NULL AND differences_json IS NOT NULL
            AND not_compared_reason_code IS NULL)
        OR (comparison_outcome = 'not_compared' AND compared_fields_json IS NULL
            AND differences_json IS NULL AND not_compared_reason_code IS NOT NULL)
    ),
    CHECK (comparison_outcome <> 'exact_match' OR match_status = 'matched'),
    CHECK (comparison_outcome <> 'discrepancy' OR match_status = 'matched')
);

CREATE INDEX listing_classification_snapshot_listing_date_idx
    ON listing_classification_snapshot(listing_id, source_snapshot_date);
CREATE INDEX listing_classification_review_target_idx
    ON listing_classification_review_revision(listing_id, recorded_at);
CREATE INDEX listing_revision_review_target_idx
    ON exchange_listing_revision_review(listing_revision_id, recorded_at);
CREATE INDEX eod_reconciliation_stream_idx
    ON eod_observation_reconciliation(comparison_stream_id, compared_at);
CREATE INDEX eod_reconciliation_official_idx
    ON eod_observation_reconciliation(official_observation_id);
CREATE INDEX eod_reconciliation_secondary_idx
    ON eod_observation_reconciliation(secondary_observation_id);
```

### DDL notes

- The registry composite FK is intentionally the same shape already used by `eod_price_observation_revision`. The existing registry declares the target as `UNIQUE (observation_id, observation_type)`, so the FK target is valid. The new snapshot write must insert registry and snapshot rows in one repository transaction.
- `listing_classification_snapshot.exchange` cannot be constrained to equal the referenced listing exchange by the row-local FK because the current parent key is only `listing_id`. Do not add a redundant listing record or alter existing identity tables for this proposal.
- CHECK constraints validate row shape but cannot prove that JSON deltas are correct, a document's locator contains the claimed fact, or intervals do not overlap across rows. Those remain repository validations below.
- The migration must be tested against the project's pinned DuckDB 2.0.0 with both an in-memory and temporary on-disk database before implementation is accepted. This proposal does not claim the new DDL has been executed.

## Append-only and supersession semantics

### Classification snapshots

Each row is one extracted listing row from one source-document extraction. The unique key prevents duplicate extraction of the same listing/source/locator. A reparse with a new parser is a new extraction record and may point to `supersedes_snapshot_id`; the source document itself is not revised merely because parser code changed. The raw file and prior extraction remain preserved.

### Classification review revisions

Each review row is immutable. The instrument and platform dimensions have separate status, decision, applicability interval, evidence, and reviewer timestamps, so one can be approved while the other remains pending or rejected. A superseding review must target the same classification snapshot. It creates a new history event; it never updates the prior row.

An approved interval change requires a new review event with new evidence and rationale. Historical as-of selection follows the supersession chain visible by the cutoff: before the superseding event is recorded, the former review remains the known review; after it is recorded and approved, the new leaf governs that snapshot. No code may silently widen, shorten, or shift a prior interval.

### Listing revision reviews

Each review is immutable and targets one exact `exchange_listing_revision`. A review supersession chain may only contain reviews of that same target revision. An approved review requires `evidence_source_document_id` and a non-empty `evidence_locator`; it also requires reviewer and review timestamp. Approval means the referenced effective listing interval/status has evidence support. It does not establish ordinary-equity or mainboard classification.

### Reconciliation history

Each result is immutable. A later source revision, parser extraction, comparator version, corrected identity, or changed comparison produces a new reconciliation event. The former source observations and reconciliation result stay queryable. A correction uses `supersedes_reconciliation_id` within the same stable comparison stream. A parser revision does not mutate a source observation; it creates a separate observation lineage and comparison event.

## Repository validation requirements

DuckDB constraints enforce primary/foreign/unique keys and row-local shapes. The repository must validate all cross-table invariants before writes and perform related inserts atomically.

### Classification snapshot and identity

- Join `listing_id` to `exchange_listing` and require `snapshot.exchange = exchange_listing.exchange`; require the raw exchange instrument identifier, when present, to agree with that listing's instrument identifier.
- Require source provider/dataset and source role to match the snapshot exchange and documented master type. A source snapshot date must agree with source metadata where provided; it must not be substituted for source document publication date or effective listing date.
- Resolve non-null raw ISIN using exactly one approved, effective security identifier revision. The resulting security must equal `exchange_listing.security_id`. Missing ISIN may remain missing in the raw snapshot, but identity must then be resolved by an independently approved listing mapping; do not guess from symbol/name. Ambiguous or conflicting mappings are quarantined.
- Require the registry row's observation ID/type and provenance fields to match the snapshot, source document, parser version, extraction timestamp, and exact locator. Keep the registry insert and snapshot insert in one transaction.
- Verify snapshot supersession points to the same listing. A changed exchange instrument identifier or changed ISIN is not silently merged; it requires the existing reviewed mapping or relationship workflow.

### Class review and interval selection

- Require review-chain links to target the same snapshot; reject cycles, forks, duplicate successors, and a supersession timestamp earlier than its predecessor.
- Require evidence document and locator to substantiate the specific dimension, value, and complete interval. `instrument_valid_*` and `platform_valid_*` are evaluated independently. Evidence availability is calculated from the source publication metadata and trading calendar, not the class interval's first date.
- An approved interval may only be appended after evidence review. A new interval that changes a previous approved decision requires a superseding review event with new evidence and rationale. Never update the previous event's dates.
- For a requested as-of cutoff, select review-chain leaves available by the cutoff. For each listing and dimension, detect any overlapping approved intervals across applicable leaves/snapshots. Any competing overlap, gap, or conflicting value is unresolved; do not resolve by “latest row wins.” The proposed review chain supersedes events for the same snapshot only. When a new snapshot supports a changed interval, close the old interval by appending an evidence-backed review event on the old snapshot, and separately append an evidence-backed approval for the new snapshot. If the competing new interval is wrong, append a rejected superseding event on that new snapshot's chain. Keep the conflict unresolved until the resulting approved interval set is non-overlapping and unambiguous; never edit either earlier event.
- Review and source availability are separate. `public_as_of` requires public evidence available by cutoff and an approved review event already recorded by cutoff. `hamsa_known_as_of` additionally requires actual source ingestion by cutoff. A date-only source publication is eligible only from the next exchange trading session.

### Listing revision review

- Resolve `listing_revision_id` to its `exchange_listing`, then verify that the evidence document/locator supports the exact exchange instrument, symbol/series where applicable, status, `effective_from`, and `effective_to` values. Do not infer interval endpoints from a current master snapshot.
- Approved review requires reviewer, review time, evidence document and non-empty locator (also DDL-checked). A review is not approved if evidence is absent, ambiguous, for another listing, or supports different status/dates.
- For EOD date `D`, require exactly one approved effective listing revision covering `D` and an approved review leaf for that exact revision. Use only its effective status. `suspended` and `delisted` are not eligible; `active`/`relisted` are necessary but not sufficient.
- Ensure review timestamps are no later than the screening cutoff. Keep review decision history append-only.

### Reconciliation source-pair checks

- `official_observation_id` must refer to an observation whose source document/provider role is officially NSE or BSE for the matching exchange; `secondary_observation_id` must refer to the admitted secondary dataset role. Role is based on provenance, not a caller-provided label alone.
- For a matched pair require equal exchange, listing ID, security ID, trade date, compatible canonical units, and observed/valid values for every configured comparable field. Never match across venues or merely by symbol.
- Validate the comparison stream key against venue, listing, trade date, and official/secondary source role. An unmatched result contains exactly one available observation ID and a reason code; the absent side stays NULL. It is not a zero-difference comparison.
- Check that superseded reconciliation rows stay in the same comparison stream; disallow cycles, forks, and duplicate active leaves. Null pair columns require repository idempotency checks because nullable unique constraints do not by themselves prevent repeated unmatched rows.

## Reconciliation payload contract

`comparator_version` defines the ordered field set and arithmetic semantics. For price comparisons it identifies exact raw OHLC, volume, and turnover fields; no adjusted prices are compared with raw prices. Values and deltas are serialized as decimal strings in JSON to avoid binary or JSON-number precision loss. Example:

```json
{
  "close_raw": {"official": "1030.00", "secondary": "1030.0", "delta": "0.00"},
  "volume_raw": {"official": "1000", "secondary": "1001", "delta": "1"}
}
```

- **`exact_match`**: both observations exist; every configured comparable field exists and is valid on both sides; the comparator recomputes each delta and all values compare exactly equal under that comparator version; `differences_json` is the empty JSON object `{}`. `compared_fields_json` contains all configured field values and computed deltas.
- **`discrepancy`**: both observations exist and all configured fields needed for this comparator are present/valid; at least one field differs. `compared_fields_json` retains both original source values and the computed delta for every compared field. `differences_json` retains the non-equal fields with both values and delta. Repository recomputation must yield at least one non-zero difference.
- **`not_compared` for a matched pair**: both source rows exist but a required configured field is missing, invalid, unit-incompatible, or unsupported for the comparator. Both payload columns are NULL and `not_compared_reason_code` records the reason, such as `missing_comparable_value`, `invalid_source_value`, `incompatible_unit`, or `unsupported_comparator`.
- **`not_compared` for an unmatched record**: exactly one source observation ID is present, the other is NULL, both payloads are NULL, and reason identifies no counterpart/coverage/not-yet-ingested/quarantined/ambiguous identity. Never store an empty differences object as a substitute for an absent pair.

Repository validation parses payload JSON, checks the field set against `comparator_version`, recomputes each decimal delta from the preserved source values, enforces empty differences for exact matches, non-empty differences for discrepancies, and NULL payloads for every not-compared outcome. It verifies the cited observations actually have those source values. The DDL can enforce presence/absence and pair shape, but not field-level arithmetic correctness or JSON object emptiness.

## SME-to-mainboard migration example

Let `M` be the independently documented effective mainboard migration/listing date. Suppose a verified official source says the listing was SME through `M - 1`, and a migration notice or official listing record establishes mainboard from `M`.

| EOD date | Platform decision used | Listing status used | Result |
|---|---|---|---|
| `D < M` | Approved SME interval covering D | Approved effective listing revision covering D | `excluded_sme` (or inactive if listing status is inactive); never mainboard eligible |
| `D >= M` | Approved mainboard interval starting M, supported by independent migration evidence | Approved effective listing revision covering D | Eligible only if identity is approved, instrument class is ordinary equity, and listing status is active/relisted |

The current classification snapshot date, a current `active` status, and the later human review timestamp provide no evidence for `M`. If no independent source supports `M`, the platform interval is unresolved and the listing is not admitted from any guessed date. Earlier SME listing history remains separately represented; predecessor/successor or ISIN changes do not merge price or financial histories.

## Migration compatibility and recovery

Proposed migration path: schema v1 baseline -> existing v2 migration -> new v3 migration, and schema v2 -> v3. New tables are empty on upgrade. Do not alter `sql/duckdb_schema.sql` in a way that changes the v1 baseline checksum, and do not edit `0002_ingestion_processing.sql` or its checksum.

Implementation should add `0003_listing_classification_and_eod_reconciliation.sql`, advance repository constants to version 3 and migration ID `0003_listing_classification_and_eod_reconciliation`, and apply DDL, migration ledger insertion, and `schema_metadata` update inside one transaction. Record the SHA-256 checksum of the exact migration bytes. If any statement or metadata write fails, rollback must leave version and tables at v2. Reopening a v3 database must verify the stored migration checksum. A database with a checksum mismatch or partial/unrecognized metadata must fail closed and require explicit repair; do not silently rerun a changed migration.

This proposal does not modify existing records, assign historical listing dates from snapshots, or backfill classification decisions. Historical eligibility remains unresolved until separately sourced and reviewed evidence covers the date.

## Requirement-to-enforcement and synthetic test matrix

| Requirement / scenario | Database enforcement | Repository enforcement | Proposed synthetic expected outcome |
|---|---|---|---|
| Valid v2 registry FK target | Existing unique `(observation_id, observation_type)` plus new composite FK | Atomic registry/snapshot append | Migration succeeds; wrong or absent registry pair fails FK |
| Snapshot exchange matches listing exchange | Listing FK and exchange enum only | Join parent and reject/quarantine exchange mismatch | NSE snapshot referencing BSE listing is rejected; no record committed |
| NIFTYBEES / non-equity example | Instrument class decision enum permits `etf` | Official classification evidence yields `excluded_non_equity`; `STK/EQ` alone does not imply eligibility | `NIFTYBEES` remains excluded if authoritative instrument evidence says ETF, regardless of series/status |
| Historical classification gap | Review status and interval CHECKs | Missing interval coverage yields unresolved | No applicable class review on D => unresolved, not eligible |
| SME-to-mainboard at M | Separate platform decision interval and evidence FK/locator | Require independent dated migration evidence; no snapshot/status/review-time inference | SME before M; eligible platform only from M when evidence supports M; absent evidence remains unresolved |
| Snapshot raw status | Nullable raw source string only | Never consulted for historical listing status | Current raw `active` cannot make a prior suspended/delisted date eligible |
| Effective listing status | Existing listing revision status/interval plus review FK | Exactly one approved review and interval covering D | `suspended` at D is inactive even if classes say ordinary/mainboard |
| Changed ISIN | Existing identifier and relationship model | Resolve only through reviewed effective identifier mapping; keep security histories distinct | Dates before/after change map only to the respective security; no automatic history merge |
| Conflicting listing mappings | PK/FKs, but cross-table cardinality not expressible locally | Detect duplicate/ambiguous effective mappings and quarantine | Conflicting mapping creates no eligible classification or price identity |
| Missing/conflicting class evidence | Review CHECKs enforce approved evidence fields | Verify source contents, evidence locator, and independent intervals | Missing or conflicting evidence stays unresolved |
| Listing review without evidence | Approved-row CHECK requires evidence source and locator | Validate evidence supports exact listing and interval | Approved insert without evidence fails CHECK; mismatched evidence rejected by repository |
| Review applicability supersession | Self-FK target and unique successor | Chain validation; new interval needs new evidence-backed event | Prior event remains queryable; historical cutoff selects pre/post event state correctly |
| Overlapping approved intervals | Not expressible by row-local CHECK | Detect competing overlaps across review leaves and snapshots; fail closed; close old intervals and approve new intervals as separate evidence-backed events | Overlap for same listing/dimension is quarantined/unresolved until review events produce a non-overlapping set; never latest-wins |
| Exact reconciliation | Pair/payload CHECKs | Verify same venue/listing/security/date/units and recompute all exact values/deltas | All configured fields present and equal => exact_match, complete compared payload, `{}` differences |
| Discrepancy reconciliation | Pair/payload CHECKs | Verify at least one unequal field and recompute delta; retain both source values | Any difference => discrepancy with both values and computed delta; no source row changed |
| Incomplete matched pair | Payload CHECK allows not_compared with NULL payloads/reason | Require a reason and no partial comparison claim | Missing required field => not_compared, both JSON columns NULL |
| Unmatched observations | One side NULL shape CHECK | Require source-side reason; nullable unmatched idempotency handled in repo | One source ID, other NULL, outcome not_compared, no zero-difference payload |
| Revised official/secondary observation | Source observations append-only | New reconciliation row supersedes in same stream | Old observation and result remain queryable; revised source creates new comparison |
| Parser revision | Existing source/extraction lineage | New extraction and observation lineage; do not mutate old parser result | v1 and v2 observations/results remain available and distinguishable |
| public_as_of vs hamsa_known_as_of | Source document timestamps available | Enforce publication/calendar eligibility versus actual ingestion cutoff and review timestamp | Backfilled source absent in known-as-of before ingestion; public-as-of uses verified publication and approved review time |
| Transaction rollback | FKs/checks and transaction support | Write registry, snapshot/review, and lineage atomically | Injected failure leaves no partial registry, snapshot, or review rows |
| Reopen/persistence | Migration ledger and table DDL | Validate metadata/checksum on repository open | v3 database reopens with identical records; mismatch fails closed |

## Invariants not enforced by DuckDB row-local constraints

The following require the repository boundary and explicit tests: snapshot/listing exchange equality; ISIN-to-security-to-listing cardinality at date D; evidence text/locator actually supporting a claim; source role and venue consistency; listing-review evidence matching effective status and bounds; review-chain acyclicity and no forks; non-overlap of approved applicability intervals; separation of publication, ingestion, review and effective timestamps; applicability of trading-calendar rules; source-side correctness of comparison values; exact JSON payload arithmetic/empty differences; stable unmatched comparison idempotency; and selecting only approved, available evidence in a requested as-of mode.

Ordinary repository operations should expose append methods only, with no generic update/delete for these records. Corrections append superseding revisions. A database owner with direct DuckDB access can bypass repository validation or alter/delete data; the append-only guarantee is an application boundary, not tamper-proof database security.

## Verification performed for this review

- Actual `sql/duckdb_schema.sql` and repository migration logic inspected; current supported schema is v2.
- DuckDB 2.0.0 in-memory metadata inspection confirmed `normalized_observation_registry` has `UNIQUE (observation_id, observation_type)` and the existing EOD table uses that composite FK shape.
- Existing full suite run without code/test/schema changes: **75 tests passed, 0 failures** (`Ran 75 tests in 27.151s`).
- The proposed v3 DDL has not been executed; actual DuckDB migration validation and the additional synthetic test cases above belong to the implementation milestone after approval.

## Unresolved implementation risks

1. The exact source schema and evidence locators for classification snapshots depend on the exchange-specific master files and notices admitted later; this design intentionally does not assert unverified fields.
2. A policy owner must approve the exact comparator field sets, decimal normalization/equality rules, and reason-code vocabulary per comparator version before reconciliation is implemented.
3. Repository design must define how a review chain supersedes prior applicability across different snapshots; overlaps remain fail-closed until one unambiguous evidence-backed leaf set exists.
4. DuckDB 2.0.0 support for every proposed self-referential composite FK and CHECK expression must be verified by executing the migration in memory and on disk before adapter work. Any failure must be reported exactly and brought back for design review; constraints must not be weakened silently.
