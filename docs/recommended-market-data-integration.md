# Recommended Market Data Integration

## Decision

Adopt **Option C: TejHQ as a gated, secondary historical-backfill source; HAMSA's official-file adapter for ongoing EOD ingestion.** Read selected TejHQ Parquet files directly with DuckDB after local archival. Do not install `tej-bazaar`, reuse its downloader, or replace HAMSA's identity, provenance, classification, revision, or point-in-time controls.

This is the fastest practical path that reuses an existing data pipeline without letting its broader universe and inferred history become HAMSA truth. It preserves the approved investment universe: **NSE and BSE mainboard ordinary equity shares only**.

## Reuse versus retain

| Reuse from TejHQ | Retain from HAMSA | Redundant or not adopted |
|---|---|---|
| Published unadjusted NSE/BSE price Parquet as a candidate historical input; separate venue delivery Parquet; action/event rows only as candidate research evidence. Use its observed file/schema and coverage gaps to plan imports. | DuckDB schema and repositories; immutable raw source archive/checksums; source/extraction lineage; actual HAMSA ingestion timestamps and `public_as_of`/`hamsa_known_as_of`; issuer/security/listing identities; ISIN-only security resolution; explicit BSE listing maps; classification/review gate; validation, quarantine, duplicate/conflict/revision handling; official local-file EOD path for daily updates. | Writing a new historical exchange scraper/downloader; TejHQ's Python pipeline/dependency stack; its symbol-gap/chain inference as security identity; its broad series allowlists as eligibility; its retrospective adjusted prices/factors as HAMSA screen data; other projects' unofficial endpoint wrappers. |

The current HAMSA ingestion is not redundant: it already parses official NSE files and a BSE per-scrip history export, archives source files, records provenance, and enforces conservative ingestion behavior. The uncovered work is a reviewed full-universe master/classification path and a practical BSE current-universe EOD path; this evaluation does not claim TejHQ resolves those authoritative classification questions.

## Source and provenance treatment

For every imported TejHQ file, record and retain:

- Exact downloaded Parquet bytes in HAMSA's raw archive and SHA-256.
- Dataset/repository ID, immutable dataset commit/revision, relative path, exchange, coverage dates, and file size.
- Retrieval timestamp (system-generated), import timestamp, parser/normalizer version, schema fingerprint, and source-record locator (row key or stable row ordinal plus source columns).
- `source_kind=third_party_normalized_dataset`, provider attribution `TejHQ`, and a rights/review status that does not imply exchange permission.
- The original per-row fields exactly as supplied, including null ISIN and series; any conversion is a separate derived observation with formula/version and lineage.

These Parquet files are TejHQ's normalized artifacts, not original NSE/BSE raw files. Their checksum is not the checksum of the exchange source. Do not create synthetic original-file references, publication timestamps, or effective listing dates. When TejHQ does not provide a reliable publication timestamp, do not infer one from the trade date. A retrospective backfill may be eligible for `public_as_of` only where source-publication availability is independently evidenced; it must remain unavailable in `hamsa_known_as_of` before actual local ingestion.

TejHQ's published terms permit local personal research under TejHQ's terms but state that TejHQ lacks exchange licensing/clarification and cannot grant rights from the exchanges. Keep that distinction in source admission. This recommendation is not a conclusion that exchange terms permit archival use; resolve that boundary before making the dataset a durable production dependency.

## Mainboard and identity admission gate

Apply HAMSA's official exchange classification observations before a source row enters canonical investment-universe observations:

1. Resolve a row to a venue-specific listing and a security only with a valid, reviewed ISIN/listing mapping effective on the row date.
2. Require a reviewed official classification that identifies an ordinary equity mainboard listing and an eligible listing/trading state for the relevant session.
3. Keep NSE and BSE prices and delivery separate; never average prices or merge delivery percentages.
4. Quarantine absent/invalid ISINs, conflicting mappings, missing classification, ambiguous instruments, duplicate-key conflicts, and rows that only match by symbol/name.
5. Exclude Emerge/SME, ETFs, funds, REITs/InvITs, preference shares, warrants, rights instruments, debt, and all other non-ordinary-equity classes. An EQ/BE/BZ, A/B/T, or other series label is not the classification proof.
6. For SME-to-mainboard migration, preserve the earlier SME listing separately and admit the mainboard listing only from the independently sourced effective migration date. A current dataset row/snapshot cannot backdate eligibility.

Unresolved rows may be retained in source staging/quarantine for coverage reconciliation but must never flow into discovery engines.

## Price, delivery, and action policy

