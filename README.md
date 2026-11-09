# HAMSA Radar

HAMSA is a local, EOD-only Indian equity research workspace for NSE and BSE equities. Issuer identity, share-security identity, and exchange listing identity are modeled separately. NSE/BSE listings with the same ISIN share a security identity while retaining venue-specific history.

## Guardrails

- 15:30 Asia/Kolkata EOD cutoff and versioned exchange calendars, including holidays and special sessions.
- Raw source files, EOD prices, filing revisions, and dossier reviews are append-only.
- Public-as-of and HAMSA-known-as-of historical modes are independent.
- Corporate-action adjusted prices are derived, versioned views; raw observations remain unchanged.
- Every normalized observation retains source document, checksum, parser, extraction location, and revision lineage.
- Missing, stale, invalid, conflicted, and not-applicable remain distinct; null never becomes zero.
- Financial and industrial classifications remain separate. Capex-heavy firms cannot be excluded solely for current ROCE or FCF.
- NSE/BSE prices are never averaged. Venue selection and any combined traded-activity calculation must be explicit.
- Human-authored Hamsa 11 statuses are not automated. HAMSA never makes buy/sell recommendations.

## Milestone status

This second-pass milestone updates the data model, point-in-time helpers, quality/provenance contracts, corporate-action and venue policies, synthetic tests, and Git ignore rules. It does not install packages, acquire external data, activate providers, implement the five screening engines, or build the dashboard.

See [docs/architecture.md](docs/architecture.md) and [docs/data-model.md](docs/data-model.md).
