"""Immutable venue-specific EOD price and delivery observation records."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from hamsa.domain.financials import QualityStatus


@dataclass(frozen=True, slots=True)
class EodPriceObservation:
    observation_id: str
    security_id: str
    listing_id: str
    exchange: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    source_document_id: str
    source_identifier: str
    checksum_sha256: str
    parser_version: str
    extraction_timestamp: datetime
    extraction_locator: str
    quality_status: QualityStatus = QualityStatus.OBSERVED
    supersedes_observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryObservation:
    observation_id: str
    security_id: str
    listing_id: str
    exchange: str
    trade_date: date
    delivery_quantity: int | None
    traded_quantity: int | None
    delivery_percentage: Decimal | None
    source_document_id: str
    source_identifier: str
    checksum_sha256: str
    parser_version: str
    extraction_timestamp: datetime
    extraction_locator: str
    quality_status: QualityStatus = QualityStatus.OBSERVED
    supersedes_observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class EodBar:
    """Normalized provider row before it is linked to a source document."""

    listing_id: str
    exchange: str
    trade_date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    turnover: Decimal | None
    source_file_id: str


@dataclass(frozen=True, slots=True)
class EodValidationIssue:
    row_index: int
    reason: str


@dataclass(frozen=True, slots=True)
class EodValidationResult:
    accepted: tuple[EodBar, ...]
    issues: tuple[EodValidationIssue, ...]
