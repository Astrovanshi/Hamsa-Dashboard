# NSE CM Security Master Qualification

**Assessment date:** 2026-11-11

**Purpose:** File-level qualification only. No records in this report are approved production identity, listing, or classification evidence. The subsequent local ingestion is separately summarized in `docs/nse-mainboard-master-ingestion.md`.

## Scope and handling

The three supplied files were inspected as data. Text inside files was not treated as instructions. During that original qualification pass, no application code, database, schema, mapping, or production data was changed. The later intake pass did add source and quarantine records to the existing local v3 database, without schema migration or approved identity/classification mappings.

The filename token `09112026` is consistent with a date of 9 November 2026 if interpreted as DDMMYYYY, but filenames do not establish publication date or source authenticity. The files contain no source URL, receipt, signed manifest, or other source-publication proof. Their local filesystem modification times are from 11 November 2026 and are not source timestamps.

## File inventory

| Supplied file | Bytes | SHA-256 | Parsed rows × columns | Duplicate `FinInstrmId` groups | Notes |
|---|---:|---|---:|---:|---|
| `NSE_CM_security_09112026 (1).csv.gz` | 1,282,023 | `99cd4f092d1f14a749ba3cb7a98c1bedb5d9d4c74b9bd71bc3b3a0c1baf75c28` | 38,415 × 120 | 0 | Byte-for-byte identical to the existing workspace artifact `data/raw/real/eod/nse/NSE_CM_security_09112026.csv.gz`. |
| `NSE_CM_security_09112026 (2).csv.gz` | 1,567,217 | `f8232a07a9a815bda8873fa9b179278030b7ace85acf07f42a90aacdc6be48c8` | 48,056 × 120 | 0 | Same 120-column header as file (1). |
| `EQUITY_L.csv` | 186,852 | `2c05ea3dbe51b6b727b8dce4973cee9fc2a0064bd1ac869328c825e5acece75e` | 2,645 × 8 | N/A | Byte-for-byte identical to `EQUITY_L (1).csv`; filename/header matches NSE's public equity-list file, but no local retrieval receipt is attached. |

Both CM files have no blank `FinInstrmId`. The file comparison below treats `FinInstrmId` as a within-file comparison key only; it is not accepted as a permanent HAMSA identity. `EQUITY_L.csv` headers were whitespace-trimmed for parsing/comparison; its original header labels are shown below.

### Observed headers

The CM files have the same header:

```text
FinInstrmId,TckrSymb,SctySrs,FinInstrmNm,ISIN,NewBrdLotQty,ParVal,SctyTpFlg,BidIntrvl,TrckgInd,CallAuctnInd,BookClsrStartDt,BookClsrEndDt,NoDlvryStartDt,NoDlvryEndDt,IssdCptl,PrtdToTrad,PricRg,SctyStsNrmlMkt,ElgbltyNrmlMkt,SctyStsOddLotMkt,ElgbltyOddLotMkt,SctyStsRETDBTMkt,ElgbltyClsgAuctnSsn,SctyStsAuctnMkt,ElgbltyAuctnMkt,SctyStsAddtlMkt1,ElgbltyAddtlMkt1,SctyStsAddtlMkt2,ElgbltyAddtlMkt2,IsseDt,FrstPmtDt,MtrtyDt,MaxTradQtyPctg,ListgDt,RmvlDt,RadmssnDt,RcrdDt,IndxPrtcptnInd,AllOrNn,MinFill,SttlmTp,Dvdd,Rghts,Bns,Intrst,AGMtg,EGMtg,MktMakrSprd,MktMakrMinQty,AddtlInf,UpdDt,DelFlg,SpclExDt,Xchg,UnqPdctIdr,SctyTp,TickSz,XchgExclsv,Sts,ExDvddDt,ExBnsDt,ExRghtsDt,FinInstrmTp,InstrmTp,TradgPrtd,BuyBckInd,TradToTradInd,Indx,IndxInstrm,FinInstrmAttrbts,MinLot,UndrlygInstrmAsstClss,UndrlygInstrm,UndrlygFinInstrmId,BlckDealAllwdFlg,InstrmNm,MktTpAndId,UnitOfMeasr,PricQtQty,PricRgTp,MaxPric,MinPric,SttlmMtd,InitlMrgnTp,BuyInitlMrgnRate,IssePric,MaxSnglTxnQty,MaxSnglTxnVal,AsstClss,PricNmrtr,Spcfctn,PricDnmtr,GnlNmrtr,GnlDnmtr,LotNmrtr,LotDnmtr,DcmlstnPric,SrsSttlmTp,FreeFltCptl,SellInitlMrgnRate,RatgDtls,FinInstrmClssfctn,SpclMrgnTp,BuySpclMrgnRat,SellSpclMrgnRat,PreOpnAllwdFlg,ClssfctnTp,MtchgCrit,ValMtd,SLBMElgblty,Sgmt,Ccy,SttlmCcy,Rsvd02,Rsvd03,Rsvd04,Rsvd05,Rsvd06,Rsvd07
```

