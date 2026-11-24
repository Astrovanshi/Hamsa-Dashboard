# Open-Source Indian Market Data Evaluation

**Assessment date:** 2026-11-10
**Scope:** Candidate source/code review for HAMSA's NSE/BSE mainboard ordinary-equity research. No package was installed and no bulk dataset was downloaded.

## Executive assessment

**TejHQ's `tej-bazaar` and its `tejhq/indian-markets` Parquet dataset are the strongest practical reuse candidate.** Its public dataset is already laid out for analytical access, and the project has exchange ingestion, historical backfill, delivery data, symbol-history and corporate-action pipelines. HAMSA should treat it as a secondary historical source, not as its canonical identity, classification, or point-in-time record.

The dataset is not a drop-in HAMSA universe. TejHQ's series filters are broader than HAMSA's approved mainboard ordinary-equity definition; the reviewed code does not establish a reliable official mainboard/non-equity classification gate. Its historical identity and adjustment logic are useful research aids but do not meet HAMSA's reviewed effective-dated mapping and point-in-time requirements. The dataset's terms permit personal local research under TejHQ's terms, while TejHQ says it does not hold an NSE/BSE license or grant exchange rights. This is a source-rights limitation, not a code-license question.

Recommendation: reuse TejHQ's **published raw, unadjusted Parquet price and separate delivery tables for backfill candidates**, after HAMSA's own classification and identity validation. Keep HAMSA's official-file path for current daily updates and canonical provenance. Do not embed TejHQ's downloader or its symbol-chain/adjustment logic in HAMSA.

## What was inspected

