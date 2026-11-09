"""Provider-neutral exchange listing records and ISIN validation."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


@dataclass(frozen=True, slots=True)
class ListingCandidate:
    exchange: Exchange
    exchange_instrument_id: str
    symbol: str
    isin: str | None
    effective_from: date
    effective_to: date | None
    source_file_id: str
    source_document_id: str
    checksum_sha256: str
    parser_version: str
    extraction_timestamp: datetime
    extraction_locator: str
    series: str | None = None
    company_name: str | None = None

    def __post_init__(self) -> None:
        if len(self.checksum_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in self.checksum_sha256):
            raise ValueError("security-master checksum must be a 64-character hexadecimal SHA-256")
        if not all((self.source_file_id, self.source_document_id, self.parser_version, self.extraction_locator)):
            raise ValueError("security-master rows require source, parser, and extraction provenance")
        if self.extraction_timestamp.tzinfo is None or self.extraction_timestamp.utcoffset() is None:
            raise ValueError("security-master extraction timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class InstrumentListing:
    listing_id: str
    company_isin: str
    exchange: Exchange
    exchange_instrument_id: str
    symbol: str
    series: str | None
    effective_from: date
    effective_to: date | None
    source_file_ids: tuple[str, ...]
    source_document_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MappingIssue:
    candidate: ListingCandidate
    reason: str


def is_valid_isin(value: str) -> bool:
    """Validate ISIN shape and its ISO 6166/Luhn check digit."""
    isin = value.strip().upper()
    if (
        len(isin) != 12
        or not all("A" <= char <= "Z" for char in isin[:2])
        or not all("A" <= char <= "Z" or "0" <= char <= "9" for char in isin[2:11])
        or not "0" <= isin[11] <= "9"
    ):
        return False

    expanded = "".join(str(ord(char) - 55) if char.isalpha() else char for char in isin)
    digits = [int(char) for char in expanded]
    checksum = sum(
        sum(divmod(digit * (2 if (len(digits) - index) % 2 == 0 else 1), 10))
        for index, digit in enumerate(digits)
    )
    return checksum % 10 == 0
