# HAMSA Provider Admission Checklist

**Purpose:** fail-closed gate before enabling any external market-data provider.
**Status:** process definition only. No provider is approved or activated by this document.

## Admission rule

A provider cannot be activated until every mandatory gate below is **Pass** for the exact provider, product, account, fields, delivery channel, intended user and use case. “Pending,” “Unproven,” a sales statement, public accessibility or a working endpoint does not count as approval. If scope changes or terms change, re-run the affected gates before continued use.

Each completed review must record evidence and reviewer/date. A source permission only admits the data product and activities that are explicitly covered; it does not imply rights for other categories or distribution.

## 1. Provider identity and source provenance

- [ ] Legal provider, contracting entity, product name, product version, data source(s), venue(s) and source-of-record role are identified.
- [ ] Product contract, terms, policy, data dictionary and technical specification are retained with version/effective date and checksum in approved local records.
- [ ] Permitted fields, securities, exchanges, segments, frequency and date ranges are itemized.
- [ ] Product states whether data is direct exchange data, vendor-consolidated data, derived data, evaluated price or issuer-reported information.
- [ ] Stable source record/filing identifiers, source timestamps, revisions and field definitions are documented.
- [ ] Any evaluation/sample data has documented permission for the evaluation method and retention period.

**Evidence:** executed contract or written license schedule; product manifest; sample specification; provider confirmation of source and revision fields.

## 2. Officially supported access method

- [ ] The transport is officially documented and authorized for this product (for example, licensed SFTP, documented API, documented feed or licensed file delivery).
- [ ] No undocumented endpoints, reverse-engineered interfaces, scraped pages or credentials borrowed from another product/account are used.
- [ ] Authentication method, credential owner, credential storage/rotation, IP allowlists, encryption and security responsibilities are approved.
- [ ] Documented rate limits, concurrency, batch size, date range, polling frequency, retry/backoff, pagination and support channels are known.
- [ ] The intended automated daily retrieval is expressly allowed under the agreement, including any restrictions on unattended jobs.
- [ ] Access is restricted to **end-of-day and historical** data. Intraday/live, streaming, order-book and real-time paths are disabled for HAMSA.

**Evidence:** current provider API/file manual, named account/product entitlement, written authorization for unattended EOD retrieval and recorded configured limits.

## 3. Licensing and intended use

For each activity mark **Permitted**, **Prohibited**, or **Requires additional approval/license**. Do not infer permission from a general subscription or browser download.

- [ ] Personal noncommercial research.
- [ ] Internal commercial research and decision support.
- [ ] Automated daily retrieval.
- [ ] Historical bulk download/backfill.
- [ ] Local raw-file archive and normalized local database.
- [ ] Database backups, disaster recovery, offline copies, replicas and retention after termination.
- [ ] Derived calculations, factors, ratios, screening flags, scores, charts and source-linked research dossiers.
- [ ] Internal single-user display and multi-user/group-company access.
- [ ] Paid research distribution, client reports, public website/app, API output, raw redistribution and derived-data publication.
- [ ] Use of data in machine-learning/AI tools or model training, if applicable.
- [ ] Attribution, delay, audit, security, user-count, deletion and downstream-recipient obligations are documented.

**Mandatory evidence:** executed agreement or written license confirmation from an authorized provider contact covering the chosen use case and storage/redistribution rights. If a necessary right is not explicit, mark it unresolved and block activation.

## 4. Historical coverage and point-in-time suitability

- [ ] Provider supplies a coverage manifest with earliest/latest dates by field, security and venue, including inactive, suspended, delisted, relisted and SME instruments where applicable.
- [ ] Security-master history includes dated identifiers, effective dates, listing status and historical symbol/ISIN mappings or clearly documents gaps.
- [ ] Filing/financial data distinguishes period end, publication timestamp/date, document date, source revision and vendor ingestion/availability time where supplied.
- [ ] Correction, restatement, vendor revision and history backfill behavior is documented; prior versions remain retrievable or the limitation is understood and accepted.
- [ ] For every signal, data was publicly available by the HAMSA 15:30 Asia/Kolkata cutoff and by the applicable exchange trading session.
- [ ] Separate `public_as_of` and `hamsa_known_as_of` replay semantics can be maintained; later backfills cannot leak into the earlier HAMSA-known view.
- [ ] Adjusted price series and corporate-action factors are versioned, reproducible and not applied before the action information was public.

**Evidence:** coverage manifest, sample historical series and lifecycle/correction examples acquired under permitted evaluation terms.

## 5. Field definitions and data quality

- [ ] Field-level data dictionary specifies units, currency, precision, exchange/venue, session, close definition, volume/turnover meaning, delivery denominator, missing-value representation and adjustment status.
- [ ] Each conversion to canonical units has a written rule/version; original raw value and unit remain preserved.
- [ ] Historical missing dates/securities and no-trade/suspension states are distinct from zero.
- [ ] Stale, invalid, conflict, missing and not-applicable states are represented separately; no silent null-to-zero conversion exists.
- [ ] Duplicate filings/rows, repeated files and amended source documents have deterministic identity/revision rules.
- [ ] Conflicting data from NSE, BSE or third parties remain separately sourced; no price averaging or undocumented winner selection occurs.
- [ ] Corporate-action event types, source terms, publication time, ex/record/effective dates and adjustment methodology are documented; incomplete terms are quarantined.
- [ ] Financial-company screening fields are distinguished from industrial-company fields and accounting bases.
- [ ] Capex-heavy companies are not excluded solely for weak current ROCE/FCF; this remains screening logic to be implemented separately.
- [ ] Yahoo or any non-primary provider is not used to establish exchange volume, venue identity, ISIN history or forced-selling evidence without validated rights and methodology.

