# TejHQ Historical Parquet Import Pilot

**Status:** Adapter implemented and verified. The local real-data fixture run is deliberately quarantined because the project has no approved security/listing/classification mappings in the isolated verification database. Production admission of SBI remains blocked by the unresolved ordinary-equity classification recorded in `docs/mainboard-classification-rules.md`.

## What was implemented

- `src/hamsa/ingestion/tejhq_parquet.py` reads already-downloaded raw NSE or BSE Parquet files through DuckDB 2.0.0. It accepts one exchange, one requested session, and at most ten explicitly selected source symbols. Symbol is a bounded row selector only; it is never used to resolve identity.
- The adapter requires a non-branch Git commit identifier, dataset ID, original dataset path, source document date, first verified public date, and retrieval date. It preserves the exact bytes in the content-addressed raw archive before parsing, records SHA-256 and a deterministic schema fingerprint, distinguishes retrieval date/optional retrieval timestamp from actual system-generated capture, ingestion, and extraction times, and stores `file_row_number` as the reproducible source locator.
- Rows must have a valid non-null ISIN, exactly one approved effective ISIN mapping, exactly one venue listing, an approved effective listing-status review, and one approved instrument and platform classification covering the trade date. Known exclusions are counted out of scope; missing, unknown, conflicting, or ambiguous identity/classification is quarantined. No effective date is inferred from the dataset snapshot.
- `DuckDBRepository.append_eod_price_observation` validates typed provenance, listing/security/venue equality, units, finite values, price/quantity bounds, and source-revision lineage before atomically appending the registry and EOD observation. No update/delete operation was added.
- An atomic local sidecar manifest is written before archival and updated after the database transaction. `recover_archived_sources()` can resume archived-but-unprocessed imports using the content-addressed file, and can detect a committed database run whose manifest update was interrupted. It is local recovery metadata, not a database source of truth.
- `DuckDBRepository.eod_observations_as_of` selects source revisions under `public_as_of` or `hamsa_known_as_of`, uses the exchange calendar for date-only publication, requires actual source ingestion and extraction by the cutoff for HAMSA-known mode, and permits parser-version pinning for reproducible extraction snapshots.
- Each accepted row is reconciled against the active official observation for the same exchange listing and session. Both source rows remain unchanged. The stable comparison stream binds exchange/listing/session/official-secondary roles. No cross-exchange average, adjusted price, corporate action, or delivery observation is written.
- `scripts/ingest_tejhq_pilot.py` is a local-file CLI. It makes no network request and does not activate a provider.

No database schema, migration, dependency, official exchange adapter, dashboard, or discovery engine was changed in this adapter milestone. Schema version remains **3**. The four-table v3 migration implementation report is `docs/tejhq-schema-migration-implementation.md`.

## Data and accounting rules

- `accepted`: new normalized observation rows appended.
- `revised`: accepted rows that append a new TejHQ source/parser revision linked to an earlier TejHQ observation; not counted as independent accepted rows in the report.
- `duplicates`: exact repeated source rows in one Parquet extraction plus targeted records found on an idempotent same-source/same-parser retry.
- `rejected`: malformed/non-finite values or invalid price/quantity relationships; the row and reason are retained in quarantine.
- `quarantined`: validly parsed records whose ISIN, listing, status, or approved classification cannot be resolved uniquely.
- `out_of_scope`: verified non-equity, SME/other platform, or inactive listing. These records never become EOD investment-universe observations.
- `reconciled`: accepted source rows for which a matched or unmatched comparison record was appended. `not_compared` is a subset whose values were incomplete or no official counterpart existed.

Counts describe the current processing attempt, not cumulative history. A source row is `accepted` on its initial normalized append; a new source/parser observation that supersedes an existing one is `revised`; an already persisted source/parser/locator is `duplicate`. On retry, prior accepted rows count as duplicates, while rejected, quarantined, and out-of-scope rows are re-evaluated and retain those dispositions. Quarantine persistence is idempotent. Exact duplicate rows within one source extraction count only the extra copies as duplicates. A source row can also produce a new reconciliation result when a counterpart or comparator changes; `reconciled` counts newly appended comparisons and `not_compared` counts newly appended incomplete/unmatched results. `revised` is not added to `accepted`. Raw files and database source records remain immutable/revisioned.

