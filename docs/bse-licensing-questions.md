# BSE Licensing Confirmation Questions for HAMSA

**Purpose:** obtain written, product-specific permission and technical terms before any BSE data is downloaded, ingested or archived by HAMSA.
**Prepared:** 2026-11-10 (Asia/Kolkata)
**Status:** request draft only. No request has been sent, no license has been obtained, and no provider has been activated.

## HAMSA usage description to include with an inquiry

HAMSA is a local Python/DuckDB investment research and portfolio intelligence system. It consumes end-of-day information only, with an exchange cutoff of 15:30 Asia/Kolkata. It will preserve raw source files, checksums and historical revisions; maintain effective-dated issuer/security/listing mappings; create normalized company/financial observations; support historical point-in-time views; calculate research signals; and keep the Hamsa 11 qualitative judgments under human review. It will not generate automatic buy/sell recommendations, use intraday/live feeds, or redistribute raw exchange data unless separately approved.

Please answer separately for:

1. **Personal noncommercial research:** one named individual using a local, non-hosted research system to make their own investment decisions.
2. **Internal commercial research:** one or more people within an investment, advisory, research or other commercial organization using HAMSA for internal decision support; no external distribution of raw data.
3. **External distribution:** paid research, client reports, hosted access, or publication of raw or derived information. This is a future possibility only and should be quoted/licensed separately.

## What published BSE material establishes

BSE's Self Data Feed presents an official subscription process that includes registration/KYC, selection of data plans, agreement on pricing and agreements, payment, and feed access. Its listed categories include API products for equity and corporate data. BSE's information-products tariff describes daily EOD/reference data, daily EOD bhav copy, historical stock-trading data, and corporate products such as announcements, shareholding, results, corporate actions and consolidated pledge.

These publications establish that official EOD/reference/historical products and an official API subscription channel exist. They do **not** establish HAMSA's right to unattended retrieval, long-term local storage, backups, normalized database construction, internal commercial use, derived analytics or redistribution. The public data catalog is not itself a license for automated bulk collection.

