# HAMSA Decision Log

This log records approved product and architecture choices. Detailed specifications remain in their owning documents; this log does not replace them.

| Decision | Approved direction | Rationale / source |
|---|---|---|
| Product | Local investment research and portfolio intelligence system; preserve the five-engine opportunity screener; never generate automatic buy/sell recommendations. | `docs/architecture.md`, product direction approval. |
| Investment universe | NSE and BSE mainboard ordinary equity only. Exclude Emerge/SME, funds/ETFs, REITs/InvITs, preference shares, warrants, rights, debt, and other instruments using official classification and status. | `docs/mainboard-classification-rules.md` and approved mainboard scope. |
| Identity | ISIN-based security identity with distinct exchange listing identities. Routine sourced identifier/symbol changes retain entity identity; mergers, demergers and reorganizations remain distinct unless explicitly reviewed. | `docs/architecture.md`, approved lifecycle rules. |
| Temporal truth | EOD cutoff is 15:30 Asia/Kolkata using exchange trading calendars. Preserve independent `public_as_of` and `hamsa_known_as_of`; date-only publications become eligible next session. | `docs/architecture.md`, approved PIT rules. |
| Raw and revision history | Immutable raw bytes and checksums; append-only normalized observations, reviews and corrections with lineage. Preserve source and parser revisions. | Architecture and ingestion approvals. |
| Data-source hierarchy | Official NSE/BSE files and filings remain primary for daily ingestion. TejHQ Parquet is the primary historical EOD backfill source, retained as a distinct secondary-origin observation stream and subject to HAMSA identity, classification, provenance, revision, calendar and PIT controls. No undocumented endpoints or access-control bypass. | User direction in `Pasted text.txt`; prior source review. |
| Stack | Python 3.11, DuckDB 2.0.0, SQLite, Streamlit. No dependency addition without approval. | Verified runtime and project requirements. |
| Schema v3 | Add four relations for listing classification snapshots/reviews, effective listing revision reviews, and EOD reconciliation. No stored eligibility allowlist/disposition; derive eligibility from independent approved evidence. | `docs/tejhq-schema-migration-review.md`, implementation authorized. |
| Repository integrity boundary | DuckDB constraints enforce row-local integrity; repository validates cross-table and append-only rules. Direct database-owner access can bypass repository enforcement. No unsupported DuckDB trigger dependency. | Approved storage design. |
| TejHQ pilot | Local raw NSE/BSE Parquet prices only, bounded pilot; exclude adjusted prices, corporate actions, delivery, and full historical backfill. Preserve raw provenance and quarantine unresolved identity/classification. | `docs/tejhq-historical-import-implementation.md`, migration approval. |
| Git | No staging, commit, or push without explicit approval. Keep raw datasets, local databases, secrets, and generated files ignored. | User's standing operating instruction. |

## Decision changes

- Historical EOD source priority changed from optional secondary backfill to TejHQ-first historical backfill. Official exchange-file ingestion remains the daily primary route. The retained TejHQ observations never become official observations; HAMSA identity/classification and point-in-time gates remain unchanged. BSE SCRIP acquisition is paused. The bounded local pilot is not authorization for a full historical backfill.

Do not silently amend an approved row. If a requirement demands a change, record the proposed conflict and obtain approval before implementation. Routine implementation details that preserve these decisions do not require a new decision entry.
