# NSE Licensing Confirmation Questions for HAMSA

**Purpose:** obtain written, product-specific permission and technical terms before any NSE data is downloaded, ingested or archived by HAMSA.
**Prepared:** 2026-11-10 (Asia/Kolkata)
**Status:** request draft only. No request has been sent, no license has been obtained, and no provider has been activated.

## HAMSA usage description to include with an inquiry

HAMSA is a local Python/DuckDB investment research and portfolio intelligence system. It consumes end-of-day information only, with an exchange cutoff of 15:30 Asia/Kolkata. It will preserve source files, checksums and historical revisions; create normalized company/security/financial observations; support point-in-time historical views; calculate research signals; and keep the final Hamsa 11 qualitative judgments under human review. It will not generate automatic buy/sell recommendations, use intraday/live feeds, or redistribute raw exchange data unless separately approved.

Please answer separately for the following intended-use cases; do not treat approval for one as approval for the others:

1. **Personal noncommercial research:** one named individual using a local, non-hosted research system to make their own investment decisions.
2. **Internal commercial research:** one or more people within an investment, advisory, research or other commercial organization using HAMSA for internal decision support; no external distribution of raw data.
3. **External distribution:** paid research, client reports, hosted access, or publication of raw or derived information. This is a future possibility only and should be quoted/licensed separately.

## What published NSE material establishes

NSE's Data Sharing & Usage Policy states that:

- A subscriber must execute a relevant agreement that describes intended use and how market data may be received, transmitted, handled, disseminated or otherwise dealt with.
- Commercial market-data use is priced under NSE Data's pricing process.
- Redistribution is not permitted except as agreed in the relevant agreement.
- Market data is provided online through a designated server; offline modes such as CDs, hard drives and USB/removable media require prior approval from the NSE Data & Analytics Managing Director and CEO.
- EOD/historical order and trade data has documented SFTP and online-platform delivery routes. This does not by itself grant local archive or database rights for HAMSA.

The public reports catalog and historic-data documentation show products and archive descriptions. Public availability does not confirm that HAMSA may automate retrieval, keep an immutable local archive, or use the data commercially. The current NSE MCP page has a separate informational/learning and noncommercial scope; it is not the license requested here and must not be assumed to cover HAMSA's local database.

