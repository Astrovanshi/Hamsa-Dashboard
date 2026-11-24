# Full-universe source assessment

**Assessment date:** 2026-11-10 (Asia/Kolkata)

**Scope:** public official NSE/BSE equity EOD and reference-data routes, with a proposed full-universe historical backfill.

**Status:** research and planning only. No bulk archive was downloaded, no provider was activated, and no application/schema files were changed.

## Locked HAMSA investment universe

HAMSA includes only ordinary equity shares officially classified and confirmed as listed on the NSE or BSE mainboard. A dual-listed ordinary share is one security identity by ISIN with separate NSE and BSE listing identities. Eligibility is based on the exchange's official instrument/platform classification and listing status, never company size or market capitalisation.

Excluded from the investment universe are NSE Emerge, BSE SME, all other SME-platform listings, ETFs, mutual funds, REITs, InvITs, preference shares, warrants, rights instruments, debt securities, and all other non-ordinary-equity instruments. Excluded rows may be recorded in a reconciliation-only category; they must never be normalized as eligible HAMSA investment-universe members or passed to discovery engines. If classification is missing, conflicting, or ambiguous, quarantine the row instead of including it.

An SME-to-mainboard migration does not make the prior SME listing eligible. Preserve the SME listing's source identity/history separately. Admit a mainboard listing only from the verified effective migration/listing date, preserving the notice/master evidence and never backdating eligibility. The source snapshot date is an observation date; it is not a substitute for an effective date.

## Executive finding

Moving beyond the SBI proof of concept is technically feasible as an incremental, file-based process, but complete historical NSE+BSE reconstruction is **not yet demonstrated**. NSE publishes daily capital-market files, historical report archives and a per-security history interface. An NSE historical-data dissemination document describes a framework “from late 1995 onwards.” The reviewed public material does not establish that every required field, historical listing, inactive instrument or current downloadable archive is complete from that date. BSE publishes daily EOD/reference products and a public per-scrip Stock Prices history export; its product material describes historical products, but the reviewed public evidence does not establish the earliest date or a usable bulk all-security public archive.

Start with dated security-master snapshots and daily official files that can be acquired through their published pages. Backfill in bounded date ranges only after each product’s actual date coverage, row scope and file size are measured. Keep the initial process manual-download/local-ingest. Do not label the database “full universe” until the measurable coverage gates in [the implementation plan](full-universe-implementation-plan.md) pass.

## Evidence categories

- **Verified published capability:** an official source describes a product, archive, file type or interface. This is not itself proof of complete coverage.
- **Observed real-file evidence:** a representative downloaded file was previously inspected and retained locally under the ignored `data/raw/real/eod/` directory. The files are not part of Git.
- **Assumption / proposal:** an implementation approach, not a claim about source coverage.
- **Unresolved:** the available official source material does not establish the requested property.

## NSE

| Area | Verified official evidence | Observed real-file evidence | Unresolved limits |
|---|---|---|---|
| Daily EOD | NSE All Reports lists CM-UDiFF Common Bhavcopy Final ZIP and Full Bhavcopy and Security Deliverable data. NSE's historical reports catalog lists Archives of Daily/Monthly Reports (EQ), Security-wise Price Volume Archives (Equities), and related archives. The report page documents that legacy CM Bhavcopy formats were discontinued from 2024-07-08 and points to UDiFF. | The retained 2026-11-09 UDiFF ZIP contained 3,704 rows, including 2,743 EQ and 961 non-EQ series. Header includes trade date, segment, instrument type/id, ISIN, symbol, series, OHLC, previous close, volume, transfer value and trades. The same-date full bhavcopy contained 3,551 rows, with delivery quantity and delivery percentage fields. | Exact earliest downloadable date by report/field, corrections/revision depth, completeness of historical suspended/delisted securities, and stability of archive access are not established. Sample row totals are one-date observations, not a universe count. |
| Per-security history | The official security-wise archive interface exposes date ranges through 5Y and Custom and a CSV download control. | No additional bulk files were downloaded for this assessment. | UI range controls do not prove every security has continuous data for the range. Whether the route supports an efficient full universe export is not established. |
| Historical depth | An NSE Data & Analytics historical-dissemination document states NSE's historical data framework was set up in response to requests “from late 1995 onwards” and lists Bhav copy, Index, Masters, Snapshots, Trades and Circulars. | The SBI sample is dated 2026-11-09 only. | “Late 1995 onwards” describes the historical data framework, not proven earliest date for each required field/instrument. Need archive inventories and actual files from multiple eras to confirm. |
| Security master | All Reports lists dated `NSE CM MII Security File` reports. NSE's Master Data Specification describes compressed `security.txt`, with header/detail records and a daily traded-security file; documented fields include token, symbol, series, instrument type and ISIN among further fields. | The UDiFF row itself had NSE instrument id, ISIN, symbol and series. No historical sequence of master snapshots was inspected in this milestone. | Historical master archive availability and retention of inactive, suspended, renamed, delisted and relisted listings are unverified. A current daily file cannot establish prior membership or effective dates. |
| Delivery | NSE publishes a full bhavcopy and security-deliverable report, and the historical reports catalog lists price/volume/delivery archives. | SBIN delivery quantity 11,162,506 and delivery percentage 46.38 on 2026-11-09. Full bhavcopy turnover is rounded in lakh units; UDiFF transfer value was retained as the precise turnover source in the current adapter. | Field continuity, definitions and date coverage through the historical archive remain to be measured. |
| Corporate actions and lifecycle | NSE corporate filings expose corporate-action information; daily listing/master reports and historical circulars may assist mapping review. | No broad historical corporate-action set was ingested. | Complete historical event revisions and terms needed for adjusted histories are not established. Do not generate adjustment factors for incomplete terms or unreviewed methodology. |

