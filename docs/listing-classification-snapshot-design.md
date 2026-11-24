# Listing Classification Snapshot Design

**Status:** Proposed design only. No schema or repository changes are included in this milestone.

## Goal and separation of facts

HAMSA needs a sourced, reviewable answer to “how was this exchange listing classified in this dated master/source snapshot?” Current `exchange_listing_revision` instead represents effective-dated symbol, series and listing status; its required `effective_from` cannot be populated from a master snapshot date without inventing an effective date.

Keep four axes separate:

1. **Identity:** `exchange_listing` → existing `security_id`, exchange and exchange instrument reference.
2. **Effective history:** existing `exchange_listing_revision` for symbol/series and status only when the effective interval is sourced.
3. **Snapshot observation:** immutable raw and normalized classification facts observed in an official source snapshot, dated by `source_snapshot_date`.
4. **Review history:** append-only human approval/rejection/pending events for the interpretation of the snapshot and, separately, for effective-dated listing revisions.

No new issuer or security entities are introduced. One ISIN may resolve to one reviewed security with separate NSE and BSE listing IDs; snapshot classifications attach to the venue listing and are not merged across venues.

## Proposed records

### A. `listing_classification_snapshot`

One immutable record per listing/source-document/extraction row. Candidate fields:

| Field | Purpose |
| --- | --- |
| `listing_classification_snapshot_id` PK | Stable observation identifier. |
| `listing_id` FK → `exchange_listing` | Venue-specific subject; source exchange must match the listing. |
| `source_document_id` FK → `source_document_revision` | Exact archived master/official page/document revision. |
| `source_snapshot_date` DATE NOT NULL | Date the source says its contents describe; never copied into `effective_from` by default. |
| `source_published_at` / `source_publication_date` | Source availability timing, using the source-document record when known. |
| `extraction_timestamp`, `parser_version`, `extraction_locator` | Reproducible field-level lineage. The locator should identify the CSV row / member / page location. |
| `source_identifier`, `checksum_sha256` | Repeated or FK-derived provenance values if the chosen schema pattern requires observation-level lineage. |
| `raw_classification_fields` JSON | Source field names and exact values, including unrecognized codes; no lossy normalization. |
| `raw_isin`, `raw_exchange_instrument_id`, `raw_symbol`, `raw_series` | Exact identifiers at that source snapshot for reconciliation. |
| `instrument_class` | HAMSA normalized class: `ordinary_equity`, `etf`, `mutual_fund`, `reit`, `invit`, `preference`, `warrant`, `rights`, `debt`, `other`, `unknown`. |
| `platform_class` | HAMSA normalized class: `mainboard`, `sme`, `other_platform`, `unknown`. |
| `listing_status` | Normalized source observation: `listed_trading`, `listed_nontrading`, `suspended`, `inactive`, `delisted`, `unknown`. Preserve finer raw fields. |
| `universe_disposition` | One of the five mutually exclusive dispositions in `mainboard-classification-rules.md`. |
| `classification_rule_version` | Identifies the reviewed source mapping/rule set used to derive the normalized dimensions. |
| `supersedes_snapshot_id` self-FK nullable | Explicit lineage when a later source document corrects/replaces an earlier classification observation. A later ordinary daily snapshot can link as superseding observation where appropriate, without deleting either. |

Candidate uniqueness: `(listing_id, source_document_id, extraction_locator)`. Do not make `(listing_id, source_snapshot_date)` unique: a source can publish a corrected/revised file for the same date, and the revision must remain visible.

The table records a *snapshot observation*, not an interval. There is no `effective_from` or `effective_to` in this table.

### B. `listing_classification_review_revision`

Append-only review decisions attached to a classification snapshot:

- `review_revision_id` PK;
- `listing_classification_snapshot_id` FK;
- review status: `pending`, `approved`, or `rejected`;
- reviewer, reviewed timestamp, rationale, evidence references;
- reviewed normalized dimension/disposition or an explicit confirmation of the proposed values;
- `supersedes_review_revision_id` self-FK.

The current review state is the leaf review event; prior states are retained. Only a latest approved review can produce an eligible current-universe listing. No qualitative interpretation is automated.

### C. `exchange_listing_revision_review`

Separate append-only audit trail for the existing effective-dated `exchange_listing_revision` records, because that table has no review status:

- review ID PK, `listing_revision_id` FK, status (`pending`/`approved`/`rejected`), reviewer/time, rationale and evidence source references, superseding review ID.

This avoids changing the historical identity row's meaning and permits later audits of symbol/status interval decisions. A classification approval cannot automatically approve a historical listing effective date, and vice versa.

## Snapshot decision function

The repository resolves normalized dimensions from source-specific, versioned mapping rules and then applies the published decision precedence:

