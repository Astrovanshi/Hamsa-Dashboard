# Mainboard Classification Rules

**Purpose:** Define conservative current-universe classifications for NSE and BSE listings before a classifier or ingestion adapter is implemented.
**Universe:** Ordinary equity shares officially classified as listed on an NSE or BSE mainboard. SME/Emerge and non-equity instruments are excluded. Company size, symbol, name, ISIN prefix, market capitalization, trading volume, or an `EQ`/`STK` label cannot by themselves establish eligibility.

## Evidence status

- **Verified exchange definitions** below are taken from official NSE/BSE documents or official exchange quote/report pages. Older format specifications are identified as such.
- **Observed file evidence** comes from the locally retained official 09-Nov-2026 NSE and BSE files. Those files prove what those particular rows contained, not the meaning of undocumented codes.
- **Design rules** state how HAMSA will interpret verified evidence. They are not exchange claims.
- **Unresolved** means no inclusion decision may rely on the field until the exchange supplies a current normative definition or an official per-security source resolves it.

## Classification dimensions

Do not compress platform, instrument class, and trading status into one guessed code. Store each separately, along with the raw source values and a final mutually exclusive HAMSA disposition.

| HAMSA disposition | Required verified facts | Rule |
| --- | --- | --- |
| **Eligible mainboard ordinary equity** | Ordinary equity instrument; official mainboard board/platform classification; listed and currently trading/eligible; reviewed ISIN/listing identity | Admit only when each fact is supported by an official source effective for the snapshot and the classification review is approved. |
| **Excluded SME/Emerge** | Official NSE Emerge/BSE SME/other SME platform classification | Exclude from investment universe; retain for reconciliation. For SME-to-mainboard migration, the disposition changes only from the independently sourced effective mainboard date. |
| **Excluded non-equity** | Official instrument class is ETF, mutual-fund unit, REIT, InvIT, preference, warrant, rights instrument, debt, or other non-ordinary equity | Exclude regardless of platform, board, series, name, or whether the product trades like a stock. |
| **Excluded inactive/non-trading listing** | Official current listing/trading status says delisted, suspended, inactive, not permitted, or not eligible to trade | Exclude from current universe for that listing snapshot. A separate still-active listing at the other exchange remains separately evaluated. |
| **Unresolved classification** | Any required dimension missing, ambiguous, conflicting, based on undocumented code semantics, or awaiting review | Quarantine/pending review. Never enter the investment universe or discovery engines. |

Stable machine values for these dispositions are `eligible_mainboard_ordinary_equity`, `excluded_sme`, `excluded_non_equity`, `excluded_inactive_non_trading`, and `unresolved_classification` respectively. Keep these values consistent in stored observations, reports, and queries.

Decision precedence is SME → non-equity → inactive/non-trading → eligible only when all inclusion tests pass → unresolved otherwise. Preserve raw dimensions even when an exclusion disposition takes precedence.

## NSE: official definitions and current MII evidence

### Verified official definitions

