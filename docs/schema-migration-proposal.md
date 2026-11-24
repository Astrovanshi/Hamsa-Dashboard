# Listing Classification Schema Migration Proposal

**Status:** Design proposal only; no DDL was run and no migration file was created.
**Target:** DuckDB analytical schema, currently versioned through existing schema metadata/migrations.
**Proposed migration ID:** `0003_listing_classification_snapshots` (final number must be confirmed against the migration registry at implementation time).

## Existing schema inspection

The current schema already contains:

- `exchange_listing(listing_id, security_id, exchange, exchange_instrument_id)`;
- `exchange_listing_revision(listing_revision_id, listing_id, symbol, series, status, effective_from, effective_to, source_document_id, supersedes_listing_revision_id)`;
- `source_document_revision` and `raw_source_file` for archive checksum, source/publication/snapshot dates, ingestion and parser/extraction provenance;
- `security_identifier_revision` for effective-dated ISIN mappings with `mapping_review_status`, reviewer and review time;
- `observation_quarantine` for source-row problems.

The gap is not company/security identity. The gap is that current-source classification has neither its own snapshot-date fact nor reviewable normalized dimensions. `exchange_listing_revision.effective_from` is required and has interval semantics, so it cannot truthfully hold a source snapshot date by default. `exchange_listing_revision` has no review-status/audit relation. Existing `issuer_classification_revision` is issuer business/sector classification, not venue platform/instrument classification. `filter_review` is the investment dossier's Hamsa 11 history and is not a listing review ledger.

## Proposed additive migration

Use the three related records described in [listing-classification-snapshot-design.md](listing-classification-snapshot-design.md):

1. `listing_classification_snapshot` — immutable listing/source snapshot row with `source_snapshot_date`, `source_document_id`, raw observed exchange fields, typed normalized `instrument_class`, `platform_class`, `listing_status`, mutually exclusive `universe_disposition`, `classification_rule_version`, extraction locator/provenance, and supersession lineage.
2. `listing_classification_review_revision` — append-only review events for the snapshot's normalized interpretation. Each event records status, reviewer/time, rationale/evidence and predecessor review. Eligibility requires the latest approved review.
3. `exchange_listing_revision_review` — append-only review events specifically for records in the existing effective-dated `exchange_listing_revision`. This provides an auditable review history without adding mutable current status onto an old effective history row.

### Proposed constraints and indexes

- Primary key per new row; FK from classification snapshot to `exchange_listing`, `source_document_revision`, and optional superseded snapshot.
- Unique `(listing_id, source_document_id, extraction_locator)` for a source row; allow multiple files/revisions for one snapshot date.
- FK from classification review to the exact classification snapshot; FK from listing review to exact listing revision; self-FKs for review supersession.
- Checks limiting normalized enum values and requiring complete provenance/source locator.
- Require `source_snapshot_date` and source document. No `effective_from` is added to snapshot table.
- Ensure an `eligible_mainboard_ordinary_equity` snapshot has normalized instrument `ordinary_equity`, platform `mainboard`, and listing status `listed_trading`; enforce with a table CHECK where DuckDB supports it and duplicate validation in repository.
- Ensure any approved eligible view requires latest review status approved; cross-row/latest-leaf condition belongs to repository/view logic because a simple row CHECK cannot verify that a review is the latest leaf.
- An unresolved/conflicted/unknown class cannot pass the eligible-view predicate.

## Effective-date and snapshot-time semantics

`source_snapshot_date` answers “what date did this source snapshot describe?” `effective_from/effective_to` answer “on what market dates did this listing revision apply?” They are separate facts.

- If a master explicitly provides a listing date and its official semantics are confirmed, retain it with provenance; do not derive an interval start from the file date.
- A classification change can be observed on one snapshot and have a different, explicitly documented effective date. Store both independently.
- If only a current snapshot is known, the classification statement is “observed as of this snapshot”; historical status remains unknown. No historical backfill of eligibility is performed.
- Under `public_as_of`, the snapshot is available only according to its reliable publication date/time and trading-calendar cutoff. Under `hamsa_known_as_of`, also require actual ingestion time. These conditions continue to use the existing point-in-time source/document layer.

## Migration/backfill behavior

The migration creates empty new tables and indexes only. It does **not** populate them from current `exchange_listing_revision` rows because existing rows lack a verified snapshot classification and may use effective dates with different semantics. It does not assign existing rows a review status automatically. Existing exchange listings remain unchanged but are not eligible for new mainboard-universe filtering until they have a classified, reviewed source snapshot.

At implementation time:

1. confirm actual latest migration number and schema version;
2. execute migration in a transaction using DuckDB itself;
3. verify all FKs/checks/data types and reopen database;
4. add repository methods that append source snapshots/reviews only and offer no generic historical-observation update/delete;
5. add synthetic tests for snapshot vs effective date, review supersession, status changes, same-date corrected files, SME migration, invalid/missing ISIN, and cross-venue conflicts;
6. only then load any actual exchange master, after source access and source qualification approvals.

## Classification outcome model

Store separate raw and normalized dimensions. The final disposition uses:

```text
eligible_mainboard_ordinary_equity
excluded_sme
excluded_non_equity
excluded_inactive_nontrading
unresolved_classification
```

Use these exact disposition values consistently in the snapshot model and implementation. The reviewer action is separate (`pending`, `approved`, `rejected`) and does not change raw source facts. A rejected or unresolved record remains visible and cannot enter the eligible view.

The actual production enum should be finalized with the source codebooks before the migration is written. In particular, do not encode current unknown NSE/BSE fields as a guessed instrument/platform enum.

## Repository-enforced invariants

DuckDB FKs/CHECKs can enforce row-local types/enum/reference constraints. Application repository validation must additionally enforce:

- source document provider matches listing exchange;
- source snapshot date matches the document's declared as-of date (when present);
- source listing ID/ISIN resolves uniquely and does not conflict with effective-dated mapping;
- a raw row maps to exactly the intended `listing_id`, and a duplicated symbol/name is never used as a fallback;
- latest non-superseded review is the sole active decision state;
- approved eligible disposition requires all verified normalized dimensions and applicable effective date for migrations;
- no direct update/delete API exists for observations/review records; corrections/reviews append new revisions.

Direct DuckDB owner access can bypass repository-level policies. Keep DB files local/private and treat repository controls as the normal application boundary; as already documented for historical records, this is not a tamper-proof security boundary against a database owner.

## Open decisions before implementation

1. Obtain the current BSE SCRIP.ZIP file and confirm current fields, source date, and whether an ordinary data user can fetch it without member authorization.
2. Obtain a current official NSE MII field/code crosswalk, particularly `SctyTpFlg`, status/eligibility fields, and any mainboard/SME classification. The legacy security.txt codebook is not sufficient as a silent crosswalk to the observed 2026 MII CSV.
3. Decide whether classification review is always manual or whether only previously approved source-code mappings may be applied automatically with human review at mapping-version level. Individual qualitative judgments remain manual; unresolved codes remain quarantined either way.
4. Define exact normalized enum spellings and migration time-of-effect event types after source research is complete.
5. Decide whether listing-revision review events need a separate table (recommended for clear audit semantics) or can share a typed review-event table without weakening FKs.

## Recommendation

Adopt an additive, snapshot-based classification model and a separate append-only review history. Do not modify `exchange_listing_revision.effective_from` semantics and do not backfill eligibility from today's master. Proceed to implementation only after obtaining the current BSE master and resolving the current NSE MII code crosswalk; until then, approved examples can be represented, but a complete exchange universe must remain unresolved wherever the source cannot prove instrument and platform.
