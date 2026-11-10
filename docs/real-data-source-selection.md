# First real EOD source selection

**Verified locally:** 10 November 2026. This note describes a manual-download first path. It does not assert data-storage or redistribution permissions.

## First source and route

Use the official [NSE All Reports](https://www.nseindia.com/all-reports) page and download the dated `CM-UDiFF Common Bhavcopy Final (zip)` from the Capital Market reports list. This is the primary sample for NSE OHLC, volume and exact traded value. The dated `Full Bhavcopy and Security Deliverable data` CSV supplies delivery quantity and percentage. Download by selecting the dated public report; the adapter performs no network request.

For BSE, use the official [Stock Prices history](https://www.bseindia.com/markets/equity/EQReports/StockPrcHistori.aspx) page, search an instrument, select the EOD date and use its Download File control. This returns a per-scrip CSV. The observed file contains prices, WAP, shares, trades, turnover, deliverable quantity and delivery percentage, but does not contain scrip code, symbol or ISIN. BSE ingestion therefore requires a separately reviewed listing mapping from the official scrip master or BSE listing lookup. The parser does not guess it from a company name.

The NSE dated sample has ISIN, symbol, series and exchange instrument ID in each row. A configured series allowlist is mandatory: the UDiFF report also contains non-ordinary-equity series/instruments. The example selects `EQ`; it reports other rows as out of scope. Add other series only after deciding that HAMSA should treat them as equities for this data product.

## Real sample files inspected

All three originals are retained locally under the ignored `data/raw/real/eod/` directory. They are intentionally not committed.

| Exchange/product | File | SHA-256 | Observed record |
|---|---|---|---|
| NSE UDiFF CM | `BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv.zip` | `9b1388cbf80206119e04efa57779b2637b93fa37fd81c974ce978858f1b3dce2` | SBIN, ISIN `INE062A01020`, NSE instrument `3045`, series EQ, 2026-11-09; OHLC 1030.00 / 1048.60 / 1022.30 / 1042.00; volume 24,065,897; traded value INR 24,974,519,875.55. |
| NSE full bhavcopy + delivery | `sec_bhavdata_full_09112026.csv` | `ed3c764b5a58368d95543146fec96d8534cc29cba6862cebf357a4f7d86c0093` | SBIN delivery quantity 11,162,506; delivery percentage 46.38. The file's turnover is rounded in lakh units, so UDiFF remains the retained turnover source. |
| BSE Stock Prices export | `bse_sbin_2026-11-09.csv` | `832ab63127e9ae74d5cf971b494092f503501a81ead14f79b7902ace0d3ed559` | BSE lookup showed SBIN, ISIN `INE062A01020`, scrip `500112`; OHLC 1029.50 / 1048.90 / 1022.15 / 1041.45; shares 1,456,011; turnover INR 1,512,208,913; delivery quantity 877,692; delivery percentage 60.28. |

The three records are consistent on the SBI identity, but venue prices are different observations and are never averaged. Delivery observations remain venue-specific. The observed NSE series split was 2,743 EQ rows and 961 other rows in the selected report; that is sample-file composition, not a claim about universe coverage.

## Sample ingestion report

The local CLI was run against these three files using the example config, which explicitly allowlists only SBIN. Actual result:

| File | Accepted observations | Rejected records | Out of configured scope | Quarantined | Duplicates | Revised |
|---|---:|---:|---:|---:|---:|---:|
| NSE UDiFF | 1 | 0 | 3,703 | 0 | 0 | 0 |
| NSE full bhavcopy/delivery | 1 | 0 | 3,550 | 0 | 0 | 0 |
| BSE Stock Prices | 2 (price + delivery) | 0 | 0 | 0 | 0 | 0 |
| **Total first run** | **4** | **0** | **7,253** | **0** | **0** | **0** |

The 7,253 rows are explicitly out of the configured SBIN/series scope; `rejected` is reserved for invalid or malformed input rows/files. Parser tests independently cover malformed headers, malformed ZIP files, duplicate rows and changed-file revisions. Reimporting the same NSE file/version produced `duplicate=1`, `accepted=0` and no additional EOD observation. A new parser version preserved the source-document revision and appended an extraction revision. The verified database contained one canonical security, two distinct listings, two venue prices and two venue-specific delivery observations.

## Limits of the first path

- This is a local-file adapter only. It makes no web/API requests, does not bypass access controls and does not depend on undocumented endpoints.
- The first verified cross-venue identity is SBIN. Other ISINs are quarantined until a reviewer supplies explicit ISIN-to-issuer/security identity mappings. No name/symbol fuzzy matching is used.
- BSE's downloaded per-scrip history lacks identifiers. Ingest it only with a reviewed listing map, ideally from a dated official BSE security master; the example BSE lookup reference is a manually captured mapping, not a BSE master archive.
- The inspected EOD files establish those fields and values for 2026-11-09 only. They do not establish historical coverage, correction SLAs, or complete universe coverage.
- Source records are stored with `license_status=pending`. The user's instruction authorizes this local milestone's archive operation; the database does not represent this as a license determination.
