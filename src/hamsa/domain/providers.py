"""Provider-neutral interfaces and source provenance types."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EodSourceFile:
    provider: str
    dataset: str
    original_filename: str
    source_as_of_date: date
    captured_at: datetime
    license_review_reference: str
    license_status: str
    local_path: Path


class EodProvider(Protocol):
    """Replaceable adapter; implementations must return end-of-day files only."""

    provider_name: str

    def list_eod_files(self, as_of_date: date) -> tuple[EodSourceFile, ...]:
        """Return approved EOD artifacts for one trading date."""
