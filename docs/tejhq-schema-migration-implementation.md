# Schema Migration v3 Implementation Report

## Scope

Implemented the approved additive migration `0003_listing_classification_and_eod_reconciliation`, targeting schema version 3. The change adds only the four reviewed relations and repository support for their append, validation, point-in-time eligibility, and reconciliation workflows. No TejHQ adapter, external data, provider, dashboard, engine, or dependency was added.

The reviewed DDL was executed as written. There were no DuckDB constraint or syntax deviations.

## Migration behavior

The repository now supports:

- New database: v1 baseline schema -> verified v2 migration -> v3 migration.
- Existing v2 database: v3 migration only.
- Existing v3 database: checksum verification and reopen without reapplying migrations.

Each migration's exact file bytes are SHA-256 checked against `schema_migration`. DDL, migration-ledger insertion, and `schema_metadata` advancement run inside one transaction. A failure in v3 leaves the database at v2 with no v3 tables or ledger row. The v1 schema file and `0002_ingestion_processing.sql` remain unchanged; no historical observation rows are rewritten.

## Repository methods and rules

`DuckDBRepository` now exposes append operations for:

- `append_listing_classification_snapshot`: checks exchange/listing agreement, official source-provider venue, raw instrument identifier, and raw ISIN against one approved effective identity mapping. It writes the typed observation-registry provenance, parser-processing revision, and snapshot atomically. Extraction time is system-generated.
- `append_listing_classification_review_revision`: records instrument and platform decisions independently with system-recorded review timestamps, required evidence locators, and same-snapshot supersession chains. New events append; older intervals remain unchanged.
- `append_exchange_listing_revision_review`: requires a reviewer and an exchange-matched evidence document and locator for approval. Reviews target one exact effective listing revision and append through a same-revision supersession chain.
- `append_eod_observation_reconciliation`: accepts source observation IDs and computes the comparison payload itself. It does not update or average source observations.

`derive_universe_disposition` is a calculated result and is not persisted. It requires the exact 15:30 Asia/Kolkata cutoff and a trading-calendar session. It separately verifies approved effective identity mapping, reviewed effective listing status, and one available approved instrument interval and platform interval. The raw listing status in a classification snapshot is not read. Missing or ambiguous evidence, interval gaps, overlapping approved intervals across snapshots, and conflicting mappings return `unresolved_classification`.

For `public_as_of`, each relevant source document must be published by the cutoff, with date-only publication becoming available on the next exchange trading session. `hamsa_known_as_of` additionally requires actual source-document ingestion and snapshot extraction by the cutoff. Review-recorded and review-approved timestamps must also be at or before the cutoff. Trade dates are not substituted for publication or ingestion times.

Reconciliation comparator `eod-raw-ohlcv-turnover-v1` compares raw open, high, low, close, volume, and turnover as exact decimals with delta defined as secondary minus official. It requires the same exchange, listing, security, session, and units and validates provenance roles. Complete equal fields produce `exact_match` with `{}` differences; any difference produces `discrepancy` with both source values and deltas; missing or invalid values produce `not_compared` with NULL payloads and a reason. Unmatched official and secondary rows each store exactly one observation reference and a reason. A comparison stream has one active result; a retry cannot create another unmatched or matched leaf, and a correction must supersede the active result.

The repository has no generic update/delete methods for these relations. Direct database-owner access can still bypass application-level append-only controls.

## Verification

The migration was executed using the project environment's DuckDB Python client and engine **2.0.0** against both an in-memory database and temporary on-disk databases.

The new tests cover:

- v1 -> v2 -> v3, v2 -> v3, on-disk v3 reopen, checksum mismatch rejection, and injected v3 transaction rollback.
- Existing v2 EOD row equality before and after migration.
- Composite registry FK type enforcement, exchange/listing validation, evidence-required listing approval, review self-reference and branching, and review interval CHECKs.
- SME exclusion before a separately evidenced migration date M and mainboard classification from M.
- Snapshot raw status not overriding effective listing status; cross-snapshot approved interval overlap fails closed.
- `public_as_of` versus `hamsa_known_as_of` ingestion availability.
- Exact, discrepant, matched-but-not-compared, unmatched-official, unmatched-secondary, and duplicate reconciliation handling.
- Changed source revisions, parser revisions, and reconciliation supersession while retaining prior observations/results.

Focused v3 suite: **13 tests passed**. At the original v3 implementation milestone the suite had 88 tests; after the independent audit and TejHQ pilot additions the final pinned-environment run is **107 tests passed, 0 failures, 0 skips in 32.619 seconds**. See `docs/PROJECT_STATE.md` for the latest workspace result.

## DDL deviations and limitations

There are no deviations from the approved DDL. DDL enforces row-local types, keys, FKs, unique constraints, and CHECK shapes. Repository validation enforces cross-table exchange/source-role matching, effective identity cardinality, approved review selection, overlap detection, public/known availability, source-side reconciliation values, and exact decimal payload computation. DuckDB owner access can bypass the repository boundary.

The repository validates that evidence exists, belongs to the listing exchange, and has a non-empty locator; the responsible reviewer still determines whether that source content substantively proves the classification or effective listing interval. Overlapping approved intervals remain unresolved until evidence-backed review events create an unambiguous non-overlapping set.

## Independent audit follow-up

The later independent code audit found that `comparison_stream_id` was caller supplied and only checked against its superseding parent. That did not bind an initial stream to its source subject, despite the approved review requiring the stream key to represent venue, listing, trade date, and the official/secondary role pair.

The repository now computes the only valid stream key as a SHA-256 identifier derived from `exchange | listing_id | trade_date | official | secondary`. The append method derives the key from the referenced immutable EOD observation(s), rejects a mismatched caller key, checks that supersession preserves the same exchange/listing/security/session, and retains the existing one-active-leaf rule. The reviewed DDL and schema version are unchanged. New regression coverage rejects reuse of a valid stream for a different session. The focused v3 suite and the final full suite results are recorded in `docs/PROJECT_STATE.md`.
