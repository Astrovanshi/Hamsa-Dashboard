# Revised data model

`sql/duckdb_schema.sql` is the analytical schema; `sql/sqlite_schema.sql` is the local dossier/app schema. Both are append-oriented. The schema contains no external data.

## Future portfolio model (documentation only)

This section describes the approved product boundary; it does not claim these
tables or modules exist in the current schema. Portfolio implementation requires
a separately reviewed schema milestone.

- **Company / issuer** remains the research identity; **security** is the share
  instrument; **listing** is its venue-specific instrument reference.
- **Broker** and **broker account** identify where a source snapshot or
  transaction originated. A user may import multiple accounts across multiple
  brokers. CSV files are user-supplied and local; no broker connection,
  credentials, or guessed account identity is introduced.
- **Mandate** separates investing from trading. **Position** is an independent
  company/security + account + mandate thesis/holding stream. A company can
  therefore have several positions, including investing and trading positions
  in the same account or different accounts. Each position owns its own thesis,
  entry history, risk rules, review checkpoints, and exit logic.
- **Transaction** is an immutable imported or manually reviewed ledger event
  (trade, fee, tax, dividend, cash movement, or reviewed corporate-action
  allocation, as supported by a future schema). Position quantity, average cost,
  realized/unrealized P&L, trims, and re-entries are reproducibly reconstructed
  from the transaction ledger and a versioned reconstruction method. A holdings
  snapshot is a reconciliation input only: it must never be used to infer
  missing transactions or fabricate transaction history.
- **Holdings snapshot / reconciliation** retains the original broker CSV and
  maps each source row to an account/security with explicit import decisions.
  Differences from reconstructed positions become visible reconciliation
  exceptions for review; they do not overwrite ledger-derived positions.
- **Position analytics** retains mandate/account attribution. Investing and
  trading P&L and capital flows remain separate. A consolidated presentation is
  opt-in and must preserve the underlying account and mandate detail.

The planned Company Intelligence Dossier is company-level and includes human
Hamsa 11 assessments, evidence/source citations, business thesis and thesis
killers, earnings/cash-flow/debt/capex/capacity-utilisation history, dated
triggers, and review history. Capital allocation events (deployments, trims,
re-entries, exits, alternative opportunities, and recycling) reference
positions and review checkpoints rather than collapsing positions by company.
Performance analytics will calculate realized and unrealized returns,
drawdown/recovery, position/account attribution, turnover, and recycling
efficiency; XIRR and time-weighted return are used only with explicit suitable
cash-flow inputs and methodology. Market/event records link to sourced exchange
filings, results, ownership changes, block/bulk deals, corporate actions, and
business milestones.

## Identity and security lifecycle

`issuer_entity` is the stable legal-issuer identity. `equity_security` identifies a share security owned by an issuer. `security_identifier_revision` maps ISINs to securities over effective dates with a sourced review state. Thus one ISIN listed on two exchanges resolves to one security, while a routine ISIN/symbol change can retain the issuer ID and preserve the mapping history.

`exchange_listing` and `exchange_listing_revision` retain venue instrument IDs, symbol/series history, and listing status. `entity_relationship_revision` and `security_relationship_revision` store reviewed predecessor/successor, merger, demerger, spin-out, and identifier-change relationships. Reorganizations do not merge historic financial or price rows.

## Source files, documents, and lineage

- `raw_source_file`: immutable original file path, SHA-256, provider/dataset, source as-of date, capture time, licensing review reference/status.
- `source_document_revision`: provider + dataset + source identifier, checksum, source/document/publication dates, reliable publication timestamp, ingestion and extraction timestamps, parser version/location, revision, and supersession reference.
- `source_document_sighting`: duplicate sightings of source identifiers/checksums without treating changed bytes as identical.
- `observation_lineage_input`: formula-versioned links from derived observations to input observations. Observation tables also store direct source-document, parser, extraction, and locator references.
- `observation_quarantine`: reason-coded unresolved or invalid rows linked to their document and extraction location.

The source-document revision key is scoped by provider, dataset, source identifier, and revision number. Exact same-source bytes are idempotent. New bytes for an existing document require a new revision and retain the prior revision.

## Financial observations and point-in-time views

`financial_observation_revision` stores issuer, metric and reporting scope; raw/canonical values and units; period start/end; source document date; publication date and precision; reliable publication timestamp where known; ingestion timestamp; revision number; original/restatement/recast/provider-backfill state; quality state; parser/extraction provenance; and superseded observation ID.

Availability follows the rules in [architecture.md](architecture.md). The snapshot function applies the versioned trading calendar to publication dates. It uses supersession chains to expose current eligible leaves and retains competing unsuperseded documents instead of choosing a winner. An optional parser-version selection reproduces a specific extraction of the same source bytes; each result retains its extraction revision and locator. `public_as_of` can use a later-acquired archival filing if it was public by the historical cutoff. `hamsa_known_as_of` additionally requires the actual ingestion timestamp to be at or before cutoff.

## Units and data quality

`canonical_unit`, `financial_metric_definition`, and `unit_conversion_rule_revision` define metric dimensions, canonical units, and reviewed conversions. Raw values and units stay stored next to canonical values. An unknown or incompatible conversion is quarantined.

Missing, stale, invalid, conflicted, and not-applicable are distinct statuses. No SQL default or application rule converts null to zero. Staleness is a revisioned metric/source policy. Quarantined records retain source/document and locator, allowing later review without losing the original input.

Canonical dimensions currently specified are INR/share for price, INR for monetary amounts and traded value, shares for quantity, percentage points for percent, `x` for ratio, and calendar days for duration. Metric-specific definitions must be added before normalization.

## EOD prices, delivery, and corporate actions

`eod_price_observation_revision` stores raw venue-specific OHLC, volume, and turnover observations, with source checksum, parser, extraction locator, quality status, and correction link. `delivery_observation_revision` independently stores each venue's delivery values.

`corporate_action_event_revision` stores action type, affected/resulting securities, source document, publication timestamp/date, source-document date, ex-date, record date, effective date, terms completeness, terms and event revision. `adjustment_factor_revision` stores factors only with complete terms and reviewed methodology, together with event/factor/formula versions, public availability, reviewer, and source inputs.

`adjusted_price_series_revision` states the basis date, factor set/version, formula, cutoff, and availability mode; `adjusted_price_factor_input` records every applied factor. Raw price rows are not updated. Screen-time factors must have been public by the screen cutoff and effective by that date. Retrospective factors may be included later only when terms and methodology are approved.

## Calendars and venue policies

`exchange_trading_session` versions each exchange calendar date, including special sessions and holidays. Each screen run records its calendar version and 15:30 Asia/Kolkata cutoff.

`venue_policy_revision` defines primary exchange, explicit fallback, and whether comparable trading activity may be combined. Price selection is never an average. Delivery remains separate by exchange; no delivery percentage aggregation is defined.

## Screening and dossier contracts

`screen_profile_revision` can reference financial/industrial rules and a venue policy. `screen_run` records point-in-time mode and cutoff. `screen_result` stores calculation, inputs, documents, and observation IDs. The five engines and dashboard are deliberately not implemented in this milestone.

The filter review ledger uses stable `entity_id`, with immutable reviews and evidence. Corrections append a new review linked to the earlier one. The eleven qualitative statuses remain human-entered.

The dossier's eleven human-entered filters are Gap, Choke Point, Turbo, Real
Buyers, Stack, Trigger, Jockey, Thin Float, Ceiling, What Kills It, and Extreme
Liquidity. Every filter supports Pass / Unproven / Fail with evidence, source
references, and review history. No qualitative judgment is automated.
