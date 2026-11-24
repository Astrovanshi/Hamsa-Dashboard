# TejHQ Parquet Compatibility and Data Parity Report

**Test date:** 2026-11-10

**Environment:** Python 3.11.9; DuckDB Python client 2.0.0; DuckDB engine v2.0.0.
**Scope:** Small local-file compatibility and parity experiment only. No application code, schema, ingestion adapter, or dependency was changed.

## Result

**DuckDB compatibility: pass.** DuckDB 2.0.0 opened the actual TejHQ Parquet files directly, with no added dependency. Filters by date, symbol and ISIN worked. A path matching TejHQ's `exchange/year=YYYY/file.parquet` layout worked both with and without `hive_partitioning=true`.

**SBI EOD parity for 2026-11-09: pass for both venues.** NSE and BSE TejHQ price rows matched their respective local official full-market source rows exactly for open, high, low, close, volume and traded value. NSE and BSE prices are different and remain separate; no averaging was performed.

**Delivery parity: not tested because no matching official source observation is present locally.** The TejHQ delivery sample ends 2026-11-06, while HAMSA's local NSE delivery file is for 2026-11-09. The local BSE full-market EOD file has no delivery fields and the retained BSE per-scrip file is price-only. TejHQ provides delivery fields, but this experiment cannot establish their parity against official delivery data.

This experiment does **not** establish full-universe completeness, mainboard eligibility, historical identity continuity, or exchange data rights. The sample itself confirms why independent classification and identity controls are required.

## Actual files inspected

The five exact Parquet byte streams are under the git-ignored `data/raw/tejhq-sample/` tree. The four 2026 files were fetched from the public Hugging Face dataset's `main` path on 2026-11-10; the NSE 2010 partition was fetched from the displayed dataset revision `62a4096`. Files were placed in the published exchange/year layout. The latest NSE/BSE price partitions cover through 2026-11-09; delivery partitions cover through 2026-11-06. The separate NSE 2010 partition was included to inspect historical null ISIN behavior.

| Local sample | Published dataset path | Bytes | SHA-256 |
|---|---|---:|---|
| `data/raw/tejhq-sample/nse/year=2026/nse_2026.parquet` | `nse/year=2026/nse_2026.parquet` | 16,525,861 | `3A51CA886A9B54FEBF8ECD07042A6728E4ADADBC3F55335091A0258AD6335934` |
| `data/raw/tejhq-sample/bse/year=2026/bse_2026.parquet` | `bse/year=2026/bse_2026.parquet` | 13,899,589 | `0427749CC74A40FCDC93A2A0FAB1ACC9F9A588A5B15EF436408785DA5A5739F6` |
| `data/raw/tejhq-sample/delivery/nse/year=2026/nse_2026.parquet` | `delivery/nse/year=2026/nse_2026.parquet` | 5,451,819 | `48D560C789594DBE7BA01E31AFA721414CDFEA8C12A59CDDC443E23C744777F1` |
| `data/raw/tejhq-sample/delivery/bse/year=2026/bse_2026.parquet` | `delivery/bse/year=2026/bse_2026.parquet` | 4,796,416 | `70862EA7383813FB3EAD200FC68459614EFB02136656429850EB3C0D3AC4E8B2` |
| `data/raw/tejhq-sample/nse/year=2010/nse_2010.parquet` | `nse/year=2010/nse_2010.parquet` | 8,354,797 | `3508FAA6DC007783C61324BDFDAB40AA7A224CD895662544D1AA139D0E2E7017` |

The samples total about 49.0 MB (decimal). The Git ignore rule `/data/raw/` covers all of them; `git check-ignore` confirmed the sample path is ignored. They are not staged or tracked.

