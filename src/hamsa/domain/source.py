"""Source-specific document identity and content revisions."""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class SourceDocumentRevision:
    source_document_id: str
    provider: str
    dataset: str
    source_identifier: str
    source_file_id: str
    checksum_sha256: str
    revision_number: int
    source_document_date: date
    publication_date: date
    published_at: datetime | None
    ingestion_timestamp: datetime
    parser_version: str
    extraction_timestamp: datetime
    extraction_locator: str
    supersedes_source_document_id: str | None = None

    def __post_init__(self) -> None:
        if self.revision_number < 1:
            raise ValueError("source document revision_number must be positive")
        if len(self.checksum_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in self.checksum_sha256):
            raise ValueError("checksum_sha256 must be a 64-character hexadecimal SHA-256")
        if not all((self.provider, self.dataset, self.source_identifier, self.source_file_id, self.parser_version, self.extraction_locator)):
            raise ValueError("source identity, file, parser, and extraction locator are required")
        for field_name, timestamp in (
            ("published_at", self.published_at),
            ("ingestion_timestamp", self.ingestion_timestamp),
            ("extraction_timestamp", self.extraction_timestamp),
        ):
            if timestamp is not None and (timestamp.tzinfo is None or timestamp.utcoffset() is None):
                raise ValueError(f"{field_name} must be timezone-aware")
        if self.published_at is not None:
            from hamsa.domain.trading_calendar import MARKET_TIMEZONE

            if self.published_at.astimezone(MARKET_TIMEZONE).date() != self.publication_date:
                raise ValueError("published_at must match publication_date in Asia/Kolkata")


def is_exact_duplicate(
    existing: SourceDocumentRevision,
    incoming: SourceDocumentRevision,
) -> bool:
    """Only same-provider, same-source-ID, same-checksum bytes are duplicates."""
    return (
        existing.provider == incoming.provider
        and existing.dataset == incoming.dataset
        and existing.source_identifier == incoming.source_identifier
        and existing.checksum_sha256 == incoming.checksum_sha256
    )
