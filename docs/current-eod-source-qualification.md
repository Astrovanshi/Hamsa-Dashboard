# Current NSE/BSE EOD Source Qualification

**Inspection date:** 2026-11-10 (Asia/Kolkata)
**Observed trade date:** 2026-11-09. Samples are small current-session files only; no historical bulk data was downloaded.

## Qualification result

Both exchanges expose a practical official current-day, all-security equity UDiFF bhav-copy through their public reports pages. Those files provide venue-specific end-of-day OHLC, volume and traded value, and include ISIN and venue instrument references. The observed files do not establish HAMSA universe eligibility; both contain ETF rows classified as `STK`, and a series code alone is unsafe. BSE's UDiFF sample has no delivery fields. NSE separately publishes a full bhavcopy/security-deliverable file that contains delivery quantity/percentage but its symbol/series rows do not carry ISIN, requiring a carefully validated join to the current security master/EOD. We did not verify a BSE all-security delivery file in this sample.

The current production adapter is not full-universe-ready: its NSE path is allowlist-oriented and does not consume/join the master; its BSE path accepts the older per-scrip history export with an explicit listing mapping, not the observed BSE all-security UDiFF file. No adapter changes were made in this task.

## NSE

### Actual current files inspected

Official publication page: [NSE All Reports](https://www.nseindia.com/all-reports), which documents/advertises “CM-UDiFF Common Bhavcopy Final (zip),” “CM - MII - Security File (.gz),” and “Full Bhavcopy and Security Deliverable data.” NSE's official [2024 MII dissemination circular](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf) documents the daily `NSE_CM_security_ddmmyyyy.csv.gz` security file and All Reports route.

1. `BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv.zip` (206,935 bytes; SHA-256 `9b1388cbf80206119e04efa57779b2637b93fa37fd81c974ce978858f1b3dce2`). ZIP member `BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv`.
2. `sec_bhavdata_full_09112026.csv` (400,839 bytes; SHA-256 `ed3c764b5a58368d95543146fec96d8534cc29cba6862cebf357a4f7d86c0093`).

The exact observed UDiFF header:

```text
TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,
XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,
LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,
ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,
Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4
```

Observed: 3,704 rows, all `Sgmt=CM`, `FinInstrmTp=STK`; 2,743 rows have `SctySrs=EQ`, 376 `SM`, and the remainder include other series. `SBIN` (`INE062A01020`, ID `3045`, series EQ) has open/high/low/close `1030.00/1048.60/1022.30/1042.00`, volume `24065897`, traded value `24974519875.55`. `NIFTYBEES` (`INF204KB14I2`, ID `10576`, series EQ) is also `STK`; it is an ETF and must be excluded. Thus neither `STK` nor `EQ` is sufficient.

The observed full-bhavcopy header (leading spaces are present in several names):

```text
SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE,
LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS,
NO_OF_TRADES, DELIV_QTY, DELIV_PER
```

Sample: `20MICRONS, EQ, 09-Nov-2026, ..., TTL_TRD_QNTY=45425, TURNOVER_LACS=84.74, DELIV_QTY=21866, DELIV_PER=48.14`; another row (`21STCENMGM`, BE) has delivery values `-`, not numeric zero. This confirms a missing marker must remain missing. The full-bhavcopy sample count was not independently enumerated in this pass. Its records need a join against the dated current master (symbol + series + session, and validated ISIN mapping) before attaching ISIN; name/symbol alone must not merge securities.

No separate delivery percentage should be inferred from UDiFF fields. The full-bhavcopy delivery file is a separate source with its own completeness and revision lineage.

## BSE

### Actual current file inspected

Official page: [BSE Bhav Copy](https://www.bseindia.com/markets/marketinfo/bhavcopy). On 10-Nov-2026 it showed “As on 10 Nov 26” and a current “Equity (UDiFF)” download for 09-Nov-2026 (850.91 KB in page display), with a separate official help link to the [UDiFF format workbook](https://www.bseindia.com/downloads1/UDiFF_BhavCopy_format.xlsx). The page states older equity standardized and legacy per-security formats were discontinued from 08-Jul-2024.

Downloaded `BhavCopy_BSE_CM_0_0_0_20261109_F_0000.CSV` (871,332 bytes; SHA-256 `02ef5495999886e57d699956bc0fb844bd77a7bf49dd1221c2f73411d55ca496`). It contained 5,107 rows; all observed `Sgmt=CM`, `Src=BSE`, `FinInstrmTp=STK`. Sample ABB row: `FinInstrmId=500002`, `ISIN=INE117A01022`, `TckrSymb=ABB`, series `A`, OHLC `6854.10/6990.35/6674.55/6936.65`, volume `22404`, value `154027878.00`. Sample NIFTYBEES row: ID `590103`, ISIN `INF204KB14I2`, series `B`, still `FinInstrmTp=STK`; this is direct evidence that `STK` is not an ordinary-share classification.

Exact observed BSE UDiFF header:

```text
TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,
XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,
LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,
ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,
Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4
```

This file is practical for an all-security *traded-row* daily EOD feed and reliable cross-checks because it includes both ISIN and BSE instrument code. It is not by itself a full current listing master: inactive, suspended, or simply non-traded mainboard listings may be absent. The 5,107 rows describe this file only, not BSE universe size or complete coverage. It has no delivery quantity or delivery percentage columns. Do not treat absent delivery fields or absent EOD rows as zero.

## Cross-venue comparison and adapter fit

- Do not average NSE and BSE prices. Store one raw observation per venue/listing/session. An engine later chooses primary venue and explicit fallback; a separate policy may sum comparable traded value/volume across exchanges but must preserve source rows.
- Venue-specific instruments are retained even when the same ISIN maps to one canonical security. A source file's symbol, code and ISIN are retained as observed.
- ISIN is the strong cross-listing join candidate, but a changed ISIN, missing ISIN, malformed ISIN, or one ISIN mapping to conflicting names/instruments is not guessed; quarantine and review. Mainboard classification comes from a separate documented master/source, not from an EOD row.
- The NSE and BSE 09-Nov-2026 samples have differing OHLC/volume/value for the same ISIN, as expected for separate venues. They must not be collapsed into a fictitious average-price bar.
- BSE UDiFF all-security ingestion requires a new parser path; the existing adapter's per-scrip BSE export is not compatible with this UDiFF header. NSE UDiFF already has a parser path but full-universe use still needs dated master joins and verified scope classification; the current command configuration applies series/ISIN allowlists rather than authoritative universe membership.
- The NSE full-bhavcopy file contains deliverable data, but delivery quantities and percentages are not in the UDiFF file and the observed `-` values are missing, not zero. No BSE delivery coverage conclusion is made from the inspected UDiFF file.

## Local reproduction

The three downloaded source files used for inspection are ignored local artifacts under `data/raw/real/eod/{nse,bse}/`. They are not tracked and are not fixtures. Re-download through the official pages above and verify current names/checksums before future production ingestion. These findings qualify only the 09-Nov-2026 session sample; they do not assert historical coverage, licensing permission, or continuous feed completeness.