- **Backfill prices:** start with TejHQ unadjusted OHLCV/traded value for sessions with usable identity and classification; maintain venue-specific records. Verify units and source field semantics on a local representative file before broad ingestion.
- **Daily update:** continue official NSE files and use official BSE files when an accessible all-security product is qualified. Where only per-scrip BSE input is available, support the existing manual route; do not claim full BSE coverage.
- **Delivery:** treat each exchange's delivery data as its own observation and source table. Join only through same-venue, date-effective listing identity. Missing remains missing; no implied zero or cross-venue aggregation.
- **Corporate actions:** retain TejHQ action rows as secondary candidate events with TejHQ source lineage, subject to matching an authoritative exchange/company notice. Do not consume TejHQ adjusted prices for historical screens: the reviewed factors are retrospective and lack HAMSA's required publication timestamps/revision lineage; some action types have neutral/no factor handling.
- **Historical symbol/ISIN:** TejHQ mappings are leads for manual mapping review, never automatic security merges. Pre-ISIN and heuristic-chain records remain unresolved until authoritative mapping evidence exists.

## Reconciliation required before broad use

The inspected dataset revision was updated through 2026-11-06. HAMSA's local NSE and BSE representative source files are dated 2026-11-09, so no same-date comparison was possible in this review. Before scaling:

1. Obtain one exchange/year Parquet file per venue at a pinned dataset revision; do not download the full dataset as the first step.
2. Inspect actual file bytes, Parquet physical schema, row count, minimum/maximum dates, null distributions, duplicate keys, and partition behavior. Compare those against the public preview.
3. For overlapping sessions, match a sample by ISIN/listing/session to original official files, compare OHLC, volume, traded value, and delivery separately, and investigate every mismatch. Do not convert rounding differences into silent tolerance or data corrections.
4. Reconcile expected eligible securities and sessions against the official security master/classification snapshots; report missing, extra, unresolved, SME, and non-equity rows separately.
5. Test duplicate file import, changed file/repository revision, parser revision, crash/recovery, and `public_as_of` versus `hamsa_known_as_of` using actual sample files.
6. Maintain a source-coverage matrix by venue, session, listing, field, identity state, and acceptance/quarantine reason. Do not announce coverage from a published date range alone.

No implementation or parity test is claimed complete by this recommendation.

## Practical implementation sequence

1. **Pin and qualify a small TejHQ sample.** Select one file per venue and a narrow date overlap; archive exact bytes, inspect schema/units/nulls, and compare rows with official source files. Resolve the TejHQ terms/source-rights gate before making routine production imports.
2. **Complete current official classification/master snapshots.** Preserve source snapshot date separately from listing effective date. Keep unresolved classifications out of the eligible universe.
3. **Add a narrow Parquet adapter at the ingestion boundary.** It should read local files into adapter-neutral source rows and call existing archive, validation, mapping, quarantine and repository APIs. No TejHQ application dependency is needed.
4. **Backfill a bounded interval, then expand by explicit coverage batches.** Use only reviewed mainboard mappings; preserve unresolved pre-2012 NSE rows in quarantine/coverage counts instead of guessing ISINs.
5. **Run daily official-file ingestion in parallel.** Keep it authoritative for current EOD. Add BSE full-market daily coverage only after an official source file/product and its identifier join have been validated; otherwise clearly report per-scrip-only coverage.
6. **Build source/session/listing reconciliation reporting.** Show accepted, missing, duplicate, conflict, out-of-scope, and unresolved rows by exchange and date before any screening engine consumes them.
7. **Only later assess historical point-in-time events and adjusted series.** Reconstruct factors from sourced, versioned corporate-action notices with publication timestamps; never inherit retrospective factors as historical screen inputs.

## Coverage limitations that remain

- TejHQ publishes NSE history from 2010, while the preview demonstrates some older rows; neither proves complete security/session coverage.
- TejHQ BSE history begins at the 2024-07-08 modern cutover; older BSE coverage is not established by this dataset.
- Pre-2012 NSE ISINs may be null; TejHQ's symbol-based backfill/chain is not sufficient for HAMSA identity.
- The dataset's series filtering does not prove mainboard ordinary-equity eligibility or reliably exclude ETFs/non-equity instruments.
- Historical listing effectiveness, delisted universe completeness, corporate-action publication-time history, and daily availability guarantees are not established.
- The dataset preview was available only through 2026-11-06 at review time; no 2026-11-09 TejHQ comparison was performed.
- TejHQ's own terms do not settle exchange data rights.

## Scope and recommendation summary

Use TejHQ as a **candidate historical Parquet source**, not as HAMSA's provider of truth. Reuse the dataset, not the downloader or inferred identity/adjustment rules. Keep HAMSA's ingestion architecture, official-file daily path, independent classification snapshots, provenance, and point-in-time rules. Start with a file-level sample qualification and an auditable reconciliation report; widen historical ingestion only after the sample passes identity, quality, and source-rights review.
