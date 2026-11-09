# HAMSA Provider Architecture Recommendation

**Assessment date:** 2026-11-10 (Asia/Kolkata)

**Decision status:** recommended architecture for review; no providers are activated and no external market data has been obtained.

## Recommendation

Build HAMSA around **official, venue-native NSE and BSE EOD observations**, plus **issuer/exchange-filed financials and corporate events**, behind replaceable provider adapters. Make source rights an explicit provider configuration gate. Preserve each venue's raw data separately and retain source revisions, publication and ingestion timestamps, effective-dated identifiers, extraction lineage and parser versions.

Do not require a commercial aggregator for the first usable version. A licensed third-party data service could reduce collection and normalization work, but it would not remove the need to preserve venue-specific source facts, point-in-time filing revisions, the official security lifecycle or the underlying license. HAMSA already requires NSE and BSE listings, separate venue observations, local reproducibility and human-reviewed identity/actions; those needs favor the exchanges as sources of record if the contracts permit local use.

The principal gating issue is **rights and delivery terms**, not library selection. NSE's public policy requires the relevant data agreement, prices commercial use, restricts redistribution unless agreed, and states that offline storage media are not permitted without prior approval. BSE's Self Data Feed likewise requires KYC, chosen plans, agreed price/agreement and payment. Obtain written permission for the specific local database, immutable archive, backup, derived metrics and user scope before enabling source retrieval. ([NSE policy](https://www.nseindia.com/static/market-data/nse-data-policy), [BSE Self Data Feed](https://marketdata.bseindia.com/))

## Minimum viable data-source combination

Subject to written rights, the minimum complete-source combination is:

1. **NSE official daily EOD and dated security masters** for NSE venue history, volume/value and delivery fields. NSE documents bhavcopy archives to March 1999 and historical month-end master snapshots from 1999, but exact current archive coverage and rights require confirmation. ([NSE historical archive description](https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf))
2. **BSE official daily EOD and dated scrip masters** for BSE venue history and BSE-exclusive listings. BSE documents daily EOD, historical trading data and a subscription API feed; exact oldest dates and archive fields need to be written into a coverage schedule. ([BSE Information Products tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf), [BSE Self Data Feed](https://marketdata.bseindia.com/))
3. **Exchange filings and original issuer documents** for announcements, results, shareholding, actions, pledges, bulk/block deals, annual reports and investor presentations. Use the exchange's filing identifier and published timestamp; store original source documents and every version where licensed. Extract normalized financial observations as reported; retain document-page/section provenance.
4. **Official trading-session calendars and special-session notices** from each exchange. Trading-day eligibility is determined from the corresponding exchange calendar, not weekday rules or the other venue's calendar.
5. **No data aggregator in the first MVP.** Use human-reviewed manual research for evidence not present in filings. Do not populate missing raw values with third-party estimates.

If the exchanges do not grant an acceptable local archive/database license, stop live ingestion and present the contract decision. A public report or “free/no-auth” interface is not a safe substitute for rights. The current NSE MCP historical server advertises five years of EOD data, but its disclaimer limits use to information/learning, excludes commercial use and does not establish durable archive rights; it does not satisfy the local history foundation. ([NSE MCP](https://www.nseindia.com/nse-mcp))

## Canonical provider assignment by category

| HAMSA data domain | Canonical source | Secondary check / fallback | Rules |
|---|---|---|---|
| Issuer/company identity | Issuer legal documents and sourced official exchange disclosures; maintain company entity independently from share security/listing | NSE/BSE dated masters; commercial vendor cross-reference only as a comparison | Routine symbol/ISIN change keeps same legal issuer ID only through sourced effective-dated mappings. Reorganizations require reviewed predecessor/successor links; never merge histories automatically. |
| Security and venue listing | Separate NSE and BSE exchange masters, each with source/effective dates and exchange IDs | A licensed LSEG/FactSet or CMIE mapping can flag a discrepancy but cannot replace primary dated exchange evidence | Retain NSE symbol/series/token and BSE scrip code/symbol as distinct listing references for the same ISIN/security. Quarantine uncertain ISIN changes or collisions. |
| Raw EOD OHLCV/turnover | Venue's own official EOD/bhavcopy: NSE for NSE observation; BSE for BSE observation | Other venue's row is a separate listing observation; Yahoo only a manual comparison if terms allow | No cross-venue price averaging. Each screening engine declares primary venue and explicit, labeled fallback. Retain raw prices permanently. |
| Liquidity and delivery | Official venue EOD trade-value/quantity and delivery report, stored separately by venue | Licensed vendor only to identify mismatches, with vendor field/source visible | Combined traded quantity/value only when same ISIN/session, valid observations, same currency/unit, compatible measure and both venues included intentionally. Never combine delivery percentages or silently change the venue. |
| Corporate-action events | Exchange corporate-action record plus issuer announcement and verified terms | LSEG/FactSet events can provide licensed second-source confirmation; Yahoo adjustment can flag a possible discrepancy only | Preserve announcement/publication timestamp separately from ex-date, record date, effective date. Adjustment factors are versioned and traceable to reviewed formula. No factor until terms/method are complete and public as of screen date. |
| Financial results and history | Company signed/filing source (exchange received filing or issuer report) with source document, period, publication timestamp and revision lineage | CMIE can help compare normalization only if rights permit; third-party standardized values never replace the source filing | Store standalone/consolidated separately; preserve original units; track as-reported revisions and public/known time independently. No backfilled value before publication/actual ingestion in the corresponding snapshot mode. |
| Announcements, ownership, pledges, insider trades | Exchange-disclosed filing and original attachment | Paid disclosure vendor only for cross-check and coverage-gap report | Keep filing event category, filing ID, publication/received time and amendments. Do not infer an insider trade or pledge state from shareholding alone. |
| Bulk/block deals | The exchange that publishes that deal record | Other exchange/vendor as corroboration only | Match venue, transaction date, filing/publication date, security and reported client fields. Do not interpret a disclosed deal as proof of ongoing ownership or durable demand. |
| Calendar | Official venue trading notices, special sessions and historic trading dates | Reconcile against actual report dates; vendor calendar may flag misses | Separate trading and settlement calendars. Every after-cutoff or date-only observation rolls to the next applicable exchange trading session. |
| Yahoo-derived values | None as canonical HAMSA field | Manual discrepancy review only, and only within permitted personal use | Provider symbol is an alias, never identity. Record Yahoo source/date/vintage if a manual check is allowed. Do not automatically load adjusted series or rely on it for liquidity. |

## Replaceable provider boundary

An adapter should implement only source transport and source-specific extraction. It must not contain screener rules, choose winners, make recommendations or silently normalize away source differences.

Every provider/product registration should include:

- Provider, legal entity, product and contract/terms version.
- Explicit permitted purpose, authorized user scope and intended HAMSA environment.
- EOD-only flag; allowed exchanges, data categories, fields, formats and date ranges.
- Automation permission, endpoint/file route, authentication method, documented request limits, polling schedule and service/failure SLA.
- Raw archive permission, retention period, backups, derivative retention, termination/deletion requirements and redistribution/display rights.
- Verified coverage start/end by security universe and field; coverage facts remain unknown unless the provider provides evidence.
- Publication timestamp semantics, timezone, date-only treatment, source corrections, historical revision and file version behavior.
- Stable filing/source IDs, extraction location, checksum and retrieval timestamp requirements.
- Parser and validation versions, declared units, field meaning, corporate-action adjustment indicator, and venue attribution.

Data rights should be separate from technical connectivity. A supported API is not an archival license, and a local download is not a redistribution license. Refuse to activate a provider if its configuration lacks explicit authorization for the intended activity.

### Adapter flow

```text
Approved product + terms
          |
          v
Provider adapter (transport, auth, source bytes, source IDs)
          |
          v
Immutable raw archive + checksum + retrieval metadata
          |
          v
Versioned parser/extractor + extraction location
          |
          v
Validation and quarantine (units, duplicates, conflicts, freshness)
          |
          v
Identity resolution (effective-dated listing/ISIN; reviewed relationships)
          |
          v
Append-only DuckDB observations and lineage
          |
          v
Source-specific repository projections -> historical snapshot/screening
```

The normalized layer should retain provider-original values and units, canonical unit conversion rule/version, observation state, venue, effective security/listing ID, period/date, public timestamp, actual ingestion timestamp, as-reported/version status, source document/checksum, parser version, extraction coordinates and formula/version lineage. A vendor correction creates a new record/revision; it never overwrites the prior as-reported source record.

## Conflict resolution and source-health policy

### Price and liquidity

- Scope every EOD value to `(security/listing, venue, trading date, field definition, source product, source revision)`.
- For the same venue and same source field, accept the formally corrected/reissued official exchange record when a revision marker or source notice identifies it. Preserve superseded row and correction relation. If source ordering is not authoritative, quarantine the disagreement.
- A different venue's price is never a same-row conflict and never averaged with the primary venue. Report it alongside the selected source if useful.
- Venue fallback is a display/engine policy: choose an explicit primary venue by listing/engine configuration, use the other exchange only if primary data is missing/stale/invalid and the other observation is valid for the same session. Expose `selected_venue`, fallback reason and both source references with the signal.
- Only sum valid comparable traded values/quantities across NSE+BSE when the engine intentionally defines consolidated activity and both listings map to the same effective security/session. Keep inputs and formula version. Keep deliverable values/percentages per exchange.
- Do not apply split/dividend adjustments to volume or price unless the chosen series and factor methodology explicitly state it. Preserve raw exchange price, quantity and turnover.

### Fundamentals and events

- Treat the filed issuer statement as source-of-record for that statement. Exchange re-publications are independently sourced copies and can establish publication metadata. Do not choose a third-party-normalized restatement without tracing to the filing.
- Use `public_as_of` only after the best reliable public timestamp is eligible under the 15:30 Asia/Kolkata cutoff and the official calendar. Date-only filings become eligible next trading session. Use `hamsa_known_as_of` only when actual local ingestion occurred by the cutoff.
- A later revision is a new financial observation version. A normalized vendor data vintage is not automatically the filing's original public-time vintage; record both clocks.
- Flag differences in units, standalone/consolidated basis, period length, taxonomy, rounding and revised values. Quarantine unresolved differences; do not cast missing or unparseable values to zero.

### Staleness and monitoring

Configure max age by `provider × product × metric × venue`. Do not assume one stale window for price, filings and quarterly fundamentals. Track:

- Expected report/session versus received file/date and cutoff time.
- Expected universe size, count and percentage of missing/duplicate/invalid rows by venue/report.
- Checksum changes for same source identifier and parser version.
- Source correction/resubmission references and time from original to correction.
- Master changes: new/removed instruments, ISIN/symbol changes, listing status and unresolved collisions.
- EOD cross-source field differences by venue/security/date, but only after semantic equivalence checks.
- Calendar discrepancies, special sessions, absent expected files and stale observations.
- Corporate action discontinuities requiring event review; do not automatically generate a factor from a price jump.

Keep thresholds configurable and report source-health status separately from any opportunity ranking. Staleness or a provider outage must suppress a signal if the required input is unavailable; it must never be treated as a zero, unchanged price or extreme-liquidity evidence.

## Third-party provider decision

### Do we need a commercial provider?

**Not for the first milestone if** HAMSA is a single local user's own research system, exchange data products can be licensed for a durable local archive, and daily/filing ingestion can be maintained. The provider's right to local storage is a hard prerequisite, and NSE's public policy makes this especially important to clarify.

Commercial data may become worthwhile if direct-source procurement yields no history for delisted securities, serviceable price corrections, a complete historical master, filing timestamps or a permitted local database, or if maintaining multi-format parser/correction operations costs more than a vendor license. Compare quote and rights, not just price per API call.

### Candidate fit

- **CMIE ProwessDX:** strongest researched Indian fundamentals/history alternative by published vintage dates. Standard agreement rules it out for HAMSA's local database and commercial-internal use. Ask whether CMIE offers a separate data-feed/enterprise license with point-in-time preservation, local archive rights, automated retrieval and derived internal research rights. Until then, do not download into HAMSA.
- **LSEG DataScope Select:** strongest reviewed single-provider technical match for EOD/historical pricing, reference/cross-reference, actions, point-in-time prices and scheduled REST/SFTP extraction. Obtain an India coverage manifest, EOD-only field set, delisted/history policy, pricing and server/archive rights.
- **FactSet Global Prices & Corporate Actions:** viable price/action alternative with a documented global history start in 2006 and prices/volume/turnover/VWAP, but India exchange security coverage and daily EOD feed design require confirmation. It does not replace issuer filings, exchange delivery percentages or local licensing analysis.
- **Yahoo Finance:** keep outside the scheduled adapter layer unless Yahoo grants express automation and retention rights. Its public consumer CSV download and yfinance convenience are not a production data license.

## Licensing approvals required before data ingestion

The following decisions require HAMSA owner approval after the provider supplies a written answer:

1. Whether HAMSA is strictly personal noncommercial research or internal commercial use, and whether any report will be shared outside the single user.
2. For NSE and BSE: approved data products/categories, EOD-only scope, date coverage, user count, actual ingestion method, server-side local raw archive and database storage, backups, revision retention, derived metrics, screenshots/reporting and deletion at termination.
3. Whether exchanging files over official public report links may be unattended under the chosen agreement, or whether the service must use a paid SFTP/API channel.
4. Rights to normalize and retain the 11 Hamsa 11 research-filter evidence records and data used in derived screening outputs.
5. Any third-party alternative's commercial internal-use rights, per-user/system license, retention and time-series export entitlements.
6. Yahoo's express permission if any automated collection, long-term archive, HAMSA database loading, commercial/internal distribution or derived display is contemplated. The current decision is **no Yahoo automation**.

## Operational-complexity estimate

| Approach | Relative complexity | Main work | Main risk |
|---|---|---|---|
| NSE+BSE direct, licensed files/products | Medium-high | Multiple formats, two venue masters, historical aliases, changed formats, filing/action corrections, separate calendars and independent QA | Rights/storage restrictions, historical gaps, repeated maintenance and licensing expansion for future sharing |
| Single licensed commercial consolidator | Medium | Vendor onboarding, product/field mapping, licensed universe and per-security usage, vendor symbol crosswalk and revision policy | Cost and dependence; may lack granular delivery/filing data, may obscure source and venue distinctions |
| Multi-provider official + consolidator cross-check | High | Two source paths, unified reconciliation and duplicated provenance/rights monitoring | More operating expense, conflicting fields and confused “authoritative” source if roles are not explicit |
| Yahoo/yfinance automation | Low apparent setup, high governance/data risk | Unofficial endpoint maintenance, symbol mapping, corrections, actions and data-quality audits | Terms restrict automation/redistribution, no supported API/SLA, no license or source-history controls |
| CMIE ProwessDX standard subscription integration | Low technical, disallowed legal architecture | Subscription, query and text export | Standard license prohibits commercial use and building a database; reject as HAMSA ingestion backend |

For HAMSA's long-run point-in-time and historical requirements, direct official ingestion is **medium-high** operational work. A commercial vendor can reduce transport and normalization work but must pass a coverage and licensing review. The synthetic pipeline already demonstrates the architecture needed to make either adapter replaceable.

## Recommended next implementation milestone

**Licensing and source qualification packet, before external ingestion:**

1. Send NSE and BSE a written single-user/local-system use case and request itemized, EOD-only quotes and product specifications for current and historical OHLCV/traded value/delivery, dated masters, actions, corporate filings and calendars. Ask explicitly about unattended retrieval, immutable raw and normalized archives, backups, corrections, derivations, use in internal research, fee/audit obligations and post-termination retention/deletion.
2. Request dated sample packages or redacted specifications only after the provider confirms the evaluation access terms. Capture each version/terms document under local procurement records, not in Git if contractually sensitive.
3. Request CMIE confirmation whether any separate commercial license can permit local database construction, automated ingestion and point-in-time/archive use. The standard ProwessDX agreement is not sufficient.
4. Request comparable RFI responses from LSEG and FactSet for India cash-equity daily EOD, ISIN and inactive-security mappings, delivery/volume definitions, action-factor/vintage history, filing support, user count, local storage, derivative display and cost. Ask each to demonstrate coverage using synthetic/security-list examples only until approved.
5. Decide if the future system will remain a single user's noncommercial tool or serve any commercial/multi-user research function. Feed rights differ materially.
6. After written approval and a selected licensed product, implement a source-qualification acceptance harness: coverage manifest, parsing sample, file dates/checksums, cross-venue independent rows, corrections, holidays/special sessions, stale/no-trade distinctions, access failure recovery and archive replay. Do this before adding the five discovery engines.

No screening engine, dashboard, broker connection, package installation or market-data provider call is part of this milestone.