- TejHQ repository structure and source: [repository](https://github.com/tejhq/tej-bazaar), especially [`pipeline/parse.py`](https://github.com/tejhq/tej-bazaar/blob/master/pipeline/parse.py), [`pipeline/transform.py`](https://github.com/tejhq/tej-bazaar/blob/master/pipeline/transform.py), [`pipeline/instrument.py`](https://github.com/tejhq/tej-bazaar/blob/master/pipeline/instrument.py), [`pipeline/symbol_history.py`](https://github.com/tejhq/tej-bazaar/blob/master/pipeline/symbol_history.py), and [`pipeline/isin_backfill.py`](https://github.com/tejhq/tej-bazaar/blob/master/pipeline/isin_backfill.py).
- TejHQ's [dataset card and public preview](https://huggingface.co/datasets/tejhq/indian-markets), [dataset terms](https://tejhq.dev/data-terms), and [API documentation](https://tejhq.dev/docs).
- Candidate repository code, README/license files and activity pages listed in the comparison below.
- HAMSA's existing [architecture](architecture.md), [official EOD ingestion guide](real-eod-ingestion.md), and current implementation/schema.

The Hugging Face dataset page and table preview were inspected for schema, sample rows, repository layout and the displayed dataset revision. **Parquet bytes were not downloaded or opened locally.** The inspected dataset revision was current through 2026-11-06, so it cannot be compared row-for-row with HAMSA's local 2026-11-09 exchange files. Therefore no exact-date price/volume parity result is claimed. A single exchange-year Parquet file is not considered a small sample; downloading it was outside this inspection.

## TejHQ architecture and dataset

### Pipeline

The repository is a Python ETL project. Its pipeline parses official NSE and BSE bhavcopy/report inputs, normalizes rows, writes Parquet, rebuilds derived tables, and publishes the dataset. Scheduled GitHub Actions run evening jobs, retry, sweep recent sessions, and check expected sessions/gaps. The code therefore offers a useful working reference for exchange file parsing, repair/reprocessing, session reconciliation, and Parquet publication. A schedule is not an SLA; the project itself documents retries and historical missed-session recovery.

The package currently targets Python 3.11+ and uses Polars, PyArrow, Requests/curl-cffi, exchange calendars, Hugging Face tooling, Typer, and other packages. Its code is MIT licensed ([license](https://github.com/tejhq/tej-bazaar/blob/master/LICENSE); [dependency list](https://github.com/tejhq/tej-bazaar/blob/master/pyproject.toml)). **HAMSA need not install these dependencies to read Parquet with its existing DuckDB stack.** The code license does not license the underlying exchange data.

### Published layout and observed schema

The dataset card documents exchange/year Parquet paths, with related trees for raw prices, adjusted prices, corporate actions, symbol history, universe and delivery. The public preview showed an NSE table with fields including `date` (date32), `symbol` (string), `series` (string), `isin` (string, nullable), `name` (string), OHLC/last/previous close (float64), `volume` (int64), `turnover` (float64), and `trades` (int64); partition metadata is also exposed in the preview. Sample rows reach back to 2010 and have null ISINs in the pre-2012 portion. This is a preview inspection, not a local-file or checksum verification. Pin the exact dataset commit and inspect a single file's physical schema before implementation.

TejHQ documents DuckDB access with `read_parquet`; DuckDB can read Parquet directly. HAMSA can consume a locally archived individual file without adopting TejHQ's Python package. The exact HF filesystem/remote access path may require extra filesystem support, so the proposed integration uses locally downloaded files and HAMSA's existing raw archive, not an unverified remote query path.

### Coverage claims versus verified coverage

TejHQ publishes NSE coverage from 2010-01-04 and BSE coverage from the CMTS cutover, 2024-07-08, with roughly 4,100 NSE sessions and around 2,200 instruments per day as project-level descriptions. These are **published project coverage claims**, not an independent completeness audit. The observed preview confirms old NSE rows exist, including pre-2012 null-ISIN rows. It does not prove every eligible listing/session is present, that all listed securities were included, or that the universe is survivorship-free.

The project explains that legacy BSE records before the clean security-code/modern ticker bridge are not included in the same form; its BSE bulk history begins at the modern CMTS format cutover. BSE's earlier history is therefore a material gap. NSE's older rows lack ISIN and trades in some periods. Neither published date range should be read as complete historical security-master or mainboard-universe coverage.

### Universe and data-quality mismatch

`pipeline/transform.py` uses NSE series `EQ`, `BE`, and `BZ`, and BSE groups `A`, `B`, and `T`. These are broad exchange trading/series buckets, not HAMSA's required proof that an instrument is an ordinary share on the mainboard. The code does not show an authoritative mainboard/ordinary-equity classification join. It consequently cannot establish the required exclusion of ETFs and other non-equity instruments. For example, HAMSA's observed NSE source has NIFTYBEES in `STK/EQ`; an `EQ` predicate alone cannot classify it as an ordinary share. No claim is made that the specific NIFTYBEES row was checked in TejHQ's Parquet file.

The transform performs useful null, volume and price validation. It also keeps the first duplicate on `(date, symbol)`. That key omits venue/security/series and does not quarantine conflicting duplicate rows. This is not an acceptable replacement for HAMSA's stricter listing/session identity and conflict handling. The raw project tables should be treated as a source dataset, not as proof of HAMSA acceptance.

### Identity, symbols, and delisted securities

Modern source rows retain reported ISIN where present; early NSE rows may not. TejHQ backfills some pre-ISIN history by joining continuous symbols around the period when ISINs become available. Its instrument-chain code also joins same-symbol ISIN intervals with gaps up to 30 days and selects a chain identity. This is a useful candidate-linking aid, but symbol continuity and a time-gap heuristic are not independent evidence that histories belong to one legal security. It can be unsafe across ticker reuse, changed ISINs, reorganizations, or successor/predecessor securities.

Symbol-history intervals are inferred from observed price rows rather than necessarily from official legal/effective listing notices. Historical prices for inactive securities may remain, but this is not a complete historical listing master or a verified inventory of delisted securities. HAMSA must keep unresolved or ISIN-less rows outside canonical security histories until reviewed evidence resolves them. Never merge price or financial history for a successor merely because a provider chain connects it.

### Corporate actions and delivery

TejHQ ingests exchange corporate-action files and exposes event and adjusted-price data. Its retrospective adjustment series is built from the action set, including split, bonus, and dividend calculations; rights, buybacks, mergers/demergers and other action types may have no price factor or use a neutral factor in the described implementation. It uses later-confirmed events to adjust earlier prices. The reviewed dataset does not supply the complete HAMSA requirements for event publication timestamp, source revision history, and historical availability. **Do not use TejHQ adjusted prices/factors in historical screens or treats them as canonical.** Raw unadjusted OHLC is the safer backfill input. Actions can be retained as candidate research evidence for later sourced review.

Delivery is stored separately by exchange. NSE MTO history is described from 2010 and applies to `EQ`; it has date, symbol, series, delivery quantity and percentage and no ISIN. BSE gross-deliverable history begins at the 2024-07-08 cutover and uses BSE identifiers mapped through that session's source data. Keep delivery venue-specific; join only through reviewed effective-dated listing mappings and never aggregate delivery percentages across venues.

### Data terms and rights

The source code is MIT. The dataset is a separate artifact. TejHQ's data terms (updated 2026-11-08) state that its service permits personal-use/local research, private dashboards, and local storage/backups, while prohibiting raw-data publication/mirroring/resale. TejHQ also states it has no NSE/BSE exchange license or written exchange clarification and cannot grant exchange rights. These terms describe what TejHQ permits under its own service terms; they do **not** establish that exchange terms permit HAMSA's intended archival or use. This unresolved source-rights boundary must remain visible in provenance/admission status and should be resolved before relying on the dataset beyond a limited evaluation.

## Candidate comparison

Ratings are relative to HAMSA's use. “Claim” means published by the project, not independently complete/verified.

| Project | NSE EOD / BSE EOD | Historical depth / delivery | Actions and identity continuity | Mainboard, delisted coverage | Format, maintenance, license, dependencies |
|---|---|---|---|---|---|
| **TejHQ `tej-bazaar` + `indian-markets`** | Both exchanges. Project claims NSE from 2010-01-04 and BSE from 2024-07-08. | NSE price and delivery from 2010 claimed; BSE price/delivery from 2024 cutover claimed. Dataset preview demonstrates old NSE rows, not complete coverage. | Action event table and retrospective adjustments; symbol history and heuristic ISIN chains. Not HAMSA-grade PIT or reviewed continuity. | Broad series filters; no sufficient mainboard/ordinary-equity proof. Historical/inactive prices may persist, but no complete delisted master claim. | Annual/exchange Parquet and associated trees; straightforward DuckDB local-file read. Active scheduled pipeline and reconciliation jobs. MIT code; dataset terms separate and exchange rights unresolved. Python 3.11+, Polars, PyArrow and other deps; can avoid them. **Best backfill candidate with gates.** |
| [jugaad-data](https://github.com/jugaad-py/jugaad-data) | NSE archive/history only; no BSE EOD coverage. | NSE historical stock/index data and daily archives; no consistent HAMSA coverage guarantee. Delivery available through archive reports but not a normalized revision store. | No full action/ISIN-continuity model. | No reliable mainboard/non-equity classifier or historical delisted universe. `EQ` defaults are not enough. | Python library returning CSV/Pandas-like data, no Parquet history model. Mature community project but source paths use browser-style calls to NSE endpoints, including undocumented/internal routes. Public-domain-like project license; exchange data rights separate. Not chosen. |
| [BennyThadikaran/eod2](https://github.com/BennyThadikaran/eod2) and [eod2_data](https://github.com/BennyThadikaran/eod2_data) | NSE-only; no BSE. | Project claims NSE EOD back to 1995; delivery and split/bonus adjustments. Data repo is periodically updated, not a complete exchange audit. | Tracks symbols/ISIN changes in a limited model; no full corporate-action/PIT lineage. Adjustments exclude dividends and other actions; stale/delisted symbols can be removed. | Mainboard filter is not established; survivorship controls require special handling/configuration. Not a complete historical classification source. | CSV-oriented desktop/Python tooling, not DuckDB/Parquet-first. GPL-3.0 for code; data/source rights separate. GPL and its narrower action handling make it a secondary reference, not the selected base. |
| [yfinance](https://github.com/ranaroussi/yfinance) | Yahoo-ticker based NSE/BSE symbols; no full exchange-universe EOD guarantee. | Per-symbol history varies; no verified comprehensive Indian listing/session coverage. Delivery data absent. | Yahoo adjusted series/actions can be useful for spot checks, but no official ISIN continuity or complete event-revision trail. | Not an exchange-classified universe; delisted and renamed ticker histories can be incomplete. | Easy Pandas integration but not canonical Parquet/provenance. Active unofficial Yahoo wrapper; Apache-2.0 code. Yahoo source terms are separate, and yfinance is explicitly unofficial. Secondary comparison only; no install. |
| [hemenkapadia/getbhavcopy](https://github.com/hemenkapadia/getbhavcopy) | Historically targeted both NSE and BSE daily/historical downloads. Current reliability is doubtful: old downloader depended on endpoints that changed or stopped. | Historical file access described by project; no independently verified complete history or delivery continuity. | No robust reviewed ISIN/corporate-action identity history established. | Mainboard classification and delisted completeness not established. | Older desktop/Windows-oriented tool; no DuckDB/Parquet-native design. Repository did not expose a clear software license in reviewed files; do not reuse code until clarified. Maintenance materially older. |
| [BennyThadikaran/NseIndiaApi](https://github.com/BennyThadikaran/NseIndiaApi) | NSE only; includes historical/archives and delivery methods via NSE JSON/archive interfaces. No BSE coverage in this project. | Per-security/API history rather than independently complete bulk coverage. | No HAMSA-grade revisions or identity continuity; exchange metadata can assist source discovery but is not a reviewed mapping ledger. | Some classification endpoints exist, but they rely on unofficial routes and need official source validation; no complete historical/delisted universe. | Python API wrapper, not Parquet-first. GPL-3.0; actively maintained but explicitly unofficial and uses undocumented/internal NSE endpoints with cookies/throttling. Excluded by HAMSA's access-method rule. |

### Source references for candidate notes

- [jugaad-data archive implementation](https://github.com/jugaad-py/jugaad-data/blob/master/jugaad_data/nse/archives.py), [history implementation](https://github.com/jugaad-py/jugaad-data/blob/master/jugaad_data/nse/history.py), [license](https://github.com/jugaad-py/jugaad-data/blob/master/LICENSE.YOLO.md).
- [eod2 README/code](https://github.com/BennyThadikaran/eod2), [eod2 historical data](https://github.com/BennyThadikaran/eod2_data), [eod2_utils](https://github.com/BennyThadikaran/eod2_utils).
- [yfinance repository and license](https://github.com/ranaroussi/yfinance).
- [getbhavcopy repository](https://github.com/hemenkapadia/getbhavcopy).
- [NseIndiaApi repository](https://github.com/BennyThadikaran/NseIndiaApi) and [documentation](https://benny-thadikaran.github.io/NseIndiaApi/).

## HAMSA-specific compatibility conclusion

1. **Direct DuckDB consumption is practical at file level.** Download and archive selected Parquet files, then read them with DuckDB. Pin the dataset repository revision, file checksum, tree/path, source dataset version, import timestamp, and parser/normalizer version. Do not make remote HF access a runtime dependency.
2. **Raw source equivalence is limited.** The Parquet file is a TejHQ-produced normalized dataset, not the original exchange file. Preserve it as an immutable TejHQ source artifact and mark its underlying exchange provenance as reported by TejHQ. Do not fabricate original exchange-file checksums or claim HAMSA parsed an exchange original.
3. **Identity is a gating join.** Map by validated ISIN plus effective-dated, reviewed listing records. Preserve NSE and BSE listing observations separately. Never accept symbol/name resemblance or TejHQ's inferred chain alone. ISIN-null rows remain unresolved/quarantined for canonical use.
4. **Classification is a separate gate.** Join candidate rows only to HAMSA's reviewed official exchange classification snapshot. Series is not eligibility. Ambiguous class, inactive status, SME/Emerge, ETF or non-equity instrument stays outside the investment universe.
5. **Use raw OHLC and venue-specific delivery only.** Exclude TejHQ adjusted series from point-in-time screens unless independently rebuilt from HAMSA's event publications and versioned factor methodology. Delivery is joined within venue and not averaged or combined.
6. **No exact data reconciliation yet.** Dataset preview date is 2026-11-06, while HAMSA's representative local files are 2026-11-09. A later overlap comparison is a required acceptance test, not a completed result.