The `EQUITY_L.csv` header, after trimming leading spaces, is:

```text
SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,MARKET LOT,ISIN NUMBER,FACE VALUE
```

## CM file comparison

Compared file (2) against file (1), keyed by the string value of `FinInstrmId`:

| Result | Count |
|---|---:|
| IDs common to both | 38,415 |
| IDs added in file (2) | 9,641 |
| IDs removed from file (1) | 0 |
| Common IDs whose row changed | 3,296 |
| Field changes among common IDs | 3,296 `UpdDt`; no other changed field observed |

Thus file (1)'s IDs are a subset of file (2)'s. All 9,641 added rows carry raw `PrtdToTrad=2`; NSE's master specification documents the corresponding legacy field as BSE-listed/exclusive. These are BSE-side candidates, not NSE listing admissions, pending a current MII-specific mapping and BSE listing identity review. The added rows are not proof of newly listed securities: the files' publication/snapshot dates are unverified. Each file has no duplicate `FinInstrmId` values, but repeated ISINs and symbols occur across distinct instrument rows. For example, `SBIN` has several instrument IDs and series; the rows include both the ordinary share and separately identified bond instruments. Identity must not be resolved from symbol alone.

NSE's master specification identifies symbols ending in `NSETEST` as dummy/test instruments; each CM file contains 23 such rows. A broader text scan finds 497 rows in file (1) and 552 in file (2) with strings such as `DUMMY` or `TEST` in identifier/name fields, but that scan is only a review flag. Do not classify records as synthetic from a name or placeholder-looking ISIN alone; invalid ISINs are separately quarantined.

Both files have 9,699 rows with raw `DelFlg=Y`. The NSE master specification documents the corresponding legacy delete flag as `Y` deleted and `N` active. Preserve this as the source's deletion flag, not a reviewed effective delisting interval. Both files have two nonzero `RmvlDt` values; under the documented NSE master epoch they decode to 1999-04-07 and 2006-01-27 (the format does not specify a timezone). `RadmssnDt` is zero in all rows and remains a sentinel, not a date.

## Timestamp and claimed-date assessment

The gzip header MTIME is `0` for both CM files, so the container supplies no usable embedded modification time. There is no row-level source publication timestamp.

`UpdDt` is populated in all rows. The applicable NSE Master Data Specification says the legacy master time/date fields use seconds from 1 January 1980 (unless specified otherwise), and defines the legacy `Local DB Update Date Time` as the local database update datetime. This supports interpreting MII `UpdDt` as a per-record update value only insofar as its relationship to the legacy field is confirmed; a complete MII-tag-to-legacy-field crosswalk was not found. Decode it using the documented epoch as a source-clock value without assigning a timezone:

- File (1): `2026-11-09 18:50:42`.
- File (2): `2026-11-09 20:31:29`.

`ListgDt` has 616 zero sentinels; positive values decode under the same 1980 epoch to `1995-02-08` through `2026-11-11`. The latest `UpdDt` values are consistent with the filename's claimed 2026 date. They are not file publication timestamps and cannot prove when either file was published. The filename convention is documented for NSE's daily MII file (`NSE_CM_security_ddmmyyyy.csv.gz`) and its website distribution became effective 5 February 2024, but the supplied bytes have no attached retrieval receipt or authenticated publication metadata. Gzip MTIME is zero. Thus `09112026` is a claimed/source-date token, not independently verified publication evidence.

## CM field completeness and sample observations

The following potentially useful classification/segment fields are completely blank in both files (all rows): `FinInstrmTp`, `InstrmTp`, `SctyTp`, `Sts`, `TradgPrtd`, `FinInstrmClssfctn`, `ClssfctnTp`, `Sgmt`, `Xchg`, and `XchgExclsv`. The field `ISIN` itself is nonblank in the observed rows, but test-like placeholder values occur.

Other status-like fields are populated, including `SctyTpFlg`, `SctyStsNrmlMkt`, `ElgbltyNrmlMkt`, `PrtdToTrad`, and `DelFlg`. The NSE legacy master specification documents analogous fields: `Delete Flag` Y/N; `Permitted to Trade` values 0 (listed, not permitted), 1 (permitted), and 2 (BSE-listed/exclusive); normal-market status 3 as suspended; eligibility 0/1; and symbols ending `NSETEST` as dummy/test instruments. The current MII-to-legacy field correspondence is not fully specified in the inspected documentation, so the importer preserves the MII raw values and applies these documented meanings conservatively only for deleted/test/out-of-scope review flags. It does not treat those flags as approved listing history, ordinary-equity classification, or mainboard classification. The blank type/platform fields and undocumented `SctyTpFlg` remain unresolved.

Illustrative CM values from file (2):

| Symbol / row | `FinInstrmId` | `SctySrs` | ISIN | Name | `SctyTpFlg` | Normal-market status / eligibility | `DelFlg` |
|---|---:|---|---|---|---:|---|---|
| SBIN | 3045 | EQ | INE062A01020 | STATE BANK OF INDIA | 0 | 6 / 1 | N |
| NIFTYBEES | 10576 | EQ | INF204KB14I2 | NIP IND ETF NIFTY BEES | 4 | 1 / 1 | N |

