# HAMSA architecture and data boundaries

HAMSA is a local **Investment Research and Portfolio Intelligence System**. The
original end-of-day opportunity screener remains a core module, with its five
planned discovery engines (Compounders, Earnings Inflection, Capex Conversion,
Cash Quality, and Extreme Sell-Side Liquidity). Research and portfolio modules
consume the same sourced, point-in-time data while remaining independently
reviewable. No module produces automatic buy/sell recommendations.

## Identity layers

- `issuer_entity` is a stable internal identity for a legal issuer. Routine symbol or ISIN changes do not create a new issuer entity; sourced, effective-dated mapping revisions retain that ID.
- `equity_security` represents a specific share security. Its ISIN assignments are effective-dated and source-backed. NSE and BSE listings for the same ISIN resolve to the same security.
- `exchange_listing` is venue-specific and retains the exchange instrument code, symbol/series revisions, and active/suspended/delisted/relisted lifecycle.
- A listing identity is scoped to exchange, instrument reference, and security identity; symbol changes remain revisions on the same listing, while a changed ISIN can map to a distinct security/listing without reusing the predecessor's history.
- A merger, demerger, reorganization, predecessor/successor, or spun-out relationship is a separate sourced and reviewed relationship. It does not merge entity, financial, or price histories. Changed identifiers are never resolved by name similarity.
- Broker account, mandate, position, and transaction are separate portfolio identities. A position references a company/security and one broker account, and records its investing or trading mandate. The same company can have multiple independent positions, including separate investing and trading positions.

## Product modules and boundaries

- **Opportunity Screener:** the five discovery engines operate on EOD data and configurable, versioned rules. Their calculations expose exact inputs, formula, source, venue policy, and as-of date. They identify research candidates and never issue buy/sell recommendations.
- **Company Intelligence Dossier:** company-level business thesis, Hamsa 11 human assessments, evidence citations, financial/capacity history, dated triggers, thesis killers, and review history. Hamsa 11 statuses are Pass / Unproven / Fail and remain human-entered; evidence and review records are append-only.
- **Portfolio Intelligence:** locally imported user-supplied broker CSV holdings and tradebooks, supporting multiple brokers and accounts. Reconstructed positions derive from immutable transactions and reviewed corporate actions. Holdings snapshots reconcile against reconstructed positions; they never fill gaps in transaction history. No broker API or credential storage is in scope.
- **Position and Capital Allocation Monitor:** a position belongs to one company/security, account, and mandate, and has its own thesis, entry history, risk rules, and exit logic. Capital deployments, trims, re-entries, exits, sizing, concentration, alternatives, recycling, status, and checkpoints are tracked per position. Investing/trading P&L and capital flows remain separate unless the user explicitly requests a consolidated view.
- **Performance Analytics:** realized/unrealized return, average cost, drawdown/recovery, account and position attribution, capital turnover, and recycling efficiency. XIRR or time-weighted returns are selected where their cash-flow assumptions fit and are explained with calculation inputs.
- **Market and Event Intelligence:** sourced exchange filings/results, ownership changes, block/bulk deals, corporate actions, and company milestones, with publication-time eligibility and reviewed event classification.

Company-level research is distinct from position-level decisions. A company dossier may inform several independent positions, but a position's mandate, thesis, entry history, risk limits, and exit logic are never merged. Consolidation is an explicit presentation choice and preserves constituent account/mandate attribution.

## Temporal and as-reported rules

All screen cutoffs are 15:30 `Asia/Kolkata` on an exchange session. The versioned exchange calendar, including holidays and special sessions, determines eligible session dates. Publication eligibility is recorded using both raw publication date/timestamp and the calendar version used to calculate the first eligible session:

- Reliable timestamp at or before 15:30 IST on a trading session: eligible that session.
- Timestamp after cutoff or on a non-trading date: eligible on the next exchange trading session.
- Date-only publication with no reliable time: eligible on the next exchange trading session after that date.

Historical snapshots support two modes. `public_as_of` asks what was publicly available by the cutoff and may use an archival backfill acquired later. `hamsa_known_as_of` additionally requires ingestion by the cutoff. Both modes require public availability; neither admits private/unpublished facts. Screen runs record session, cutoff, mode, and calendar version. This prevents retrospective backfills from appearing in HAMSA-known history.

Every financial revision retains `period_end`, source document date, publication date and precision, optional reliable publication timestamp, ingestion timestamp, source revision/version, as-reported classification, quality state, and source lineage. Original facts and superseded revisions remain stored.

## Corporate actions and price history

Raw EOD prices and venue-specific delivery observations are append-only. Splits, bonuses, rights, mergers, demergers, identifier/symbol changes, suspensions, delistings, and relistings are corporate-action event revisions with separately stored announcement/publication timestamp, ex-date, record date, and effective date.