**Primary references:** [NSE Data Sharing & Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy), [EOD/Historical subscription](https://www.nseindia.com/static/market-data/eod-historical-data-subscription), [All Reports](https://www.nseindia.com/all-reports), [historical-data archive description](https://nsearchives.nseindia.com/content/press/Data_details_CM.pdf), [NSE MCP](https://www.nseindia.com/nse-mcp).

## Permissions expressly established versus confirmation required

| Topic | What published material expressly establishes | HAMSA status / confirmation needed |
|---|---|---|
| Agreement and intended use | NSE requires a relevant agreement that sets out intended use and permitted data handling/dissemination. | **Not established for HAMSA.** Please provide the applicable agreement and confirm each intended-use case above. |
| Commercial use and fees | NSE policy says commercial market-data access is priced by NSE Data under its approved pricing process. | **Not established.** Provide an itemized quote for HAMSA's selected products/use cases. |
| Redistribution | Policy disallows redistribution except where agreed in the relevant agreement. | **Not permitted by default.** Specify rights or restrictions for research excerpts, displayed values, reports, screenshots and any future external distribution. |
| Delivery channel | NSE documents online delivery; specific EOD/historical order/trade data is delivered through SFTP and historical order/trade via an online platform. | **Product-dependent.** Confirm an officially supported channel for each selected EOD product and historical archive. |
| Offline media | Use of offline media such as hard drives/removable media is not permitted without prior approval under the policy. | **No HAMSA archive permission established.** Obtain explicit approval for persistent local files, DuckDB, backups, replicas and disaster recovery. |
| Data fields | NSE product pages/specifications describe data products and report fields, including EOD and security master information. | **No HAMSA entitlement established.** Confirm selected products and the licensed fields/segments/securities. |
| Historical coverage | NSE historical documentation describes equity bhavcopy history from March 1999 and historical master snapshots; current licensed-product archive coverage is not guaranteed by that page. | **Unresolved.** Provide actual start/end dates, completeness by field/security/status and the current archive catalogue. |
| API/SFTP limits | Product routes are documented, but no HAMSA-specific request limits, uptime or daily SLA were established by this review. | **Unresolved.** Provide concurrency, rate, file polling, retry, maintenance and availability limits. |
| Local/derived database rights | No general right to create a persistent local HAMSA database was identified. | **Unresolved and blocking.** State whether source files, normalized observations, derived values and revisions may be retained locally and for how long. |

## Questions for NSE Data & Analytics

### A. Account, entity and permitted purpose

1. Which contracting entity, subscriber category and product agreement apply to a single-user local research application such as HAMSA?
2. Does the agreement permit each case listed in the usage description: personal noncommercial investment research, internal commercial decision-support research, and any future paid or public research output? Please answer each separately.
3. Does an internal research application count as commercial use if no data is sold or provided to another party but the user or organization uses the outputs to make investment decisions?
4. Are any research, analyst, noncommercial or academic pathways available to a private individual or commercial organization? What qualifications, process, fees, confidentiality terms or additional undertakings apply?
5. Are separate licenses required for raw market data, corporate data, historical reports, derived metrics, index/benchmark use, model inputs or displaying data in an internal application?

### B. Products and historical coverage

6. Please quote and describe the smallest EOD-only product set that covers cash-equity daily OHLCV, official close, traded quantity, traded value/turnover, number of trades if available, and security-wise delivery quantity/percentage.
7. Are the daily bhavcopy/report downloads covered under the same terms as the paid EOD/historical products? If different, identify the exact product and usage rights for each file route.
8. For each requested field/product, what is the earliest and latest available date? Please state coverage separately for regular cash-equity, SME/Emerge, suspended securities, delisted securities, securities with no trade, and securities whose symbol or ISIN changed.
9. Can NSE provide a dated historical security-master archive from 1999 onward, including historical ISIN, symbol, series, token/security code, listing/trading status, effective dates and retired instruments? Is that daily or monthly, and what gaps exist?
10. What date range and history are available for corporate actions, issuer announcements/results, shareholding filings, bulk/block deals, short-sale reports, delivery data and official trading calendars?
11. Are original filings and attachments available as immutable source documents with stable filing identifiers, publication/broadcast timestamps, revision identifiers and amendment links? If not, which metadata are supplied?
12. How are legacy report formats and current UDiFF reports mapped? Please provide versioned schemas and any official crosswalks for changes.

### C. Automated EOD access and operations

13. Which supported access method is approved for unattended daily EOD collection for the selected products: SFTP, a documented API/MCP interface, portal export, or another documented interface?
14. Is automated retrieval of public daily report files permitted for this subscriber, or must all unattended retrieval use a paid/licensed channel?
15. If a documented API or MCP service is offered, can HAMSA use only EOD/historical endpoints and disable all live, delayed, intraday, streaming or order-book tools at the account/network level? Is the interface licensed for local application integration and persistent storage?
16. What authentication and credential rotation are required? Are IP allowlists, VPN, certificates, mutual TLS or dedicated machines required?
17. What request, file, concurrency and historical-download limits apply? Are there restrictions on batch sizes, query frequency, securities per request, date range, retries or parallel downloads?
18. What is the expected post-close publication schedule for each file, in what timezone, and what service level applies on normal days, holidays, special sessions and delayed publications?
19. How does NSE signal missing, corrected, republished or late files? Are stable revision IDs, correction notices or change manifests available? What is the correction window and are subscribers notified?
20. What are support hours, incident escalation procedures, maintenance windows, service uptime commitments, and subscriber remedies for failed/delayed delivery?

### D. Local storage, archival and backups

21. Does the agreement expressly permit storing received raw EOD files and historical reports on HAMSA's local computer and encrypted local backup media, notwithstanding the policy's restriction on offline media without approval?
22. May HAMSA keep an append-only local DuckDB database and immutable raw source archive containing historical observations, original revisions and corrections? State whether a persistent server/database is treated differently from removable media.
23. May the archive contain checksums, source identifiers, schema versions, parser versions, extraction timestamps, source publication timestamps and extraction locations?
24. What retention period applies to raw files, normalized records, derived metrics and superseded revisions? Must data be deleted or rendered inaccessible on subscription expiry, termination or product change?
25. Are backups, disaster-recovery copies, encrypted replicas, point-in-time database backups, local version control of synthetic test fixtures, or restoration tests allowed? What media/storage locations are permitted?
26. Can backups be stored in a local encrypted filesystem, local network-attached storage, or an approved private cloud? If cloud is prohibited, please state the exact restriction.

### E. Financials, corporate actions and derived outputs

27. Which products include corporate action announcements and complete historical event terms for splits, bonuses, rights, dividends, mergers, demergers, name/symbol changes, ISIN changes, suspensions, delistings and relistings?
28. Are announcement/publication timestamps distinct from ex-date, record date and effective date? Are amended action records/version histories supplied?
29. Does NSE provide adjusted historical series or event factors? If so, identify the adjustment methodology, factor version/revision fields, treatment of rights/demerger/merger cases, and rights for local storage and calculation. May HAMSA instead calculate its own factors from licensed raw terms and retain factor lineage?
30. Which financial filing products provide annual/quarterly results and XBRL or attachments? Are standalone/consolidated basis, reporting period, publication time, submission/revision status and original filing document included?
31. May HAMSA normalize permitted raw fields into canonical units and calculate private derived metrics (for example, liquidity ratios, moving averages or turnover aggregates) for one or more internal users? Are there limits on retaining formula outputs or source values needed to reproduce them?
32. Which outputs may be shown in an internal application: raw values, charts, derived ratios, rankings, screening flags, historical point-in-time reports, or excerpts? Do thresholds differ for internal-only vs external presentation?

### F. Publication, redistribution and audit

33. Confirm which activities are prohibited unless separately licensed: raw data redistribution, display to colleagues, reports to clients/investors, screenshots, web/mobile publication, hosted access, API output, model or AI training, or publishing derived indicators.
34. What attribution, watermark, delay, retention, confidentiality, access-control, audit-log and end-user reporting requirements apply?
35. Does NSE require records of users, queries, stored files and redistribution? What audit rights and notice apply to HAMSA's local system?
36. If future HAMSA use changes from one named user to an internal team or external paid research, which contract amendments and fees are required before use changes?

### G. Fees and contract documents requested

Please provide:

- Product name and version, full technical specification, supported access method and sample files.
- Itemized one-time setup and recurring subscription fees, historical-data fees, per-user/per-system/per-security fees, taxes and any separate data-vending/display/redistribution fees.
- The applicable agreement, current data policy, permitted-use schedule, product-specific addendum, service-level/support document, retention/deletion policy and amendment/change-notice terms.
- A written product/use matrix that marks each activity above **permitted**, **prohibited**, or **requires additional license/approval**.
- A named contact for licensing and technical support.

## Approval rule

No NSE provider is admitted for production ingestion until the written response and executed agreement explicitly cover the selected EOD product, automation route, historical files, local archive/database, backups, internal-use case, derived metrics, retention and any intended display. If a response is silent or ambiguous on a required activity, that activity remains unapproved and the adapter stays inactive.