## Verification results

### Portable synthetic tests

The portable tests create their own Parquet files with DuckDB and do not depend on ignored local samples. They cover cross-venue listing separation for one ISIN, accepted append and reconciliation, duplicate retry, changed-byte source revisions, parser revisions with stable source-document identity, out-of-scope ETF, unknown classification, missing/ambiguous ISIN, exact/conflicting duplicate rows, NaN rejection, archive-before-parse failure and recovery after deleting the input path, transaction rollback, crash after database commit and idempotent manifest recovery, and `public_as_of` versus `hamsa_known_as_of` with parser-version selection.

### Optional local real-file tests

`tests/test_tejhq_real_samples.py` is separate and skipped when ignored source files are absent on a clean checkout. In this workspace it inspected the actual NSE and BSE 2026 partitions and the NSE 2010 partition using DuckDB 2.0.0. The tests verified the SBI row values for 2026-11-09 against the retained official NSE/BSE EOD source files. Open, high, low, close, volume, and traded value matched exactly on each venue, independently. These tests also confirm that the real-file import path quarantines rows when no approved HAMSA identity/classification mapping is present and that the 2010 SBI row's NULL ISIN stays unresolved.

The exact sample byte checksums and downloaded source paths are listed in `docs/tejhq-parquet-compatibility-report.md`. Raw files are under `/data/raw/` and ignored by Git.

### Real-file pilot report from isolated empty identity DB

| Source file | Requested records | Accepted | Rejected | Quarantined | Duplicates | Revised | Out of scope | Reconciliation |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| NSE 2026 partition, 2026-11-09, SBIN + NIFTYBEES | 2 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| BSE 2026 partition, 2026-11-09, SBIN | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| NSE 2010 partition, 2010-01-04, SBIN | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |

Reasons: current SBI/NIFTYBEES rows have no reviewed mapping in the isolated verification DB; the 2010 SBI row has NULL ISIN. Those are quarantines, not claims that the securities lack real-world identity. The real SBI price parity was separately verified from the retained actual official files. Synthetic accepted-row tests validate the application boundary but do not provide real classification evidence.

## Local use

First ensure the chosen local DuckDB contains approved identity, effective listing, and classification evidence. This is currently not true for real SBI mainboard-ordinary eligibility: the NSE quote supports mainboard and active status, but the available ordinary-share field is not sufficient under the approved rule; BSE current-master classification remains unverified. Do not bypass the quarantine by adding a pilot allowlist.

Run from the project root with an already-downloaded file and the pinned environment:

```powershell
.\.venv\Scripts\python.exe scripts\ingest_tejhq_pilot.py `
  --database data\hamsa.duckdb `
  --archive-root data\raw\archive\tejhq `
  --file data\raw\tejhq-sample\nse\year=2026\nse_2026.parquet `
  --exchange NSE `
  --dataset-id tejhq/indian-markets `
  --dataset-revision 408bab9d85371d333cc18572a428934f4fad0112 `
  --dataset-path nse/year=2026/nse_2026.parquet `
  --source-document-date 2026-11-10 `
  --first-verified-public-date 2026-11-10 `
  --retrieval-date 2026-11-10 `
  --trade-date 2026-11-09 `
  --symbols SBIN,NIFTYBEES
```

Supply a real timezone-qualified `--retrieved-at` only when an actual retrieval timestamp is evidenced. The NSE 2026 sample is verified at file revision `408bab9d85371d333cc18572a428934f4fad0112`; its published file SHA-256 matches the retained bytes. The NSE 2010 sample is verified at `62a4096f74bc79f34be2a9d848e7831b51d9808b`, also with a matching SHA-256. The retained BSE 2026 sample is not verified: its hash differs from the current published file at `12ba6b3495817adcd442828519189bdbc610890c`, and that file page reports data through 2026-11-06 rather than the sample's 2026-11-09 row. The exact immutable commit containing the retained BSE bytes remains unresolved. Do not use the BSE sample as a provenance-complete import input. The adapter rejects branch names such as `main`; its hash-format check cannot independently prove that an arbitrary supplied commit belongs to the supplied bytes.