**Primary references:** [BSE Self Data Feed](https://marketdata.bseindia.com/), [BSE Information Products Domestic Tariff Sheet](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf), [SEBI equity-cash source catalog](https://www.sebi.gov.in/curation/equity_cash_market.html), [BSE scrip-master sample](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44).

## Permissions expressly established versus confirmation required

| Topic | What published material expressly establishes | HAMSA status / confirmation needed |
|---|---|---|
| Product access | BSE offers subscribed EOD/reference, historical and corporate-data products through its information-products program and Self Data Feed. | **Not an entitlement.** Identify the specific product and eligible client category for each HAMSA use case. |
| API access | Self Data Feed describes API product categories and a registration/KYC, plan, price/agreement and payment process. | **No endpoint or automation right yet.** Provide current API manual, authentication process, rate limits and automation terms. |
| Historical data | BSE lists historical stock-trading data products; SEBI links an official security-wise price-volume/deliverable page. | **Coverage unresolved.** Provide the oldest available date and continuity by field, security state and venue code. |
| Security master | A BSE dated equity scrip-master CSV example includes scrip code, symbol/instrument, ISIN and other reference fields. | **Historical mapping unresolved.** Provide dated master history including inactive/delisted securities, effective dates and ISIN/symbol changes. |
| Fees and agreements | BSE publishes a tariff sheet and requires selected plan, agreed pricing/agreement and payment for Self Data Feed. | **No HAMSA quote or agreement.** Fees, scope, taxes, product rights and renewal terms require a product-specific offer. |
| Storage, backups and commercial use | The reviewed public pages establish no general local database, archive or commercial internal-use permission for HAMSA. | **Unresolved and blocking.** Obtain a written license covering the exact system, archive, users and derived outputs. |
| Redistribution | No general redistribution permission is established by the public catalog/tariff. | **Not permitted by assumption.** Obtain an explicit addendum for any display, publication or distribution. |

## Questions for BSE Market Data / Self Data Feed

### A. Client, product and allowed purpose

1. Which BSE entity and agreement govern the selected Self Data Feed product, historic price-volume files, EOD bhavcopy, security masters, corporate data and filing attachments?
2. Does the license permit each use case separately: one-person personal noncommercial investment research; internal commercial research/decision support; and future paid/public output?
3. If HAMSA is a local tool and no raw feed is sold, is it nevertheless a commercial application when used within an investment, research, advisory or other business to inform investment decisions?
4. Which subscription plan supports the data fields and history needed by a cash-equity research tool? Are there distinct plans for API integration, bulk download, display, storage, research, or development/testing?
5. Are there separate entitlements by user, named account, organization, workstation, server, product, security universe, data field, API, or number of downloads?

### B. Historical scope and data fields

6. Please provide a product-level historical coverage manifest with the earliest/latest available date for each field and each security, including BSE-exclusive securities, SME listings, suspended securities, delisted securities, relistings, symbol changes and changed ISINs.
7. For EOD history and bhavcopy, which fields are licensed: open, high, low, official close, last traded price, previous close, traded quantity, traded value/turnover, number of trades, weighted average price, deliverable quantity and deliverable percentage? Please provide units and definitions for each field.
8. Are BSE delivery values and percentages venue-specific for the exact scrip/date and tied to the same reported traded-volume denominator? Please provide the official field definitions and any known limitations.
9. Are historical daily records corrected or republished? How are a corrected record, source revision and publication time identified? Are old versions available, and for what period?
10. Can BSE supply dated security-master files with scrip code, symbol/instrument, ISIN, group/status, effective start/end dates, predecessor/successor records and delisted/inactive securities? What is the update frequency and archive depth?
11. Which products cover corporate actions, with event type, announced/publication timestamp, ex-date, record date, effective date, revised terms and original filing document? Does BSE provide calculated adjustment factors or only event disclosures?
12. Which products cover announcements, quarterly/annual financial results, shareholding patterns, consolidated pledge, insider/PIT/SAST filings, bulk/block deals, governance filings and investor documents? For each, provide the earliest date, attachment format, filing ID, publication time, amendment and revision-history fields.
13. Which official trading calendar contains holidays, special trading sessions and subsequent calendar revisions? Please distinguish trading sessions from settlement calendars and specify historic availability.

### C. Official access, daily automation and reliability

14. What officially supported interface should a local application use for daily unattended EOD delivery: Self Data Feed API, SFTP/file delivery, scheduled report export, or another documented route?
15. Are public browser report pages licensed for automated download? If not, which subscription product authorizes unattended retrieval?
16. Please provide API specification, schema/data dictionary, examples, authentication method, credential lifecycle, allowed client types, IP restrictions, encryption requirements and supported client/network configuration.
17. What are the API and download limits: requests per second/day, securities per batch, dates per query, concurrency, historical-download caps, retry intervals, pagination limits and rate-limit response behavior?
18. What are the EOD publication schedule and timezone for each product? State expected availability after close, special-session publication, holiday handling, and any service level for daily delivery.
19. How does BSE report a missing/late file, source outage, correction, amended filing or historical republishing? Are there status notifications, change manifests, stable revision IDs, support tickets or correction files?
20. What availability targets, planned maintenance windows, operational support hours, incident escalation and service credits apply?

### D. Local raw archive, database, retention and backups

21. May HAMSA retain immutable original EOD files, master snapshots, filings and attachments locally, with checksum and source identifier, for reproducible historical research?
22. Does the agreement allow normalized records in a local DuckDB database, including superseded observations, revision lineage, source-document references, parser version and derived observations?
23. May one user or multiple authorized internal users access that local database? Are local workstation and local server use licensed differently?
24. What are the permitted retention period and deletion requirements for raw files, database rows, backups, extracted attachments, derived metrics and superseded revisions during and after subscription expiry or termination?
25. Are encrypted local backup, removable-media backup, local network storage, disaster recovery copies and offline restoration allowed? Are cloud storage, private cloud, remote desktops or virtual machines permitted or restricted?
26. Does the BSE product permit archival of BSE records even when HAMSA has no active subscription, or must all copies be deleted when the license ends?

### E. Corporate actions, security master and derived analysis

27. Does BSE provide sufficient historical event terms to validate splits, bonuses, rights, dividends, consolidations, mergers, demergers, ISIN changes, symbol changes, suspensions, delistings and relistings?
28. Are original action announcements and later corrections retained separately? Can HAMSA use the official event terms and calculate private adjustment factors if it preserves raw prices and the formula/version lineage?
29. Which identity relationships may be obtained from BSE (same issuer symbol/ISIN changes, code changes and successor securities)? Does BSE provide effective dates and documentary sources, or must HAMSA separately review issuer reorganizations?
30. May HAMSA calculate and retain internal ratios, liquidity aggregates, historical returns, corporate-action-adjusted analytical series, screen scores and charts from licensed BSE data? Are any of these considered derived market data requiring separate fees/approval?

### F. Internal display, publication and redistribution

31. May licensed raw or derived BSE data be displayed in a local-only single-user interface? What if HAMSA is used by a private internal team or group company?
32. Which display and publication uses are permitted or prohibited: internal report, paid research report, client presentation, web application, mobile application, screen image, API output, educational material, research paper, raw data download and model/AI outputs?
33. What attribution, delayed-display, redistribution, security, audit-log, user count and downstream-recipient requirements apply?
34. Can derived summaries be published without raw observations? Define materiality thresholds, minimum aggregation, prohibited fields and any derived data or redistribution fees in writing.

### G. Fees, subscription and documents requested

Please provide:

- Product name/plan and itemized fees for setup, recurring access, historical backfill, API access, user/system/security counts, field/category additions, taxes and renewals.
- All applicable contract documents, data-use terms, tariff versions, service-level terms, security/authentication policy, retention/deletion schedule and amendment procedure.
- A field/product coverage matrix and historical start-date statement, including inactive/delisted security history.
- API manuals, file specifications, calendars, source revision/correction procedure, rate-limit schedule and support/escalation details.
- A written response marking each activity in this request **permitted**, **prohibited**, or **requires additional license/approval**.

## Approval rule

No BSE provider is admitted for production ingestion until an executed agreement explicitly covers the chosen EOD products, official access path, automated daily retrieval, historical downloads, local raw and normalized archives, backups, retention, internal-use case, derived analytics, and any planned display. If a required right is silent or ambiguous, the affected provider/product stays inactive.
