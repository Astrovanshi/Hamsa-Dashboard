"""Historical snapshots with separate public-truth and HAMSA-known modes."""

from dataclasses import replace
from datetime import date, datetime
from typing import Iterable

from hamsa.domain.financials import FinancialObservationRevision, QualityStatus
from hamsa.domain.trading_calendar import (
    AvailabilityMode,
    Calendar,
    PublicAvailability,
    first_eligible_session,
)


def eod_cutoff_for_session(session: date) -> datetime:
    """Return 15:30 Asia/Kolkata for an exchange trading session."""
    from datetime import time
    from hamsa.domain.trading_calendar import MARKET_TIMEZONE

    return datetime.combine(session, time(15, 30), tzinfo=MARKET_TIMEZONE)


def as_reported_snapshot(
    revisions: Iterable[FinancialObservationRevision],
    *,
    as_of_session: date,
    mode: AvailabilityMode,
    calendar: Calendar,
    parser_version: str | None = None,
) -> tuple[FinancialObservationRevision, ...]:
    """Return eligible latest revision-chain leaves without hiding conflicts.

    Public mode answers what was public by the EOD cutoff, including legitimate
    retrospective backfills. HAMSA-known mode additionally requires ingestion
    by that cutoff. Competing unsuperseded documents are retained; this method
    never chooses a winner between them.
    """
    if not calendar.is_trading_session(as_of_session):
        raise ValueError(f"{as_of_session} is not a trading session in calendar {calendar.version}")
    cutoff = eod_cutoff_for_session(as_of_session)
    eligible: list[FinancialObservationRevision] = []
    for row in revisions:
        if parser_version is not None and row.parser_version != parser_version:
            continue
        public_session = first_eligible_session(
            PublicAvailability(row.publication_date, row.published_at), calendar
        )
        if public_session > as_of_session:
            continue
        if mode is AvailabilityMode.HAMSA_KNOWN_AS_OF:
            ingested = row.ingestion_timestamp
            if ingested.tzinfo is None or ingested.utcoffset() is None:
                raise ValueError("ingestion_timestamp must be timezone-aware")
            if ingested > cutoff:
                continue
        eligible.append(row)

    grouped: dict[tuple[object, ...], list[FinancialObservationRevision]] = {}
    for row in eligible:
        key = (row.subject_id, row.metric, row.period_start, row.period_end, row.reporting_scope)
        grouped.setdefault(key, []).append(row)

    output: list[FinancialObservationRevision] = []
    for rows in grouped.values():
        superseded = {row.supersedes_observation_id for row in rows if row.supersedes_observation_id}
        leaves = [row for row in rows if row.observation_id not in superseded]
        observed_values = {
            (row.canonical_value, row.canonical_unit)
            for row in leaves
            if row.quality_status is QualityStatus.OBSERVED
        }
        if len(observed_values) > 1:
            output.extend(
                replace(
                    row,
                    quality_status=QualityStatus.CONFLICTED,
                    quality_reason="unresolved unsuperseded source observations disagree",
                ) if row.quality_status is QualityStatus.OBSERVED else row
                for row in leaves
            )
        else:
            output.extend(leaves)
    return tuple(sorted(output, key=lambda row: (
        row.subject_id, row.metric, row.period_end, row.reporting_scope,
        row.revision_number, row.source_document_id, row.observation_id,
    )))