The source's personal-use terms do not prove exchange licensing. This importer preserves `license_status=pending`; the user has authorized local retention for this pilot only.

## Remaining blockers and limits

1. **SBI eligibility evidence:** Existing approved classification rules leave NSE SBI unresolved as ordinary equity. BSE mainboard/ordinary classification is also not verified. The real sample therefore must not be admitted as an eligible investment-universe observation until official evidence is added and reviewed.
2. **Immutable dataset revision:** NSE 2026 and NSE 2010 per-file commits and hashes are verified. The retained BSE 2026 sample's commit is unresolved and must not be imported as provenance-complete data.
3. **Full point-in-time calendar:** `eod_observations_as_of` requires the appropriate exchange calendar version already populated for the requested screen date. The pilot does not ingest a calendar provider.
4. **Scope:** Only raw NSE/BSE price files are supported. Historical dates without ISIN remain quarantined. There is no full-universe or full-history run, delivery import, adjusted price or corporate-action import.
5. **Source rights:** Technical accessibility and local personal use do not establish an NSE/BSE licence or exchange permission. No legal permission is claimed by this implementation.

## Test record

See `docs/PROJECT_STATE.md` for the final full-suite count and current Git state. The full suite must be run with `.\.venv\Scripts\python.exe scripts\run_tests.py`; the system Python in this workspace does not have DuckDB installed.

## Independent audit and evidence resolution — 2026-11-10

The importer and repository were reviewed against actual code, including `TejHQParquetImporter._ingest_pilot`, `_register_source`, `recover_archived_sources`, `DuckDBRepository.eod_observations_as_of`, `derive_universe_disposition`, and `append_eod_observation_reconciliation`.

### Audit corrections

- **Retry accounting defect fixed.** Previously, any successful prior processing revision caused every selected row to be reported as a duplicate. This made a second attempt against an empty identity database report quarantined rows as duplicates. Retries now re-evaluate disposition; only a previously persisted normalized observation with matching source/parser/locator provenance increments `duplicates`. Quarantine rows are idempotent, and rejected/quarantined/out-of-scope counts retain their categories. Tests cover quarantine retry, out-of-scope retry, and accepted-row retry.
- **Late official reconciliation fixed.** Re-importing an identical secondary row now checks whether the official counterpart or comparator result changed. A newly arrived official row appends a reconciliation revision superseding the prior unmatched result. Repeating the same pair does not append another result. Price observations remain unchanged.
- **Archive integrity strengthened.** Recovery validates the archived/input SHA-256 against the atomic manifest before retry. A tampered content-addressed archive is rejected. Fault-injection tests cover failure inside source registration (transaction rollback), after source registration but before extraction, after raw archival, before normalized transaction commit, after commit before manifest success, and database rollback/retry.
- **Source revision lineage corrected across immutable dataset commits.** Upstream file path plus commit remains the source identifier. Revision lookup is now by logical dataset path from preserved source-file metadata, so changed bytes at a newer immutable dataset commit link to the previous file revision instead of starting an unrelated chain. Parser-only revisions keep source-document identity and append extraction/observation history.
- **EOD snapshot cutoff enforced.** `eod_observations_as_of` now rejects cutoffs other than 15:30 Asia/Kolkata. Publication timestamps are compared as instants; date-only source dates become eligible on the next session from the selected calendar. HAMSA-known mode additionally requires actual database ingestion and extraction by cutoff. Trade date is not substituted for publication, retrieval, ingestion, or extraction timestamps.

### Verified sample revision and checksum