Adjustment factors are separate versioned records with formula version, complete event terms, reviewer approval, publication availability, and all input/source references. No factor is produced when terms are incomplete or methodology is unreviewed. A historical screen can use only factors public by its cutoff and effective by its date. A retrospective return series may use subsequently confirmed factors, with `retrospective` mode recorded. Adjustments always derive a view; raw prices are never overwritten. Merger/demerger histories remain separate unless a reviewed calculation explicitly defines a linked return.

Portfolio reconstruction applies corporate actions only through sourced, reviewed transaction/reconstruction rules. Unresolved terms or successor mappings create reconciliation exceptions; they do not silently rewrite predecessor positions or join successor histories.

## Venue and liquidity policy

Every future screen profile must reference a versioned venue policy. Price selection uses configured primary exchange and explicit fallback only; NSE and BSE prices are never averaged. Combined volume and traded value are permitted only for same-security, same-session, valid, comparable observations under an explicit policy and formula. Venue-level observations remain preserved. Delivery quantities and percentages remain venue-specific; they are not combined or treated as interchangeable.

## Provenance and revisions

Raw source files are checksum-addressed and immutable. Source documents have provider/dataset-scoped identifiers, checksum, revision number, publication/document dates, and supersession links. Repeated sightings of exact bytes are recorded without duplicating normalized observations; changed bytes create a revision.

Each normalized row carries its source document, source identifier/checksum, parser version, extraction timestamp, and locator. Derived rows additionally carry formula version and input observation references. Quarantine records preserve the source and locator for unresolved mappings, incompatible units, incomplete event terms, invalid rows, and unresolved conflicts.

## Quality, nulls, units, and freshness

Quality states are separate: `observed`, `missing`, `stale`, `invalid`, `conflicted`, and `not_applicable`. Null remains null and is never silently made zero. Conflicting values remain visible and are not averaged or automatically selected. Invalid/ambiguous rows are quarantined. Staleness windows are versioned by metric and source; no freshness assertion is made where no reviewed policy exists.

Canonical units are INR/share for prices, INR for monetary amounts and turnover, shares for quantities, percentage points for percentages, `x` for ratios, and calendar days for durations. Metric definitions identify dimensions. Any conversion preserves raw value/unit and records the approved conversion rule revision. Unknown or incompatible conversions are quarantined.

## Storage and module boundaries

- DuckDB stores analytical revisions, observations, provenance, factors, and screen snapshots.
- SQLite stores app settings and the append-only human dossier review ledger.
- `providers/` will contain replaceable NSE/BSE/company adapters; ingestion consumes adapter-neutral records.
- `domain/`, `ingestion/`, `storage/`, and `screening/` remain independent of Streamlit.
- Future portfolio modules will use separate company/security, broker/account, position, and transaction repositories. A reconstruction service will consume immutable transactions plus versioned corporate-action rules; a reconciliation service will compare results with broker holdings snapshots without fabricating trades.
- Local CSV import is the initial broker boundary. Imported originals, checksums, parser/extraction provenance, row-level quarantine, and user-selected account/mandate mapping are retained. The application stores no broker credentials and makes no broker API calls in this scope.
- Dossier evidence links to source documents and observations; portfolio analytics links to position transactions, cash flows, and reconstruction version. Neither changes the five-engine screening boundary.
- No provider, dashboard, or five screening engines are implemented in this milestone.

Raw data, local databases, secrets, credentials, keys/certificates, logs, caches, and virtual environments are excluded by `.gitignore`. Only code, SQL schemas, docs, policy examples, and synthetic fixtures belong in Git.

## Enforcement boundaries

DuckDB enforces row-local types, primary/unique keys, foreign keys, check constraints, and typed composite references for observation lineage and screen-result evidence. Those constraints reject invalid IDs/types and malformed local values. Schema metadata and migration records identify the expected version and baseline checksum.

The DuckDB repository is the ordinary application write boundary. It exposes append methods, not generic update/delete methods. Corrections append new observations and supersession links. Before a write, it validates source-document consistency, metric/canonical-unit agreement, same-natural-key revision chains (including `period_start`), monotonic revision numbers, and non-branching supersession. Registry, observation, and lineage rows are written transactionally. Future repository operations must also validate interval overlap, calendar-based eligibility, conversion-rule dimensions/status, complete corporate-action terms, and archive bytes/checksums where applicable.

DuckDB does not enforce append-only history against a database owner. Direct SQL access can update/delete rows, bypass repository checks, or remove triggers. DuckDB triggers are not used for immutability: supported triggers run actions after changes, and DuckDB 2.0 does not support row-level update triggers. SQLite's human dossier review ledger retains separate database triggers that abort review/evidence updates and deletes; those guards are tested independently.

## Replaceable policy interfaces

`TradingCalendarProvider` returns sourced, versioned exchange sessions for explicit date ranges. `UnitConversionPolicy` resolves a reviewed conversion rule or returns no rule. `FreshnessPolicyProvider` resolves a reviewed metric/source age rule as of a date or returns no rule. These interfaces define no source coverage, conversion factors, calendar content, or stale-age defaults; missing policy is unresolved and must not be guessed.
