"""Explicit quality outcomes, configurable staleness, and quarantine rules."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from hamsa.domain.financials import QualityStatus


@dataclass(frozen=True, slots=True)
class QuarantinedObservation:
    source_identifier: str
    reason_code: str
    detail: str


@dataclass(frozen=True, slots=True)
class StalenessWindow:
    metric: str
    source: str
    max_age_days: int


def quality_for_value(value: Decimal | None) -> QualityStatus:
    """Missing stays missing and is never represented as numeric zero."""
    return QualityStatus.MISSING if value is None else QualityStatus.OBSERVED


def apply_staleness(
    status: QualityStatus,
    *,
    observation_date: date,
    as_of_date: date,
    window: StalenessWindow,
) -> QualityStatus:
    if window.max_age_days < 0:
        raise ValueError("max_age_days cannot be negative")
    if status is not QualityStatus.OBSERVED:
        return status
    if observation_date > as_of_date:
        return QualityStatus.INVALID
    if (as_of_date - observation_date).days > window.max_age_days:
        return QualityStatus.STALE
    return QualityStatus.OBSERVED


def convert_unit(
    raw_value: Decimal,
    *,
    raw_unit: str,
    canonical_unit: str,
    multiplier: Decimal,
    additive_offset: Decimal = Decimal("0"),
    rule_documented: bool,
    units_compatible: bool,
) -> Decimal:
    if not rule_documented or not units_compatible or multiplier <= 0:
        raise ValueError("unit conversion is undocumented or incompatible; quarantine observation")
    if not raw_unit or not canonical_unit:
        raise ValueError("raw and canonical units are required")
    return raw_value * multiplier + additive_offset