| Local sample | Published path | Immutable commit | Published SHA-256 versus retained bytes | Result |
|---|---|---|---|---|
| NSE 2026 | `nse/year=2026/nse_2026.parquet` | `408bab9d85371d333cc18572a428934f4fad0112` | `3a51ca886a9b54febf8ecd07042a6728e4adadbc3f55335091a0258ad6335934` = local | Verified; contains 2026-11-09 SBI row used in NSE parity test. |
| NSE 2010 | `nse/year=2010/nse_2010.parquet` | `62a4096f74bc79f34be2a9d848e7831b51d9808b` | `3508faa6dc007783c61324bdfdab40aa7a224cd895662544d1aa139d0e2e7017` = local | Verified; historical NULL-ISIN test input. |
| BSE 2026 retained sample | `bse/year=2026/bse_2026.parquet` | Unknown for retained bytes; current published file commit is `12ba6b3495817adcd442828519189bdbc610890c` | Retained: `0427749cc74a40fcdc93a2a0fab1acc9f9a588a5b15ef436408785da5a5739f6`; current published: `875aa3e3c99d1eea1c109db331e263eaf9bf3901b33749dfe8147773b3a84e66` | Not verified; hashes differ. Current published file is dated through 2026-11-06, while retained bytes include 2026-11-09. Its prior local price-parity comparison does not verify TejHQ commit membership. |

Source file pages inspected: [NSE 2026 at its immutable commit](https://huggingface.co/datasets/tejhq/indian-markets/blob/408bab9d85371d333cc18572a428934f4fad0112/nse/year=2026/nse_2026.parquet), [NSE 2010 at its immutable commit](https://huggingface.co/datasets/tejhq/indian-markets/blob/62a4096f74bc79f34be2a9d848e7831b51d9808b/nse/year=2010/nse_2010.parquet), and [current BSE 2026 file](https://huggingface.co/datasets/tejhq/indian-markets/blob/12ba6b3495817adcd442828519189bdbc610890c/bse/year=2026/bse_2026.parquet). No bulk dataset was downloaded during this audit.

### SBI official evidence by exchange

**NSE:** The official NSE SBIN quote page reports ISIN `INE062A01020`, symbol `SBIN`, Status `Listed`, Trading Status `Active`, Board Status `Main`, Class of Shares `Equity`, and Date of Listing `01-Mar-1995`. This is current evidence for identity, mainboard classification, listing/trading status, and the exchange-reported listing date. The official SBI Act and FY2025-26 annual report also describe fully paid/equity shares and the same equity ISIN. HAMSA's ordinary-equity classification is not approved: the current security-master codebook distinguishing ordinary from other equity-class instruments has not been obtained and reviewed. No mapping or review was inserted.

**BSE:** The retained BSE 2026-11-09 official full-market EOD sample reports scrip code `500112`, symbol `SBIN`, ISIN `INE062A01020`, and a traded row. SBI's FY2025-26 annual report identifies its equity ISIN and exchange codes and says its securities were not suspended during that fiscal year. This supports identity/listing activity but does not establish the current BSE master classification. The current BSE master was not obtained. Official BSE mainboard classification, current listed/trading status, authoritative ordinary-equity classification, and BSE effective listing date remain unverified. Series `A`, group labels, company name, and price presence are not substituted for classification evidence. No mapping or review was inserted.

### Calendar evidence and local calendar state

The official NSE 2026 equities calendar shows the 2026-11-10 holiday, the 2026-11-08 special Muhurat session, and regular-market close at 15:30. November 9 is not listed as an NSE holiday; retained official NSE and BSE EOD files also contain that date. None of the local DuckDB files contains an `exchange_trading_session` row for 2026-11-08 through 2026-11-11. `test-cal` exists only in synthetic tests. HAMSA has no populated production calendar version to report or use for an admitted real-data screen. The importer remains blocked until the applicable official calendar version is loaded through an approved calendar ingestion path.

### Admission status

The importer is **technically verified for its bounded synthetic and local-file paths**, subject to the audit fixes above. Real-data admission remains blocked: NSE ordinary-equity classification still needs an approved authoritative mapping; BSE current master/platform/instrument evidence and effective listing date are missing; the retained BSE TejHQ file revision is unresolved; and no production exchange-calendar version is populated. No successful real observation admission is claimed.