```text
if official platform is SME/Emerge:       Excluded SME/Emerge
elif official instrument is non-equity:   Excluded non-equity
elif official listing is inactive:        Excluded inactive/non-trading listing
elif ordinary equity + mainboard + active: Eligible mainboard ordinary equity
else:                                     Unresolved classification
```

Conflict, invalid mapping, unknown source code, missing required dimension, unreviewed mapping, or incomplete source row forces `Unresolved classification`, even if some fields resemble an eligible security. The first three exclusions are only assigned from verified evidence; no default follows from absence of a positive field.

### Eligibility query constraints

- Source document provider/exchange must match `exchange_listing.exchange` (repository cross-table validation).
- `source_snapshot_date` must equal the source document's explicit `source_as_of_date` when one exists; a disagreement is quarantined, not resolved by choosing one.
- The source record must identify one listing by reviewed exchange instrument reference and verified ISIN mapping; ambiguous or missing ISIN is not silently joined by name/symbol.
- The latest snapshot only supplies current observed membership as of that snapshot. It never starts a listing interval.
- Current-eligible view requires an approved latest review and disposition `eligible_mainboard_ordinary_equity`; all other states stay out.
- Public availability and HAMSA-known availability remain governed by the existing publication/ingestion timestamps on source documents. A later correction is a new source/extraction/review record and cannot rewrite prior historical views.
- Supersession is lineage, not deletion. Choosing an active snapshot uses source-snapshot date, source revision, and explicit supersession; same-date unresolved competitors remain visible for review.

## Reviewer history and source traceability

Store every source snapshot as a `source_document_revision` against its archived `raw_source_file` (existing SHA-256 and archive path). Each normalized classification points to the source document and exact extraction locator; its raw code fields remain intact. Store the rule version used to interpret those codes. Review events cite the evidence and reviewer/time. Later rule changes or corrected exchange documents create new derived classification snapshots/review events; they do not rewrite the original observations.

Do not use `filter_review` for this purpose: it represents human investment-thesis filters, not exchange identity/classification approval. Do not put mainboard classification in `issuer_classification_revision`, which describes business type/sector, not a venue listing's regulatory platform.

## Lifecycle behavior

- **Current mainboard listing:** insert source snapshot and source fields. If board, instrument and status are all verified, create an approved decision for that snapshot; otherwise leave pending/unresolved.
- **SME-to-mainboard migration:** keep pre-migration SME classification snapshots and listing history. Add a new classification snapshot tied to an official notice/master source for the new state. A distinct sourced effective migration/listing date may be recorded in the appropriate effective-dated listing or relationship history after review. Eligibility starts at that effective date, not at the later master snapshot date. Snapshot approval does not backfill prior dates.
- **Mainboard-to-SME or other reclassification:** retain the prior mainboard snapshots; add a new snapshot and independently verified effective event. Current eligibility changes only from that event's sourced effective date. If such a change is not supported by official evidence, quarantine the conflict rather than infer it.
- **Rename:** preserve raw symbol per snapshot. Update `exchange_listing_revision` only with a sourced effective date; keep listing/security IDs stable where the official instrument identity supports continuity.
- **ISIN change:** preserve the raw ISIN seen in each snapshot. Resolve a routine same-issuer identifier change through existing reviewed identifier mappings; do not infer continuity or merge price/financial histories. If a new security/listing is created, retain it separately and relate it only through an explicit reviewed mapping/relationship.
- **Suspension:** new snapshot states the venue listing is not currently trading; mark disposition excluded inactive/non-trading for the observed snapshot. Do not delete earlier active snapshots or rewrite their historical state.
- **Relisting/readmission:** new status observation with readmission/listing notice evidence. Restore current eligibility only after approved positive platform/instrument/status facts and effective-date evidence; maintain old delisted/suspended history.
- **Conflicting NSE and BSE snapshots:** keep separate observations because they describe separate listings and venue status can differ. Do not average or collapse status. A direct contradiction about shared security/instrument class is surfaced for review; do not automatically pick a winner.
- **Missing/invalid ISIN:** store raw row and provenance, quarantine or leave identity unresolved, and exclude from the canonical eligible universe until reviewed. Never use company name/symbol similarity as a substitute identity key.

## Data model fit

The design extends the existing `exchange_listing` identity and provenance graph. It does not alter `effective_from` semantics, add issuer/security duplicates, or modify price/financial history keys. The 3 proposed tables add typed snapshot facts plus append-only classification/listing-review decisions. If a later implementation finds the existing registry/provenance pattern can host these rows without loss, the table count can be reduced, but no source-document JSON blob alone should substitute for queryable, constrained normalized snapshot facts.
