"""Issuer, security, listing, and corporate-action lifecycle records."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum


class RelationshipType(StrEnum):
    SAME_LEGAL_ISSUER_IDENTIFIER_CHANGE = "same_legal_issuer_identifier_change"
    PREDECESSOR_OF = "predecessor_of"
    SUCCESSOR_OF = "successor_of"
    MERGED_INTO = "merged_into"
    DEMERGED_INTO = "demerged_into"
    SPUN_OUT_TO = "spun_out_to"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CorporateActionType(StrEnum):
    SPLIT = "split"
    BONUS = "bonus"
    RIGHTS = "rights"
    MERGER = "merger"
    DEMERGER = "demerger"
    SYMBOL_CHANGE = "symbol_change"
    ISIN_CHANGE = "isin_change"
    SUSPENSION = "suspension"
    DELISTING = "delisting"
    RELISTING = "relisting"


@dataclass(frozen=True, slots=True)
class EntityRelationship:
    relationship_id: str
    from_entity_id: str
    to_entity_id: str
    relationship_type: RelationshipType
    effective_date: date
    announced_at: datetime
    source_document_id: str
    review_status: ReviewStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CorporateActionEventRevision:
    event_id: str
    revision_number: int
    security_id: str
    action_type: CorporateActionType
    source_document_id: str
    published_at: datetime | None
    publication_date: date
    source_document_date: date
    ex_date: date | None = None
    record_date: date | None = None
    effective_date: date | None = None
    terms_complete: bool = False
    terms_json: str = "{}"
    supersedes_event_revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class AdjustmentFactorRevision:
    factor_id: str
    security_id: str
    event_revision_id: str
    effective_date: date
    price_factor: Decimal
    volume_factor: Decimal
    factor_version: str
    formula_version: str
    methodology_review_status: ReviewStatus
    terms_complete: bool
    publication_date: date
    publication_precision: str
    publicly_available_at: datetime | None
    public_availability_session: date
    availability_calendar_version: str
    source_document_id: str
    input_observation_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.terms_complete or self.methodology_review_status is not ReviewStatus.APPROVED:
            raise ValueError("adjustment factors require complete terms and approved methodology")
        if self.price_factor <= 0 or self.volume_factor <= 0:
            raise ValueError("adjustment factors must be positive")
        if self.publication_precision == "timestamp":
            if self.publicly_available_at is None:
                raise ValueError("timestamp precision requires a reliable publication timestamp")
            if self.publicly_available_at.tzinfo is None or self.publicly_available_at.utcoffset() is None:
                raise ValueError("publication timestamp must be timezone-aware")
        elif self.publication_precision == "date_only":
            if self.publicly_available_at is not None:
                raise ValueError("date-only publication must not claim a reliable timestamp")
        else:
            raise ValueError("unsupported publication precision")
        if self.publicly_available_at is not None:
            from hamsa.domain.trading_calendar import MARKET_TIMEZONE

            if self.publicly_available_at.astimezone(MARKET_TIMEZONE).date() != self.publication_date:
                raise ValueError("published_at must match publication_date in Asia/Kolkata")
        if not self.availability_calendar_version or not self.source_document_id:
            raise ValueError("corporate-action factors require calendar and source-document references")