Dataset pages observed during retrieval: [NSE 2026 partition](https://huggingface.co/datasets/tejhq/indian-markets/tree/main/nse/year=2026), [BSE 2026 partition](https://huggingface.co/datasets/tejhq/indian-markets/tree/main/bse/year=2026), [NSE delivery 2026](https://huggingface.co/datasets/tejhq/indian-markets/tree/main/delivery/nse/year=2026), [BSE delivery 2026](https://huggingface.co/datasets/tejhq/indian-markets/tree/main/delivery/bse/year=2026), [NSE 2010 partition](https://huggingface.co/datasets/tejhq/indian-markets/tree/main/nse/year=2010). The dataset root displayed revision `6cf4d20`; individual directory pages displayed different commit markers, including `d4cc8de` for delivery. Because those pages did not consistently expose an immutable per-file commit, the SHA-256 values above identify the exact tested bytes. A future ingestion should resolve and record an immutable commit/file revision as well as the checksum.

## DuckDB schema and compatibility

### Price files

NSE and BSE price files have the same 16 fields:

| Field | DuckDB type | Observations |
|---|---|---|
| `date` | `DATE` | Calendar date; no timestamp component. |
| `symbol`, `series`, `isin`, `name` | `VARCHAR` | `isin` nullable. |
| `open`, `high`, `low`, `close`, `last`, `prev_close` | `DOUBLE` | Decimal price values. |
| `volume` | `BIGINT` | Integer shares/units. |
| `turnover` | `DOUBLE` | Numeric traded value; matched official INR transfer value on the parity row. |
| `trades` | `BIGINT` | Integer number of trades; nullable by schema/source. |
| `year` | `INTEGER`; `month` | `TINYINT` | Also present in the Hive-style path; values matched the `year=2026` path in the tested files. |

The NSE 2026 file had 572,992 rows and dates 2026-01-01 through 2026-11-09. The BSE 2026 file had 526,959 rows over the same date range. The NSE 2010 file had 347,026 rows from 2010-01-04 through 2010-12-31.

### Delivery files

Both delivery files have `date DATE`, `symbol VARCHAR`, `series VARCHAR`, `volume BIGINT`, `delivery_qty BIGINT`, `delivery_pct DOUBLE`, `year INTEGER`, and `month TINYINT`. The NSE delivery file had 523,221 rows and the BSE file 524,242; both covered 2026-01-01 through 2026-11-06. Delivery has no ISIN field, so it must be linked through a reviewed, venue-specific listing mapping for the same date and symbol/series.

### Partitioning and queries

The source layout is Hive-style by exchange and year (for example `nse/year=2026/nse_2026.parquet`). Each tested Parquet file also physically contains `year` and `month` columns. DuckDB successfully read the nested path with default behavior and with `hive_partitioning=true`. In Hive mode the path year is exposed as `BIGINT`; the physical year is `INTEGER`. Values agreed in every tested row (`year <> 2026` count was zero). HAMSA should cast partition year to its canonical type and avoid treating the path key and payload column as independent facts.

Direct filters succeeded:

```sql
SELECT date, symbol, series, isin, open, high, low, close, volume, turnover
FROM read_parquet('data/raw/tejhq-sample/nse/year=2026/nse_2026.parquet')
WHERE date = DATE '2026-11-09'
  AND symbol = 'SBIN'
  AND isin = 'INE062A01020';
```

This returns one NSE row. Equivalent BSE filtering returned one BSE row. The 2010 NSE rows contain a `NULL` `isin`; SQL `IS NULL` counted all 347,026 rows, while equality against an ISIN returned no rows. DuckDB preserved nulls; HAMSA must keep these records unresolved rather than substituting an ISIN or zero.

Duplicate checks found zero repeated `(date, symbol, series)` groups in the two 2026 price files and the two 2026 delivery files. This is only a result for these files, not proof the provider never publishes duplicates. A future adapter must still detect duplicates/conflicts and keep the original rows and source locations.

### Read performance

On the local project environment, warm in-process full scans running `count(*)` and `sum(volume)` had these five-run median times:

| File | Rows | Median elapsed |
|---|---:|---:|
| NSE 2026 | 572,992 | 0.01428 s |
| BSE 2026 | 526,959 | 0.01266 s |
| NSE 2010 | 347,026 | 0.01077 s |

Seven warm symbol/date filtered runs returned median times of 0.01030 s for NSE 2026 and 0.00957 s for BSE 2026. These are small-file local, warm-cache measurements, not cold-disk or production-throughput guarantees. They demonstrate that direct DuckDB reads are practical for this sample without a Pandas/Polars conversion step.

## Official-file reconciliation: 2026-11-09

Source rows were read from HAMSA's locally retained official NSE UDiFF ZIP and BSE full-market UDiFF CSV under `data/raw/real/eod/`. Match key for this check: date plus ISIN and the relevant exchange's source row. Traded value is NSE/BSE `TtlTrfVal`; TejHQ `turnover` was compared as supplied. No adjusted price series was used.

| Venue / source observation | Open | High | Low | Close | Volume | Traded value (INR) |
|---|---:|---:|---:|---:|---:|---:|
| NSE official UDiFF, `SBIN`, `EQ`, ISIN `INE062A01020` | 1,030.00 | 1,048.60 | 1,022.30 | 1,042.00 | 24,065,897 | 24,974,519,875.55 |
| TejHQ NSE Parquet, same session/symbol/series/ISIN | 1,030.00 | 1,048.60 | 1,022.30 | 1,042.00 | 24,065,897 | 24,974,519,875.55 |
| **NSE delta (TejHQ − official)** | **0.00** | **0.00** | **0.00** | **0.00** | **0** | **0.00** |
| BSE official UDiFF, scrip code `500112`, `SBIN`, `A`, ISIN `INE062A01020` | 1,029.50 | 1,048.90 | 1,022.15 | 1,041.45 | 1,456,011 | 1,512,208,913.00 |
| TejHQ BSE Parquet, same session/symbol/series/ISIN | 1,029.50 | 1,048.90 | 1,022.15 | 1,041.45 | 1,456,011 | 1,512,208,913.00 |
| **BSE delta (TejHQ − official)** | **0.00** | **0.00** | **0.00** | **0.00** | **0** | **0.00** |

For this SBI session, all six compared fields matched exactly at both exchanges. This is a successful one-security/one-session parity test, not universe-wide reconciliation or a provider accuracy guarantee. It does not justify averaging venues: the venues had distinct volumes, traded values, and prices.

### Delivery comparison

TejHQ delivery files in this sample end on 2026-11-06. HAMSA's retained NSE official full-delivery file is dated 2026-11-09, so the same-date join is absent. That local official row reports SBI volume 24,065,897, delivery quantity 11,162,506, and delivery percentage 46.38%; TejHQ has no Nov 9 delivery row to compare. The local BSE full-market price file carries no delivery fields, and the existing BSE SBI per-scrip file is price-only. Therefore **no NSE or BSE delivery parity result is claimed**. Delivery values must remain venue-specific and no value should be filled from another source/session.

## Identity, classification, and historical behavior

### Identity and exchange listings

- On 2026-11-09 both TejHQ exchange files contain SBI with ISIN `INE062A01020` and symbol `SBIN`; NSE series is `EQ`, BSE series is `A`. The same ISIN supports mapping to one HAMSA security, while the exchange and source row retain two distinct listing identities.
- The TejHQ BSE row contains no BSE scrip code. The local official BSE file has `FinInstrmId=500112`; mapping TejHQ's BSE row to HAMSA's listing still requires an official/effective-dated mapping. The price dataset alone does not carry all HAMSA instrument references.
- The 2010 NSE price file has NULL ISIN on every row, including SBI. It cannot safely support ISIN-based canonical history without independently reviewed effective-dated evidence. Symbol equality alone is not sufficient.
- In the 2026 BSE file the symbol `A1L` appears with ISIN `INE911Z01017` through 2026-01-07 and `INE911Z01025` starting 2026-01-08. This concrete identifier change demonstrates why `(exchange, symbol)` alone cannot be the security key. Preserve both source observations and resolve the security/listing relation with authoritative effective-dated evidence; do not infer a merger or merge price histories from the symbol.
- Within the 2026 price partitions, 54 NSE symbols and 47 BSE symbols occur with more than one ISIN over the year. There were no same-day duplicate `(date,symbol,series)` groups in the tested files. The multi-ISIN cases require historical mapping review and are not automatically identity errors or safe continuity evidence.

### Mainboard and instrument exclusions

The actual NSE sample contains `NIFTYBEES`, series `EQ`, ISIN `INF204KB14I2`, name `NIP IND ETF NIFTY BEES`. The BSE sample contains the same symbol/ISIN as series `B`, named `NIPPON INDIA ETF NIFTY BEES`. Thus a series predicate alone would admit a known ETF on both venues. TejHQ Parquet does not carry the official classification/status fields HAMSA needs to prove ordinary mainboard equity. All source rows must pass HAMSA's independent, reviewed exchange-classification snapshot; SME/Emerge and non-equity rows remain excluded or quarantined.

### Inactive securities and survivorship

The 2010 NSE file has 1,520 distinct symbols; 681 of those symbol strings do not appear in the 2026 NSE partition. That establishes that the inspected 2010 partition retains some historical rows absent by the sampled 2026 year, but does not identify which absences are delistings, reorganizations, renamed securities, scope changes, or provider gaps. The two year files do not establish a complete historical listing master or survivorship-free coverage. TejHQ's separate symbol-history and universe artifacts were not imported in this experiment; source review indicates symbol history is derived from observed price rows, not a replacement for effective-dated official listing notices.

### Corporate actions and point-in-time use

Only the unadjusted `nse` and `bse` price files were downloaded for parity. No adjusted Parquet file or corporate-action Parquet file was consumed. TejHQ publishes these in separate trees. The reviewed pipeline/source description indicates the adjusted series is retrospective and applies selected split/bonus/dividend calculations; it does not provide HAMSA's full event publication timestamp, source-revision, and as-known history, and some event classes are not factor-adjusted. Consequently:

- Use the tested raw exchange-specific price partitions as candidate price observations, not TejHQ adjusted prices, for historical screens.
- Keep corporate-action rows as secondary candidate evidence only until independently sourced, reviewed, revisioned, and assigned publication-time eligibility by HAMSA.
- `public_as_of` must not infer action availability from ex-date or a later-adjusted series. `hamsa_known_as_of` starts no earlier than actual local ingestion.
- A retrospective return view can be considered separately after the factor lineage and methodology are verified; this test makes no claim about that path.

## Integration recommendation

1. Keep HAMSA's official-file adapter as the daily primary path and DuckDB as the analytical store.
2. A local-file TejHQ Parquet reader is technically viable without new dependencies. It should archive exact bytes, SHA-256, dataset ID, immutable source revision, path, retrieval/ingestion timestamps, schema fingerprint, and row locator before parsing.
3. Label source provenance as a TejHQ-normalized dataset, not an original NSE/BSE file. Do not fabricate exchange-source checksums, publication timestamps, scrip codes, or effective dates.
4. Retain venue, source symbol, source series, ISIN, and source row as delivered. Resolve the security by validated ISIN and listing by official exchange-specific effective mapping; route missing/conflicting identity or classification to quarantine.
5. Treat all non-ordinary instruments as excluded after the official classification gate. NIFTYBEES is a sample proof that `EQ`/`B` cannot be the gate.
6. Preserve original price and delivery files separately. Delivery has no ISIN and ends earlier than the price sample; join it only with same-venue effective listing identity and an explicit freshness/coverage state.
7. Reconcile each exchange/session to official observations, preserving mismatches and exact source values. The exact SBI parity result is encouraging but too narrow to relax validation or conflict checks.

TejHQ's [data terms](https://tejhq.dev/data-terms) distinguish its code license from its dataset and say it has no NSE/BSE exchange license or written clarification. This experiment tests bytes and schema only; it does not resolve source licensing or admit a provider.

## Limitations and further investigation

- Only one 2026 annual file per venue, one 2010 NSE annual file, and one 2026 delivery file per venue were tested; no bulk archive or other years were downloaded.
- The SBI price parity covers one date, one security per venue, and the exact local official files. Full-universe/session/field reconciliation is outstanding.
- There is no overlapping local official delivery observation for TejHQ's 2026-11-06 delivery rows; no delivery accuracy conclusion is possible.
- Pre-2012 ISIN absence is visible in the 2010 sample; the provider's inferred symbol-based continuity must not be treated as official identity evidence.
- The BSE Parquet file lacks BSE scrip code; the NSE/BSE master join and effective listing histories remain HAMSA responsibilities.
- Official mainboard/SME, ordinary-equity, and active/listed/trading classifications are absent from these price rows. NIFTYBEES confirms this gap is material.
- Historical 681 symbol strings absent from the 2026 sample cannot be classified as delisted or renamed from this experiment; full historical inactive/delisted coverage remains unknown. Historical BSE depth and coverage before the dataset's modern cutover remain a separate gap.
- The adjusted-price and corporate-action Parquet bytes were not downloaded or tested. Their PIT suitability is not established.
- The sample files came from a mutable `main` URL; checksums pin these bytes, but future ingestion must retain an immutable dataset commit/object revision and checksum.
- Personal local use permitted by TejHQ's terms does not establish permission from the exchanges. Licensing/source-rights review remains separate from technical compatibility.

## Filesystem and Git outcome

The five Parquet samples remain under ignored `data/raw/tejhq-sample/`. `git check-ignore` confirmed the raw-data ignore rule. No packages were installed; no application code, schemas, adapters, existing planning documents, or ingestion files were changed. This report is the only workspace document added by this experiment; nothing was staged or committed.