1. NSE's official [Master Data Specification v1.6](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE-Masters%20Data-v1.6.pdf) documents the legacy CM `security.txt` fields. It defines legacy **Instrument Type** values `0=Equities`, `1=Preference Shares`, `2=Debentures`, `3=Warrants`, `4=Miscellaneous`; `Permitted To Trade` values `0=listed but not permitted`, `1=permitted to trade`; normal-market security status values `1=preopen`, `2=open`, `3=suspended`, `4=preopen extended`, `5=stock open with market` (the master specification also documents value 6 as price discovery); and market eligibility `1=allowed`, `0=not allowed`. It also documents Symbol, Series, Token (unique for a symbol-series combination), Listing Date, Expulsion Date, Readmission Date, Delete Flag (`N=active`, `Y=deleted`) and ISIN Number.
2. That specification describes **Series** as the series identifier only; it does not define a complete mapping from series values to ordinary equity or mainboard/Emerge status.
3. NSE's [NSE/MSD/67344 circular](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf) confirms the daily MII security file is published on All Reports and identifies `PrtdToTrad` as the MII field related to permitted trading for BSE-exclusive securities. It distinguishes BSE-exclusive cash-market classes including mainboard, SME, partly-paid shares and rights entitlements. That circular does not publish a complete mainboard/ordinary-share codebook for all NSE-listed MII rows.
4. NSE official security quote pages expose per-security fields `Status`, `Trading Status`, `Board Status`, `Class of Shares`, and `Basic Industry`. For example the [SBIN quote](https://www.nseindia.com/get-quote/equity/SBIN/State-Bank-Of-India) reports status Listed, trading Active, Board Status Main, Class of Shares Equity, ISIN `INE062A01020`. The [NIFTYBEES quote](https://www.nseindia.com/get-quote/equity/NIFTYBEES/Nippon-India-ETF-Nifty-50-BeES) reports Board Status Main and Class of Shares Equity but Basic Industry Mutual Fund Scheme; NSE's [ETF description](https://www.nseindia.com/static/products-services/etfs-advantages) identifies NIFTYBEES as an exchange-traded fund. These fields demonstrate that “Main” and a broad “Equity” class alone do not establish ordinary-share eligibility.

### Observed current MII file

The retained `NSE_CM_security_09112026.csv.gz` has 120 columns and source snapshot label 09-Nov-2026. Relevant observed ISO tags include `FinInstrmId`, `TckrSymb`, `SctySrs`, `FinInstrmNm`, `ISIN`, `SctyTpFlg`, `PrtdToTrad`, `SctyStsNrmlMkt`, `ElgbltyNrmlMkt`, `ListgDt`, `RmvlDt`, `RadmssnDt`, `DelFlg`, `SctyTp`, `Sts`, `FinInstrmTp`, `InstrmTp`, `TradgPrtd`, `FinInstrmClssfctn`, `ClssfctnTp`, and `Sgmt`.

Observed sample values:

- SBIN: `FinInstrmId=3045`, `TckrSymb=SBIN`, `SctySrs=EQ`, `ISIN=INE062A01020`, `SctyTpFlg=0`, `SctyStsNrmlMkt=6`, `ElgbltyNrmlMkt=1`, `DelFlg=N`.
- NIFTYBEES: `FinInstrmId=10576`, `TckrSymb=NIFTYBEES`, `SctySrs=EQ`, `ISIN=INF204KB14I2`, `SctyTpFlg=4`, `SctyStsNrmlMkt=1`, `ElgbltyNrmlMkt=1`, `DelFlg=N`.
- The candidate fields `SctyTp`, `Sts`, `FinInstrmTp`, `InstrmTp`, `TradgPrtd`, `FinInstrmClssfctn`, `ClssfctnTp`, and `Sgmt` were empty for the inspected rows. Many MII rows share an ISIN across distinct series/instrument IDs.

The official legacy specification defines instrument and status semantics, but available documentation does **not** provide a sufficiently explicit, current crosswalk from each MII ISO field/code (`SctyTpFlg`, `SctyStsNrmlMkt`, `ElgbltyNrmlMkt`, `DelFlg`, etc.) to those legacy fields for this actual file. Similar values and matching examples are not a verified crosswalk. MII `SctyTpFlg=0` or `4` therefore remains raw evidence pending that crosswalk. Do not assert `0=ordinary shares` or `4=ETF` from the sample correlation.

NSE UDiFF EOD is not a substitute: the 09-Nov file reports both SBIN and NIFTYBEES as `FinInstrmTp=STK`, and both as series `EQ`. The NSE ETF page and NIFTYBEES security page provide the additional authoritative facts needed to exclude NIFTYBEES. An all-universe implementation needs an official batch classification field/source or a documented, complete, reviewable per-security classification feed; individual quote pages alone are not yet a practical whole-master join.

### NSE field decision table

| HAMSA classification | Official field/source | Observed evidence | Confidence | Unresolved issue |
| --- | --- | --- | --- | --- |
| Listing identity and ISIN | MII `FinInstrmId`, `ISIN`; source snapshot | SBIN ID 3045 / `INE062A01020`; NIFTYBEES ID 10576 / `INF204KB14I2` | High for observed field values | Confirm current file's ID lifecycle and exact listing/instrument semantics; do not merge by symbol. |
| Symbol and series | MII `TckrSymb`, `SctySrs`; legacy spec says symbol/series fields identify the security | Both examples carry `EQ`; MII has multiple rows by series for an ISIN | High for observation, no eligibility meaning | Series codebook does not establish ordinary shares or platform. |
| Instrument class | Legacy `Instrument Type` codebook; candidate MII `SctyTpFlg`, `FinInstrmTp`, `InstrmTp`, `SctyTp` | Legacy codes documented; current MII candidate columns do not have verified crosswalk; EOD has `STK` for both examples | Medium for legacy-only definitions; low for direct MII mapping | Need NSE's current MII field/code crosswalk and its relation to the 2026 MII file. |
| Mainboard vs Emerge | Official quote field `Board Status`; no confirmed populated MII field in sample | Per-security quote pages show `Main`; sample MII has no identified board field | High for pages that explicitly report it; low for the full master | Need official batch field/source and effective-date semantics for SME migration. |
| Ordinary vs ETF/other | Official quote `Basic Industry` plus product-specific official NSE ETF listing/description; no confirmed normative populated MII field | NIFTYBEES is explicitly an ETF/MF scheme despite Board Main, Class Equity, MII/EOD `EQ`/`STK` | High for this example; low as a whole-universe data method | Obtain documented current classification coverage for every instrument. |
| Status | Legacy `Permitted To Trade`, normal-market `Security Status`/`Eligibility`, `Delete Flag`; quote fields `Status`, `Trading Status` | MII raw status codes observed; quote pages explicitly report listed/active for examples | High for legacy source definitions; page-specific status confidence high | Current MII field mapping and status combinations need an official crosswalk; `DelFlg=N` alone is not sufficient. |
| Listing date | Legacy `Listing Date`; observed MII `ListgDt` | MII has numeric values | High for legacy field definition; unresolved MII encoding mapping | Decode only with current field spec; snapshot date never substitutes for listing effective date. |

## BSE: documented route and available definitions

### Current master access

An official BSE [Equity Segment Master Circular](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=cb125690-a0f8-452a-ba6b-86cab98004bc&id=20230630-19) directs users to `www.bseindia.com → Members → Information for Members → Members Help Desk → SCRIP.ZIP`. An official BSE [FAQ](https://www.bseindia.com/downloads1/FAQ_ESM.pdf) also references `https://www.bseindia.com/members/index.aspx` and `SCRIP.ZIP`.

This documentation does **not** say whether an ordinary non-member can anonymously retrieve the file or whether login/authorization is required. HAMSA has not obtained or inspected the current ZIP. No undocumented URL, credentials, or access bypass should be used. Exact next action: open the official BSE Members Help Desk page, follow the displayed Equity Scrip Master `SCRIP.ZIP` link, and record whether it downloads or requests member authentication. If it requests authentication, the missing input is the current SCRIP.ZIP downloaded through an authorized account or supplied by BSE; ask BSE whether it offers a public/non-member route. The earlier current BSE UDiFF EOD sample is not a substitute for this master.

### Published field semantics (dated specification; current-file verification pending)

BSE's official [Standardised Security Master file format](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44) documents the filename `BSE_EQ_SCRIP_DDMMYYYY.csv` and the following fields:

| Published field | Documented meaning/value | HAMSA use and limitation |
| --- | --- | --- |
| Scrip Code | Numeric identifier assigned to security | Venue listing reference; exact current field and continuity require raw master verification. |
| Instrument Code | Security symbol | Venue symbol; not identity by itself. |
| Group Name | Settlement group | Not proven to mean board/platform. Do not classify SME or mainboard from group letters without official codebook. |
| Scrip Name | Full name | Descriptive only; no identity merge based on name. |
| ISIN CODE | ISIN | Candidate cross-exchange security identifier; missing/conflicting values require quarantine. |
| Security Type Flag | `EQ` equity security, `MF` mutual funds, `DB` debt securities, `GS` government securities | Broad taxonomy. `EQ` does not by itself establish ordinary equity or exclude ETF/REIT/InvIT/partly-paid products. |
| Instrument status flag | `A` active, `S` suspend, `I` inactive | Published status meaning; verify current field/value presence in current master and distinguish listed from tradable. |
| Instrument Type | `E` equity trading, `D/C` debt (per document) | Broad trading class; not a mainboard classifier or proof of ordinary fully-paid equity. |

The dated specification has no confirmed mainboard/SME field in the consulted portions. Current file header, code values, actual group distributions, status meanings, snapshot date, publication time, and whether later file revisions changed the layout are unresolved until the current ZIP and applicable current format document are inspected.

### BSE field decision table

| HAMSA classification | Official field/source | Evidence | Confidence | Unresolved issue |
| --- | --- | --- | --- | --- |
| Listing identifier | Scrip Code (published master spec); actual BSE EOD `FinInstrmId` | EOD sample has e.g. SBI 500112, NIFTYBEES 590103 | Medium for EOD observed value; current master unverified | Verify that the master code is stable/unique for the BSE listing over time. |
| ISIN | ISIN CODE (published master spec); actual BSE EOD `ISIN` | EOD contains `INE062A01020` and `INF204KB14I2` | High for EOD row values, medium for current master mapping | Inspect current raw master, status and missing/conflict behavior. |
| Symbol/name | Instrument Code / Scrip Name (published spec); EOD `TckrSymb` / `FinInstrmNm` | EOD sample ABB, SBIN, NIFTYBEES | Medium pending current master verification | Retain as venue attributes only; no name/symbol-only security merge. |
| Instrument class | Security Type Flag; Instrument Type | Published old codes broad; BSE EOD uses `FinInstrmTp=STK` for NIFTYBEES | Low for ordinary-equity decision | Need current official codebook differentiating ordinary fully-paid equity from ETF and other units. |
| Mainboard vs SME | No confirmed field in consulted published master spec | Group Name is documented as settlement group, not board | Unresolved | Need current master or separate official per-security listing status/classification and dated SME migration evidence. |
| Status | Instrument status flag (`A/S/I`) in published spec | Current master not inspected | Medium for dated spec only | Confirm current field and whether `A` means currently tradable versus merely active/listed. |
| Snapshot date | Filename pattern includes date | No raw current master available | Low | Verify actual filename, source page, publication time, and source-as-of semantics. |

## Example decisions using verified official NSE fields

These examples illustrate the HAMSA rule, not a full-universe implementation. Dates are source observation/capture dates; no effective listing date is inferred from a snapshot. The sources are not a single same-date master join.

| Exchange | Listing identifier | ISIN | Source snapshot | Verified source fields | Rule | Disposition / review |
| --- | --- | --- | --- | --- | --- | --- |
| NSE | `SBIN` (NSE quote-page reference; MII `FinInstrmId=3045` is a separate 09-Nov observation, not joined as a same-date snapshot) | `INE062A01020` | NSE quote-page observation: 06-Nov-2026 | Quote fields: `Board Status=Main`, `Class of Shares=Equity`, `Status=Listed`, `Trading Status=Active`, ISIN. | Mainboard and active/listed status are supported. The broad `Class of Shares=Equity` field is not sufficient by itself to prove ordinary-share status; the observed MII codes have no verified crosswalk. | **Unresolved classification** pending an authoritative ordinary-equity distinction or an approved official source mapping. This deliberately does not promote SBI from symbol/name or sector assumptions. |
| NSE | `NIFTYBEES` / MII sample `FinInstrmId=10576` | `INF204KB14I2` | NSE product/security-page classification retrieved 10-Nov-2026; MII sample separately labelled 09-Nov-2026 | NSE quote page: `Board Status=Main`, `Class of Shares=Equity`, `Basic Industry=Mutual Fund Scheme`; official NSE ETF materials identify NIFTYBEES as an ETF. MII/EOD show series `EQ`, EOD type `STK`; those labels are not ordinary-equity evidence. | Official ETF/MF-scheme identification overrides broad “Equity” and trading labels; mainboard status does not convert a fund unit into an ordinary share. | **Excluded non-equity — approved for this example only**. |

These observations have different source capture dates and are not a same-day master join. A production decision must store each source document/snapshot separately and require date-consistent or explicitly reviewed evidence. The SBI example remains unresolved because the verified fields do not explicitly distinguish ordinary shares from all other equity-labelled instruments. Neither example licenses inferring a disposition for other listings from name, symbol, series, type code, company size, or market cap.

## Source links

- [NSE Master Data Specification v1.6](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE-Masters%20Data-v1.6.pdf)
- [NSE daily MII publication route](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf)
- [NSE MII/BSE-exclusive publication and field reference](https://nsearchives.nseindia.com/content/circulars/MSD67344.pdf)
- [NSE SBIN quote](https://www.nseindia.com/get-quote/equity/SBIN/State-Bank-Of-India)
- [NSE NIFTYBEES quote](https://www.nseindia.com/get-quote/equity/NIFTYBEES/Nippon-India-ETF-Nifty-50-BeES)
- [NSE ETF description](https://www.nseindia.com/static/products-services/etfs-advantages)
- [BSE SCRIP.ZIP route circular](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=cb125690-a0f8-452a-ba6b-86cab98004bc&id=20230630-19)
- [BSE standardized master format](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44)
- [BSE FAQ referencing Members Help Desk/SCRIP.ZIP](https://www.bseindia.com/downloads1/FAQ_ESM.pdf)
