# Current Exchange Master Field Mapping

**Inspection date:** 2026-11-10 (Asia/Kolkata)
**Scope:** Current NSE/BSE mainboard ordinary equity membership only. This document records source evidence and unresolved classifications; it does not authorize inclusion of any row.

## Finding summary

- **NSE:** NSE documents daily Capital Market MII security files on the public All Reports page. The copies examined here were supplied locally; one is byte-identical to an earlier workspace artifact, but no receipt or authenticated publication metadata accompanies these exact copies. They carry ISIN, exchange instrument ID, symbol, series and status/classification-looking fields. The file alone does **not** safely establish mainboard versus Emerge or ordinary-equity class. See the corrected timestamp and field review in `docs/nse-cm-master-qualification.md`.
- **BSE:** An official current all-security daily EOD file was retrieved and inspected, but a current BSE security master was **not** obtained. BSE publishes a Scrip Master route through Members Help Desk and has published a field-format specification, but the current actual master snapshot and access conditions remain unverified. A 2022 standard-format specification is evidence of documented field semantics, not evidence that an actual 2026 master file has those exact fields unchanged.
- For both venues, names, symbols, security codes, `EQ`/`STK` series/instrument labels, or market capitalization are insufficient to infer HAMSA eligibility.

## NSE

### Observed file and sample

