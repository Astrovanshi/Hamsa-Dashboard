# HAMSA product roadmap

HAMSA is a local Investment Research and Portfolio Intelligence System. The
roadmap preserves the original end-of-day opportunity-discovery purpose while
adding portfolio and company research capabilities. No phase generates
automatic buy/sell recommendations.

## Milestones

| Phase | Scope | State / boundary |
| --- | --- | --- |
| Foundation | Versioned DuckDB analytical schema, SQLite human-review ledger, provenance, point-in-time rules, security identity/lifecycle, synthetic ingestion and tests | Foundation and synthetic ingestion are under review; no external sources are active. |
| Data readiness | Licensed NSE/BSE official security masters, EOD files, filings and trading calendar; validation, raw archive and as-reported history | Future. Requires provider/licensing and data-source review before activation. |
| Opportunity Screener | Configurable, separately profiled company/financial screens for Compounders, Earnings Inflection, Capex Conversion, Cash Quality, and Extreme Sell-Side Liquidity | Future. EOD only; each signal shows formula, source and date. Capex-heavy companies are not rejected solely for weak current ROCE/FCF; falling prices alone do not qualify liquidity signals. |
| Company Intelligence Dossier | Hamsa 11 evidence-backed human assessments; thesis, thesis killers, financial and operating history, dated triggers and review history | Future. Pass / Unproven / Fail remains human-entered for every filter. |
| Portfolio Intelligence | Local CSV import for broker holdings snapshots and tradebooks; multiple brokers/accounts; investing/trading mandates; immutable transaction ledger; position reconstruction and broker-snapshot reconciliation | Future. No broker APIs or credential storage. Missing trade history is never inferred from current holdings. |
| Capital Allocation Monitor | Position-specific deployment, trims, re-entries, exits, sizing/concentration, alternatives, recycling, thesis status and review checkpoints | Future. Company-level dossiers do not merge distinct positions. |
| Performance Analytics | Position/account realized/unrealized P&L, average cost, XIRR/TWR where methodologically suitable, drawdown/recovery, attribution, capital turnover and recycling efficiency | Future. Investing/trading flows remain separate except in an explicit consolidated view. |
| Market and Event Intelligence | Exchange filings/results, ownership changes, block/bulk deals, corporate actions and business milestones | Future. Event-publication time, event dates, provenance, revisions and review status remain distinct. |
| Streamlit experience | Local research workspace for screens, dossiers, portfolio/reconciliation, allocation and analytics | Future, after data and domain contracts are reviewed. |

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

## Next review boundary

This roadmap update is documentation only. It does not implement portfolio
tables/services, activate providers, add dependencies, ingest external data,
build discovery engines, or build the dashboard. Portfolio schema and
reconstruction rules require their own design and approval before coding.