**Evidence:** approved source-to-field map; synthetic or licensed sample validation report; unresolved-field list and quarantine procedures.

## 6. Identity and venue integrity

- [ ] Canonical issuer, security and exchange listing are separate entities in the provider mapping plan.
- [ ] Same-issuer routine ISIN/symbol changes use sourced effective-dated mappings.
- [ ] Merger, demerger, scheme, successor and predecessor relationships are explicit reviewed links; no price or financial history is automatically merged across entities.
- [ ] NSE and BSE instrument references remain venue-specific even when the ISIN is shared.
- [ ] Ambiguous mappings and multiple candidate securities are quarantined pending review.
- [ ] Provider ticker/scrip code aliases are not treated as canonical identity.

**Evidence:** historical mapping samples, provenance references, exception queue and reviewer assignment.

## 7. Failure, retry and reconciliation procedures

- [ ] Expected file/API schedule, exchange calendar, special-session behavior and time zone are documented.
- [ ] Late/missing file behavior is defined; retries are idempotent and cannot create duplicate observations or revisions.
- [ ] Crash recovery covers raw archived/database uncommitted, database committed/archive status stale, timeout/partial response and duplicate retry cases.
- [ ] Source correction/republication produces append-only new revisions and lineage; no silent overwrite or deletion is performed.
- [ ] Per-product reconciliation checks row counts, date coverage, schema, totals, duplicate rows, invalid values and source checksums.
- [ ] Cross-venue reconciliation retains independent values; any combined volume/value rule explicitly records both venue observations and formula version.
- [ ] Source-health and freshness monitoring can suppress affected signals rather than carrying forward stale closes or substituting zeros.
- [ ] Provider outage, credential expiry, contract suspension and license termination paths can disable ingestion and prevent unauthorized use.
- [ ] A replay of an approved source archive into a clean database can reproduce normalized observations and lineage.

**Evidence:** written operations runbook, recovery test results and reconciliation example. Tests require the appropriate approved sample data or synthetic fixtures; do not call a provider before licensing approval.

## 8. Provenance and retention

- [ ] Original source file/document is retained only where permitted and linked by immutable checksum/source ID.
- [ ] Every normalized or derived record stores source-document reference, parser/extraction version, extraction timestamp/location, original value/unit, conversion rule and formula version as applicable.
- [ ] Source publication timestamp/date, document date, HAMSA actual ingestion timestamp and as-reported revision are separate fields.
- [ ] Superseded records and review history are append-only at the repository interface; corrections create new revisions with lineage.
- [ ] Retention, backup, end-of-contract deletion, audit and credential-handling requirements are implemented and documented.
- [ ] Raw data, local databases, credentials, API keys and sensitive contracts are excluded from public Git unless explicitly permitted; configuration examples contain no secrets.

**Evidence:** provenance review, storage-permission clause and tested repository controls.

## 9. Written admission decision

For each provider/product, record:

| Field | Required value |
|---|---|
| Provider / contracting entity | Exact legal entity |
| Product / version | Exact named product and terms version |
| Intended HAMSA use | Personal, internal commercial, external distribution, or combination |
| Permitted data/frequency | Explicit field, venue and EOD-only scope |
| Supported access route | Exact documented SFTP/API/file method and limits |
| Coverage evidence | Start/end date, security universe, field gaps and lifecycle coverage |
| Storage/retention | Raw, normalized, revision, backup and deletion rights |
| Output rights | Derived metrics, display, publication and redistribution terms |
| Quality and failure controls | Validation, revisions, stale/missing/conflict and recovery procedure |
| Approver and review date | HAMSA owner, legal/procurement reviewer as applicable |
| Decision | **Admitted**, **Rejected**, or **Unresolved** with rationale |

## 10. Activation checklist

Activation is allowed only if all gates above pass and the owner signs the record below.

- [ ] No licensing question affecting selected use remains unanswered.
- [ ] No required source category depends on an undocumented endpoint or non-approved scraping.
- [ ] The configured provider is EOD-only and its actual requests cannot reach live/intraday functionality.
- [ ] All rows in “Licensing and intended use” are resolved for HAMSA's actual use.
- [ ] Coverage, mappings, schema, units and revision behavior meet the explicitly approved minimum.
- [ ] Reconciliation, retry, failure and archive replay procedures are ready.
- [ ] Provenance, immutable revisions, storage retention and security controls are ready.
- [ ] Required synthetic/integration tests pass using approved test material.
- [ ] Owner has documented approval for this exact provider/product and environment.

**Provider / product:**
**Decision:** Admitted / Rejected / Unresolved
**Decision date:**
**Approver:**
**Evidence/contract reference:**
**Scope and exceptions:**

Any unchecked mandatory item means **do not activate**.