Official page: [NSE All Reports](https://www.nseindia.com/all-reports). NSE's 2024 circular specifies daily website publication of `NSE_CM_security_ddmmyyyy.csv.gz` on that page ([circular NSE/MSD/60315](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf)).

Inspected file: `NSE_CM_security_09112026.csv.gz`, labelled by filename for 09-Nov-2026. It has 38,415 data rows and 120 columns. SHA-256: `99cd4f092d1f14a749ba3cb7a98c1bedb5d9d4c74b9bd71bc3b3a0c1baf75c28`. One newly supplied copy is byte-identical to the existing workspace artifact under ignored `data/raw/real/eod/nse/`. The filename token is a claimed source/snapshot date, not independently verified publication time or an effective listing date.

Full actual header (spelling, order and case as observed):

```text
FinInstrmId,TckrSymb,SctySrs,FinInstrmNm,ISIN,NewBrdLotQty,ParVal,SctyTpFlg,BidIntrvl,TrckgInd,CallAuctnInd,BookClsrStartDt,BookClsrEndDt,NoDlvryStartDt,NoDlvryEndDt,IssdCptl,PrtdToTrad,PricRg,SctyStsNrmlMkt,ElgbltyNrmlMkt,SctyStsOddLotMkt,ElgbltyOddLotMkt,SctyStsRETDBTMkt,ElgbltyClsgAuctnSsn,SctyStsAuctnMkt,ElgbltyAuctnMkt,SctyStsAddtlMkt1,ElgbltyAddtlMkt1,SctyStsAddtlMkt2,ElgbltyAddtlMkt2,IsseDt,FrstPmtDt,MtrtyDt,MaxTradQtyPctg,ListgDt,RmvlDt,RadmssnDt,RcrdDt,IndxPrtcptnInd,AllOrNn,MinFill,SttlmTp,Dvdd,Rghts,Bns,Intrst,AGMtg,EGMtg,MktMakrSprd,MktMakrMinQty,AddtlInf,UpdDt,DelFlg,SpclExDt,Xchg,UnqPdctIdr,SctyTp,TickSz,XchgExclsv,Sts,ExDvddDt,ExBnsDt,ExRghtsDt,FinInstrmTp,InstrmTp,TradgPrtd,BuyBckInd,TradToTradInd,Indx,IndxInstrm,FinInstrmAttrbts,MinLot,UndrlygInstrmAsstClss,UndrlygInstrm,UndrlygFinInstrmId,BlckDealAllwdFlg,InstrmNm,MktTpAndId,UnitOfMeasr,PricQtQty,PricRgTp,MaxPric,MinPric,SttlmMtd,InitlMrgnTp,BuyInitlMrgnRate,IssePric,MaxSnglTxnQty,MaxSnglTxnVal,AsstClss,PricNmrtr,Spcfctn,PricDnmtr,GnlNmrtr,GnlDnmtr,LotNmrtr,LotDnmtr,DcmlstnPric,SrsSttlmTp,FreeFltCptl,SellInitlMrgnRate,RatgDtls,FinInstrmClssfctn,SpclMrgnTp,BuySpclMrgnRat,SellSpclMrgnRat,PreOpnAllwdFlg,ClssfctnTp,MtchgCrit,ValMtd,SLBMElgblty,Sgmt,Ccy,SttlmCcy,Rsvd02,Rsvd03,Rsvd04,Rsvd05,Rsvd06,Rsvd07
```

Fields `FinInstrmTp`, `InstrmTp`, `Xchg`, `XchgExclsv`, `Sts`, `TradgPrtd`, `FinInstrmClssfctn`, `ClssfctnTp`, `SctyTp`, and `Sgmt` were present but empty in the observed file. The NSE Master Data Specification v1.6 documents a 1980-01-01 epoch for analogous legacy master time/date fields and defines the legacy Local DB Update Date Time as a record update timestamp. `UpdDt` decodes to a 2026-11-09 source-clock maximum in the supplied files, but MII-to-legacy field correspondence and timezone are not fully established. It is not file publication evidence. Listing/removal/readmission values remain raw fields until current MII semantics and approved effective-date evidence are established.

Representative rows:

| FinInstrmId | TckrSymb | SctySrs | FinInstrmNm | ISIN | SctyTpFlg | SctyStsNrmlMkt | ElgbltyNrmlMkt | DelFlg |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3045 | SBIN | EQ | STATE BANK OF INDIA | INE062A01020 | 0 | 6 | 1 | N |
| 11128 | SBIN | AF | STATE BANK OF INDIA | INE062A01020 | 0 | 1 | 0 | N |
| 10576 | NIFTYBEES | EQ | NIP IND ETF NIFTY BEES | INF204KB14I2 | 4 | 1 | 1 | N |

The same ISIN/symbol appears in multiple instrument/series rows. The NIFTYBEES row demonstrates that series `EQ` plus `FinInstrmTp=STK` in the daily EOD is not an ordinary-share test. The apparent association of `SctyTpFlg=4` with the observed ETF and `0` with SBIN is sample evidence only; without an official current code definition, HAMSA must not use it as a definitive ETF/equity mapping.

### Field-level mapping

| HAMSA classification | Official source field | Evidence | Confidence | Unresolved issue |
| --- | --- | --- | --- | --- |
| Security identifier | `ISIN` | Present in daily MII file; sample SBIN `INE062A01020`; EOD row carries same ISIN | High for field presence; row semantics still require validation | Verify format, blank/placeholder handling and uniqueness/cardinality rules against NSE documentation |
| Venue instrument/listing reference | `FinInstrmId` | Present; SBIN EQ ID `3045`; other SBIN series use distinct IDs | High for field presence | Confirm whether/how ID reuse is prevented across time and whether this identifies listing, instrument, or segment product |
| Symbol | `TckrSymb` | Present; e.g. `SBIN` | High | Historical symbol intervals need dated source revisions, not current snapshot backdating |
| Series | `SctySrs` | Present; sample values include `EQ`, `BE`, `SM`, `MF`, `AF`, and others | High for field presence | Official complete codebook/mapping and whether any code denotes SME/mainboard not established here |
| Instrument type | `SctyTpFlg`, `SctyTp`, `FinInstrmTp`, `InstrmTp`, `FinInstrmClssfctn`, `ClssfctnTp` | Columns exist; populated `SctyTpFlg` values include 0,1,2,3,4; several other candidate fields are blank in observed sample | Low for classification | Official code meanings and which field is normative for ordinary shares are unresolved. Do not infer from observed names or codes |
| Mainboard versus SME | No confirmed normative populated field | `SctySrs` includes `SM`; no verified official mapping between series and platform in inspected file | Low / unresolved | Need an official source/codebook explicitly distinguishing NSE mainboard from Emerge and effective migration dates |
| Ordinary equity | No confirmed normative populated field | ETF `NIFTYBEES` appears with `SctySrs=EQ`; EOD labels it `STK` | Low / unresolved | Need verified official security-type code mapping; ISIN prefix/name heuristics are not sufficient |
| Active/trading status | `SctyStsNrmlMkt`, `ElgbltyNrmlMkt`, `DelFlg`, `PrtdToTrad`, `TradgPrtd`; also `RmvlDt`, `RadmssnDt` | Fields exist; SBIN EQ observed as status `6`, eligible `1`, delete `N`; ETF example status `1`, eligible `1`, delete `N` | Low until codebook obtained | Meaning and eligible status combinations are not verified. `DelFlg=N` alone cannot prove active/mainboard eligibility |
| Snapshot/publication date | Filename token `09112026`; NSE circular documents `NSE_CM_security_ddmmyyyy.csv.gz` daily naming | Supplied bytes have that filename token; NSE circular documents the daily filename pattern. Local file has no authenticated receipt or publication timestamp; gzip MTIME is zero. `UpdDt` is per-record update-like data, not a publication date. | Medium for claimed/source date convention; none for this file's publication time | Exact file publication date/time and snapshot capture provenance remain unverified |
| Effective listing date | `ListgDt`, potentially `RmvlDt` / `RadmssnDt` | Fields present as numeric values in observed rows | Low | Need official encoding and semantics confirmation before using as effective dates; snapshot date must not substitute |

## BSE

### Current master access and published format evidence

The BSE site documents a Scrip Master download through **Members → Information for Members → Members Help Desk → SCRIP.ZIP** in an [official BSE Equity Segment Master Circular](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=cb125690-a0f8-452a-ba6b-86cab98004bc&id=20230630-19). The public BSE site exposes the Members Help Desk link, but the master itself was not retrieved as an anonymously accessible current snapshot during this inspection. The BSE public page returned access denial to the non-browser research fetch; no credentials, alternate endpoint, or bypass was used. This does not prove that the member route always requires login; it means HAMSA has not yet verified access to the actual current file.

BSE's [Standardised Security Master file format](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44) describes a `BSE_EQ_SCRIP_DDMMYYYY.csv` and documents (among others) Scrip Code, Instrument Code, Group Name, Scrip Name, ISIN CODE, Security Type Flag (`EQ`, `MF`, `DB`, `GS`), Instrument status flag (`A` active, `S` suspend, `I` inactive), and Instrument Type (`E` equity trading; `D/C` debt). This is a dated published specification, not a verified current header/codebook; later changes, if any, cannot be confirmed without the current file/specification. Inspect the actual master header/body and its current accompanying documentation before adapter design.

### Field-level mapping

| HAMSA classification | Official source field | Evidence | Confidence | Unresolved issue |
| --- | --- | --- | --- | --- |
| Security code | `Scrip Code` (published 2022 spec); current file not inspected | Official format specification describes a numeric identifier | Medium for documented design, no current-file verification | Obtain current raw file and verify field name/type/cardinality |
| ISIN | `ISIN CODE` (published 2022 spec); current file not inspected | Official format specification identifies ISIN field | Medium for documented design, no current-file verification | Confirm populated for ordinary shares, non-equity, suspended and inactive records |
| Security name | `Scrip Name` (published 2022 spec); current file not inspected | Official format specification calls it full name | Medium for documented design, no current-file verification | Current header, text encoding, truncation and revision semantics unverified |
| Symbol | `Instrument Code` (published 2022 spec); current file not inspected | Official format specification says it contains security symbol | Medium for documented design, no current-file verification | Verify current mapping to UDiFF `TckrSymb` and change history |
| Instrument type | `Security Type Flag`; `Instrument Type` (published 2022 spec) | Older official format defines broad equity/mutual fund/debt/government categories and trading/debt instrument types | Medium, but not current-file verified | Broad `EQ` does not establish ordinary equity or mainboard; current values and newer code definitions needed |
| Mainboard versus SME | No confirmed field in inspected public format documentation | The documented fields above do not name a mainboard/SME platform classification | Low / unresolved | Need an official current field or a separate official exchange classification/listing-status source; no group/code inference |
| Ordinary equity | No confirmed field | Broad `Security Type Flag=EQ` in old spec; no proof it excludes ETFs/REITs/InvITs/partly-paid or other instruments | Low / unresolved | Need official current type taxonomy and classification method |
| Active/listed/trading status | `Instrument status flag` (`A`,`S`,`I`) (published 2022 spec) | Published old format describes Active, Suspend, Inactive | Medium for old format only | Current master uses this field unchanged? “Listed” vs tradable distinction and source-of-truth status remain unverified |
| Snapshot/publication date | Filename pattern `DDMMYYYY`; no current file | Format specification filename contains date | Low | Need actual current snapshot, page publication timestamp and whether date means generated, published or effective |
| Effective listing date | None confirmed in inspected old-format summary | The format description does not establish an effective-from field | Low / unresolved | Use sourced effective date from official listing notice/master only; never infer from snapshot date |

## Classification rule pending source confirmation

No NSE or BSE record enters the HAMSA current universe solely because it has an ISIN, an equity-like name, an `EQ` series, `STK` instrument type, or active/trading-like values. Inclusion requires an official, documented positive classification of (1) ordinary equity and (2) mainboard listing status, together with confirmed active/listed status on the relevant snapshot. Any unknown code, ambiguous relationship, or conflicting classification is quarantined. SME securities may be retained separately for reconciliation; they never enter the universe. SME migration starts eligibility only on its verified effective mainboard date.

## Source references

- NSE All Reports, which displayed daily EOD and MII security-file entries: [nseindia.com/all-reports](https://www.nseindia.com/all-reports).
- NSE circular documenting public daily MII-file naming and route: [NSE/MSD/60315](https://nsearchives.nseindia.com/content/circulars/MSD60315.pdf).
- BSE daily bhav-copy page: [BSE Bhav Copy](https://www.bseindia.com/markets/marketinfo/bhavcopy).
- BSE UDiFF bhav-copy format workbook: [UDiFF_BhavCopy_format.xlsx](https://www.bseindia.com/downloads1/UDiFF_BhavCopy_format.xlsx).
- BSE master-file route in official member circular: [BSE Equity Segment Master Circular (2023)](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=cb125690-a0f8-452a-ba6b-86cab98004bc&id=20230630-19).
- BSE published older field specification: [Standardised Security Master format](https://www.bseindia.com/markets/MarketInfo/DownloadAttach.aspx?attachedId=e99e2ca5-95d7-4173-83da-7774412bbb2d&id=20220531-44).