These are literal source values, not decoded classifications. NIFTYBEES also appears under other instrument IDs and series with the same ISIN. Its name and the independently documented ETF evidence in the existing project research support excluding it from ordinary-equity investment coverage; the numeric flag and `EQ` series are not the basis. This illustrates why series and symbol alone are unsafe eligibility rules.

## Comparison with `EQUITY_L.csv`

`EQUITY_L.csv` has 2,645 rows, each with a unique ISIN and unique symbol in this file. Its 2,645 ISINs all occur in the CM file (2), and all 2,645 matched symbols also agree after whitespace trimming. This is an observed cross-file join, not independent proof that either file is current or complete. The CM file has many additional records, including different instruments and repeated symbols/ISINs; the BSE file is not a security-classification codebook.

`EQUITY_L.csv` supplies symbol, company name, series, date of listing, paid-up value, market lot, ISIN, and face value. It has no explicit active/trading status, mainboard/SME platform field, or ordinary-equity instrument-class field. The series field is not sufficient evidence of mainboard ordinary-equity eligibility. `DATE OF LISTING` is an observed field, but without source-date provenance and verified semantics it must not be used to infer when the snapshot was taken or to approve historical listing intervals.

## What these fields can and cannot establish

| Purpose | What is observed | Qualification |
|---|---|---|
| Within-file instrument reference | `FinInstrmId` | Can distinguish rows within these snapshots; stability and lifecycle semantics are undocumented here. Not a HAMSA security ID. |
| Candidate cross-file security identity | `ISIN` | Useful for candidate matching when valid and source-backed. Does not itself prove issuer continuity, exchange listing, or validity for all rows; placeholders and instrument multiplicity require checks. |
| Exchange symbol and series | `TckrSymb`, `SctySrs`; BSE `SYMBOL`, `SERIES` | Preserve as venue/source facts. Do not use symbol-only mapping or infer eligibility from series. |
| Lifecycle dates/status | `ListgDt`, `RmvlDt`, `RadmssnDt`, `DelFlg`, status/eligibility fields; BSE `DATE OF LISTING` | Preserve raw values, but field definitions, code meanings, temporal semantics, and snapshot provenance remain unverified. No historical interval should be manufactured from them. |
| Instrument classification | Numeric `SctyTpFlg` is populated; several type/classification fields are blank | No authoritative codebook/crosswalk was verified. Not sufficient to distinguish ordinary shares from ETF, debt, or other instruments. |
| Mainboard versus SME | No populated explicit platform classification field observed in the CM file; none in `EQUITY_L.csv` | Cannot establish platform. No SME/mainboard approval is possible from these files alone. |
| Current active/trading state | Raw status-like fields exist; the analogous legacy NSE definitions are documented | Preserve as raw snapshot facts and conservative review flags. MII crosswalk and snapshot authenticity still need verification; do not project status historically. |

## Evidence still required for mainboard ordinary-equity eligibility

Before any record can be admitted, obtain and review:

1. An authenticated NSE source artifact with a verifiable retrieval/publication date, immutable bytes/checksum, and applicable official MII/security-master specification and codebook. The codebook must define instrument type, platform/segment, status, deletion, and date fields, including timezone/epoch and sentinel semantics.
2. Authoritative classification evidence that distinguishes ordinary equity from ETFs, debt, preference shares, and other instruments, and mainboard from Emerge/SME. A broad series label or populated numeric code without its official definition is insufficient.
3. Independently evidenced effective listing/status dates. A current snapshot date is not a listing effective date; SME-to-mainboard eligibility requires a verified effective migration/listing event.
4. For BSE, a source-authenticated current security master and its official field/code definitions, including security code, ISIN, instrument class, platform, and active/listed/trading status. `EQUITY_L.csv` alone does not provide these facts.
5. A reviewed mapping from the exchange-specific instrument/listing reference to HAMSA's separate exchange listing identity, with ambiguous, invalid, conflicting, or placeholder ISINs quarantined.

**Qualification result:** These files are useful for format inspection and candidate ISIN/symbol cross-checking. They are not sufficient to establish a verified 2026-11-09 NSE snapshot, an effective-dated listing history, mainboard platform classification, or ordinary-equity eligibility. No row is approved by this report.

## Project references

- [Current master field mapping](current-master-field-mapping.md)
- [Mainboard classification rules](mainboard-classification-rules.md)
- [Current EOD source qualification](current-eod-source-qualification.md)

## Source documentation references added in the ingestion review

- [NSE Master Data Specification v1.6](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE-Masters%20Data-v1.6.pdf) documents the legacy time epoch and the legacy local database update field, together with the legacy deletion, trade permission, status and dummy/test definitions. It does not by itself prove that every ISO-tagged MII field is a one-to-one alias of a legacy field.
- [NSE circular MSD60315](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf) documents the daily MII security filename form and website dissemination. It does not authenticate the supplied local files or establish their actual publication time.
