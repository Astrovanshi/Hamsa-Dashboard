# HAMSA product roadmap

HAMSA is a local Investment Research and Portfolio Intelligence System. The
roadmap preserves the original end-of-day opportunity-discovery purpose while
adding portfolio and company research capabilities. No phase generates
automatic buy/sell recommendations.

## Milestones

| Phase | Scope | State / boundary |
| --- | --- | --- |
| Foundation | Versioned DuckDB analytical schema v3, SQLite human-review ledger, provenance, point-in-time rules, security identity/lifecycle, synthetic ingestion and tests | Complete and preserved. |
| Data readiness | Local-file official NSE/BSE EOD and calendar ingestion, source validation, raw archive, identity/classification review, as-reported history | Adapters exist. Production mainboard universe, calendar rows, and normalized company financial coverage remain blocked by missing reviewed source evidence/data. |
| Opportunity Screener | Compounders, Earnings Inflection, Capex Conversion, Cash Quality, and Extreme Sell-Side Liquidity calculations | Implemented as transparent EOD research flags with configurable thresholds and explicit unproven/blocked states. No production screen can run until an eligible universe, calendar, financial inputs, and business-class review exist. Financial-sector profiles and numerical “unusual liquidity” defaults are intentionally unset. |
| Company Intelligence Dossier | Hamsa 11 evidence-backed human assessments; thesis, thesis killers, financial and operating history, dated triggers and review history | Local append-only review, source citation, thesis, issuer business-class review, watchlist and checkpoint workflows implemented. Data content is limited by source coverage. Pass / Unproven / Fail remains human-entered. |
| Portfolio Intelligence | Local CSV import for broker holdings snapshots and tradebooks; multiple brokers/accounts; investing/trading mandates; immutable transaction ledger; position reconstruction and broker-snapshot reconciliation | Future. No broker APIs or credential storage. Missing trade history is never inferred from current holdings. |
| Capital Allocation Monitor | Position-specific deployment, trims, re-entries, exits, sizing/concentration, alternatives, recycling, thesis status and review checkpoints | Future. Company-level dossiers do not merge distinct positions. |
| Performance Analytics | Position/account realized/unrealized P&L, average cost, XIRR/TWR where methodologically suitable, drawdown/recovery, attribution, capital turnover and recycling efficiency | Future. Investing/trading flows remain separate except in an explicit consolidated view. |
| Market and Event Intelligence | Exchange filings/results, ownership changes, block/bulk deals, corporate actions and business milestones | Read-only point-in-time corporate-action and venue-specific EOD monitor implemented. No ownership/block/bulk/business-milestone ingestion adapter is available yet. |
| Streamlit experience | Local Market Radar, discovery workbenches, company dossier, event/liquidity monitor, watchlist and data operations | App implemented; Streamlit is declared in `pyproject.toml`, but was not installed in the current `.venv` and network access prevented installation during this milestone. Launch verification is pending that runtime dependency. |

## Shared architectural rules

- Company/issuer, security, exchange listing, broker, account, mandate, position,
  and transaction are separate entities.
- A company can have several independently managed positions. Each position
  retains its own thesis, entry history, mandate, risk rules, and exit logic.
- Portfolio positions are reconstructed reproducibly from immutable transaction
  history plus versioned corporate-action handling. Holdings snapshots are
  reconciliation evidence, not a substitute for missing trades.
- Raw source files and original price/financial observations remain preserved.
  Corrections append revisions with source, parser, extraction and formula
  lineage; historical screen views remain point-in-time safe.
- EOD only; no intraday or live feeds. Source activation requires data-use and
  licensing review. Local broker CSV import does not store credentials.
- Every screen signal exposes exact calculation, source, and date. Qualitative
  Hamsa 11 assessments are not automated and no buy/sell recommendation is
  produced.

## Remaining MVP gates

The local dashboard runtime must be installed from the already-declared
dependency before its browser pages can be launch-verified. The full current
mainboard universe remains blocked by official classification and mapping
evidence; production calendar sessions and normalized financial observations
are also absent. Do not relax those evidence requirements. Portfolio schemas,
broker imports, and position reconstruction remain future work.