Official references: [NSE All Reports](https://www.nseindia.com/all-reports), [NSE Historical Reports](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives), [NSE security-wise history](https://www.nseindia.com/report-detail/eq_security), [NSE Master Data Specification](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_MasterData_Technical_Specifications.pdf), [NSE historical-data dissemination document](https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf).

## BSE

| Area | Verified official evidence | Observed real-file evidence | Unresolved limits |
|---|---|---|---|
| Daily EOD | BSE's Information Products tariff describes daily EOD bulletins and bhav copies. BSE's Self Data Feed describes structured equity data/API feeds behind registration, plan selection, agreement and payment; it is not being activated. | The retained 2026-11-09 Stock Prices export for SBIN contained date, OHLC, WAP, shares, number of trades, turnover, deliverable quantity, delivery percentage and spreads. | Public bulk daily equity bhavcopy retrieval and its full file schema were not verified in the previously inspected route. A tariff/product description is not evidence that a public downloadable all-security archive is available. |
| Per-security history | Official BSE Stock Prices history page offers per-scrip date search and a Download File control. | The observed CSV contains no scrip code, symbol or ISIN. SBI identity was separately confirmed from BSE page context and mapped to scrip 500112 and ISIN INE062A01020. | Earliest queryable date, max range, gaps, inactive/delisted behavior and historical corrections are not established. Search page open returned HTTP 403 in this assessment browser; no restriction was bypassed. |
| Security master | BSE publishes scrip/reference information and a BSE dated master sample is linked in prior source research. | No full current or historical BSE master file was inspected for this milestone. The observed SBIN export itself is not self-identifying. | Actual all-security master route, formats/headers, update frequency, history bounds and inactive listing coverage need a small file sample and written/source-page confirmation. |
| Delivery and corporate actions | BSE's product material describes EOD/reference and corporate data products. | SBIN delivery quantity 877,692 and delivery percentage 60.28 on 2026-11-09 in its per-scrip CSV. | Definition/coverage and bulk history remain unverified. Never aggregate NSE/BSE delivery percentages. Corporate-action event history and mapping continuity remain unverified. |

Official references: [BSE Stock Prices history](https://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx), [BSE Information Products tariff](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf), [BSE Self Data Feed](https://marketdata.bseindia.com/), [BSE dated scrip-master sample](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44).

## Earliest verifiable coverage

- **NSE:** the official historical-dissemination PDF provides a broad historical-program statement of “from late 1995 onwards.” That is the earliest publicly documented historical program found in this review. It is **not** a verified field-by-field earliest EOD date or proof of complete all-security daily files. The only actual raw EOD file date inspected for this project remains 2026-11-09.
- **BSE:** the official sources reviewed describe historical products and a per-scrip history interface but do not provide a defensible earliest date for the requested full-universe daily fields. The earliest actual BSE file inspected for this project remains 2026-11-09.
- Therefore the only strictly file-verified coverage date for both current adapters is 2026-11-09. Older coverage remains to be proven from actual source files before estimating gaps or claiming a start date.

## Full-universe feasibility and the boundary of “complete”

| Target | Feasibility today | What blocks a completeness claim |
|---|---|---|
| Current NSE mainboard ordinary shares + EOD | Likely practical through dated daily reports and master snapshots after official mainboard/instrument classification and active status are verified. | Need actual master parser and row reconciliation. Do not treat `EQ` allowlisting alone as proof of mainboard ordinary-share eligibility unless the official source definition supports it. Historical reconstruction is not a prerequisite. |
| Current BSE mainboard ordinary shares + EOD | Possible if a complete official current master and all-security EOD file can be used; the per-scrip route alone is operationally costly. | Bulk route and normalized official mainboard/ordinary-share classification are not verified. Historical reconstruction is not a prerequisite. |
| Historical point-in-time eligible universe | Conditionally feasible if dated masters, migration/listing effective-date notices, and historical EOD files are available. Historical mainboard eligibility begins only on verified mainboard effective date. | Master history and inactive coverage have not been demonstrated for either venue. Current membership cannot reconstruct the historical eligible universe. |
| Continuous price history | Technically feasible for acquired dates; coverage must be reported per listing and venue. | Uneven date bounds, stale/absent sessions, source revisions, venue-specific symbol/code changes, and delisting records. |
| Point-in-time historical identity | Feasible only to the extent sourced effective-dated evidence exists. | A dated source may report a current snapshot rather than effective dates; ambiguous mappings must remain quarantined. |

The delivery objective should be **measured coverage with explicit unresolved rows**, not a binary “full universe” flag.

## Provisional coverage dashboard metrics

Report counts by source date and venue, not just company count:

1. Issuers, securities and listings separately; active, suspended, delisted, relisted, and unknown status separately.
2. NSE listings, BSE listings, dual-listed ISIN/security pairs, and each series/class in scope.
3. Mappings with approved ISIN, approved non-ISIN identity, pending review, rejected, and quarantined status.
4. EOD sessions expected/observed per exchange calendar; listings with first/last observed date; missing-session count and longest gap by listing.
5. OHLC, volume, turnover, delivery quantity and delivery percentage coverage per venue and per field.
6. Duplicate, rejected, out-of-scope, conflicted, quarantined and revised source records.
7. Percentage and count linked to sourced historical listing revisions; unresolved date intervals.
8. Raw source files and source revisions by report/date/checksum; parsing failures and archive/file reconciliation differences.

Publish numerator, denominator, denominator definition, calendar version, source vintage and date range with every percentage. Do not use current listed-security counts as a denominator for historical sessions.

## Decisions and unresolved source questions

- Confirm which exact fields/codes in each official current master establish mainboard classification, ordinary-share instrument type, and active listing status. The NSE UDiFF `STK` set contained multiple series; `STK` or `EQ` alone must not be assumed to prove both required classifications.
- Confirm the official source/field or listing notice used to establish the effective mainboard migration date for SME migrations. No SME row becomes eligible through a current symbol/ISIN match alone.
- The investment scope itself is locked. Remaining source question: whether current official masters expose sufficient classification/status fields directly, or whether an official listing notice/secondary source is required to resolve rows. Ambiguities must be quarantined.
- Establish source-level coverage bounds and correction semantics by collecting a tiny set of official dated files (recent, oldest discoverable, and one intermediate date) for each report. Report size and scope before any bulk download.
- Confirm whether a BSE all-security daily EOD route and historical master archive can be accessed through documented public pages. If not, determine whether manual per-scrip export is acceptable for a limited validation set; do not scale that route silently.
- Establish which dated official trading calendar and special sessions are used to measure missing dates.
- Establish whether delivery is required for all historical years or is a later/optional coverage dimension. Do not fill unavailable delivery values with zero.
- Determine source publication timestamps/correction markers where they exist. For a historical backfill with no reliable timestamp, retain conservative availability bounds rather than inferring same-day knowledge.

## Recommendation

Continue with local-file current-universe ingestion independently of historical reconstruction: first verify and parse current NSE/BSE mainboard ordinary-share master classifications and active statuses, then resolve current identities and ingest current EOD. Validate BSE's all-security current file/master route through published sources or user-supplied files. Oldest/middle/recent probes belong to the separate historical workstream and must not delay current ingestion. Preserve the pilot adapter and quarantine unverified classifications.
