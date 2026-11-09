"""Point-in-time financial observations and filing revisions."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class PublicationPrecision(StrEnum):
    TIMESTAMP = "timestamp"
    DATE_ONLY = "date_only"


class AsReportedStatus(StrEnum):
    ORIGINAL = "original"
    RESTATEMENT = "restatement"
    RECAST = "recast"
    PROVIDER_BACKFILL = "provider_backfill"


class QualityStatus(StrEnum):
    OBSERVED = "observed"
    MISSING = "missing"
    STALE = "stale"
    INVALID = "invalid"
    CONFLICTED = "conflicted"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class FinancialObservationRevision:
    observation_id: str
    subject_id: str
    metric: str
    raw_value: Decimal | None
    raw_unit: str | None
    canonical_value: Decimal | None
    canonical_unit: str
    period_end: date
    source_document_date: date
    publication_date: date
    publication_precision: PublicationPrecision
    published_at: datetime | None
    ingestion_timestamp: datetime
    revision_number: int
    source_document_id: str
    as_reported_status: AsReportedStatus
    quality_status: QualityStatus
    source_locator: str
    parser_version: str
    extraction_timestamp: datetime
    supersedes_observation_id: str | None = None
    period_start: date | None = None
    reporting_scope: str = "consolidated"
    quality_reason: str | None = None
    formula_version: str | None = None

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("revision_number must be positive")
        if self.publication_precision is PublicationPrecision.TIMESTAMP:
            if self.published_at is None or self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
                raise ValueError("timestamp publication precision requires an aware published_at")
            # Publication dates are exchange-local calendar dates.
            from hamsa.domain.trading_calendar import MARKET_TIMEZONE

            if self.published_at.astimezone(MARKET_TIMEZONE).date() != self.publication_date:
                raise ValueError("published_at must match publication_date in Asia/Kolkata")
        elif self.publication_precision is PublicationPrecision.DATE_ONLY and self.published_at is not None:
            raise ValueError("date-only publication precision cannot claim a reliable timestamp")
        if self.ingestion_timestamp.tzinfo is None or self.ingestion_timestamp.utcoffset() is None:
            raise ValueError("ingestion_timestamp must be timezone-aware")
        if self.extraction_timestamp.tzinfo is None or self.extraction_timestamp.utcoffset() is None:
            raise ValueError("extraction_timestamp must be timezone-aware")
        if not self.source_document_id or not self.parser_version or not self.source_locator:
            raise ValueError("source document, parser version, and extraction locator are required")
        if self.quality_status is QualityStatus.MISSING and self.canonical_value is not None:
            raise ValueError("missing observations cannot carry a canonical value")
        if self.quality_status is QualityStatus.OBSERVED and self.canonical_value is None:
            raise ValueError("observed observations require a canonical value")
