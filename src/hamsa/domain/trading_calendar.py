"""Point-in-time publication availability against an exchange calendar."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Protocol


# India has used UTC+05:30 continuously throughout the modern listed-market
# period. A fixed offset avoids requiring the optional OS tzdata database.
MARKET_TIMEZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
EOD_CUTOFF = time(15, 30)


class Calendar(Protocol):
    version: str

    def is_trading_session(self, session: date) -> bool: ...

    def next_trading_session(self, after: date) -> date: ...


class AvailabilityMode(StrEnum):
    PUBLIC_AS_OF = "public_as_of"
    HAMSA_KNOWN_AS_OF = "hamsa_known_as_of"


@dataclass(frozen=True, slots=True)
class PublicAvailability:
    publication_date: date
    reliable_timestamp: datetime | None


def first_eligible_session(availability: PublicAvailability, calendar: Calendar) -> date:
    """Apply 15:30 IST and date-only next-session availability rules."""
    published_date = availability.publication_date
    timestamp = availability.reliable_timestamp
    if timestamp is None:
        return calendar.next_trading_session(published_date)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("reliable publication timestamp must be timezone-aware")
    local = timestamp.astimezone(MARKET_TIMEZONE)
    if local.date() != published_date:
        raise ValueError("publication timestamp date does not match publication_date in Asia/Kolkata")
    if calendar.is_trading_session(local.date()) and local.time().replace(tzinfo=None) <= EOD_CUTOFF:
        return local.date()
    return calendar.next_trading_session(local.date())
