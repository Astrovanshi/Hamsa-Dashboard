# HAMSA Engineering Operating Policy

## Persistent working context

Before starting a milestone, read this file, `docs/PROJECT_STATE.md`, the relevant entries in `docs/DECISION_LOG.md` and `docs/MILESTONE_TRACKER.md`, plus the governing specification and previous implementation report. Inspect the actual source, SQL, tests, and Git status; prior reports are evidence to verify, not a substitute for inspection.

## Autonomous milestone workflow

For work already authorized by the user:

1. Define a bounded implementation plan from the approved requirements and acceptance criteria.
2. Identify dependencies, data assumptions, failure modes, and compatibility risks.
3. Implement within scope, preserving existing work and interfaces where practical.
4. Review the changes independently against the requirements and approved decisions.
5. Add focused tests, run them, diagnose failures, and run the complete project test suite.
6. Review the final diff, `git diff --check`, tracked/untracked status, and ignored artifacts.
7. Update project state and milestone records with verified outcomes.
8. Continue to the next already-authorized milestone without waiting for the user to restate it.

A report is not completion: acceptance requires working implementation and verified criteria. Never hide a failure, fabricate source evidence or coverage, suppress a failing test, or weaken a constraint to make a milestone pass.

Use the pinned interpreter for database tests: `.venv/Scripts/python.exe scripts/run_tests.py` on Windows. A system interpreter without DuckDB is not a valid test environment; do not install packages as a workaround.

## Approval boundaries

Stop for user approval only when work requires a fundamental architecture/product change, alteration of an approved investment or screening rule, a new dependency or paid service, a destructive or irreversible external action, credentials/account permissions/financial transactions, or a change to an approved decision. Routine code choices, reversible refactors, bug fixes, tests, and documentation updates inside scope are autonomous.

Never stage, commit, or push unless explicitly authorized for that operation. Preserve unrelated staged, modified, untracked, and ignored user data. Do not send messages or contact providers unless explicitly authorized. Do not download external data or activate a provider unless authorized by the active milestone.

## HAMSA invariants

- The investment universe is NSE/BSE mainboard ordinary equity only. Official exchange classification and effective listing status determine eligibility. SME/Emerge and non-equity instruments remain excluded; unresolved classification fails closed.
- ISIN-based security identity is distinct from exchange-specific listing identity. Never resolve identity from symbol or name alone, and never merge predecessor/successor histories automatically.
- EOD only. No live or intraday feeds. Historical screens must preserve `public_as_of` and `hamsa_known_as_of` semantics and prevent lookahead.
- Preserve immutable raw bytes, checksums, source identifiers, parser/extraction provenance, source revisions, observation revisions, and superseded history. Missing is not zero.
- Instrument class, platform class, and effective listing status are independent evidence dimensions. A current snapshot date is not an effective listing date.
- Official NSE/BSE ingestion remains independent of secondary historical datasets. Secondary observations never overwrite official observations.
- Do not automate qualitative Hamsa 11 judgments or produce buy/sell recommendations.
- Python 3.11 and DuckDB 2.0.0 are the supported verified runtime. Add no dependency without approval.
- DuckDB repository methods are the ordinary application integrity boundary; direct database-owner access can bypass repository checks.

## Project hygiene

Keep source, schema, docs, configuration examples, and synthetic tests reviewable. Do not track raw data, local databases, credentials, keys, certificates, logs, caches, or virtual environments. Keep provider code replaceable and separate from screening logic. State uncertainty and provenance explicitly.

## Reuse before building

For non-trivial functionality, follow: discover, evaluate, reuse, adapt, then build only what is missing. Check existing repository code, established libraries, exchange-provided tooling, and mature open-source implementations before creating commodity infrastructure. Assess maintenance, local-first fit, data-integrity and point-in-time compatibility, and dependency cost. Prefer a small, proven component plus HAMSA-specific integration over reimplementing solved functionality; do not add a dependency without approval or import an unsuitable framework wholesale.
