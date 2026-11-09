"""Provider-neutral contracts for calendars, unit rules, and freshness.

Implementations must be supplied from reviewed source data/configuration. This
module intentionally defines no source coverage, conversion, or age defaults.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TradingSession:
    exchange: str
    session_date: date
    is_trading_session: bool
    session_type: str
    calendar_version: str
    source_document_id: str


class TradingCalendarProvider(Protocol):
    """Loads versioned, official calendar records without assuming coverage."""

    provider_name: str

    def load_sessions(self, exchange: str, start: date, end: date) -> tuple[TradingSession, ...]:
        """Return sourced sessions for an explicit exchange/date interval."""


@dataclass(frozen=True, slots=True)
class UnitConversionRule:
    source_unit: str
    canonical_unit: str
    dimension: str
    multiplier: Decimal
    additive_offset: Decimal
    rule_version: str
    review_status: str
    source_document_id: str | None

    def convert(self, raw_value: Decimal) -> Decimal:
        if self.review_status != "approved":
            raise ValueError("unit conversion rule is not approved")
        return raw_value * self.multiplier + self.additive_offset


class UnitConversionPolicy(Protocol):
    def resolve(self, source_unit: str, canonical_unit: str, *, dimension: str) -> UnitConversionRule | None:
        """Return a reviewed rule or None; callers quarantine unresolved units."""


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    metric: str
    source: str
    max_age_days: int
    policy_version: str
    effective_from: date
    source_document_id: str | None


class FreshnessPolicyProvider(Protocol):
    def resolve(self, metric: str, source: str, *, as_of: date) -> FreshnessPolicy | None:
        """Return the applicable reviewed rule or None; never invent a default."""
