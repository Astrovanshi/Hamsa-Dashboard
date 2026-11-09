"""Explicit exchange venue selection and comparable activity aggregation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from hamsa.domain.market_data import EodPriceObservation
from hamsa.domain.financials import QualityStatus


@dataclass(frozen=True, slots=True)
class VenuePolicy:
    primary_exchange: str
    fallback_exchanges: tuple[str, ...]
    allow_combined_activity: bool = False


@dataclass(frozen=True, slots=True)
class SelectedVenuePrice:
    observation: EodPriceObservation
    selected_exchange: str
    used_fallback: bool


@dataclass(frozen=True, slots=True)
class CombinedActivity:
    security_id: str
    trade_date: date
    exchanges: tuple[str, ...]
    total_volume: int
    total_turnover: Decimal


def select_price(
    observations: Iterable[EodPriceObservation],
    *,
    policy: VenuePolicy,
) -> SelectedVenuePrice | None:
    """Pick configured primary, then configured fallback; never average prices."""
    grouped: dict[str, list[EodPriceObservation]] = {}
    for row in observations:
        grouped.setdefault(row.exchange, []).append(row)
    for index, exchange in enumerate((policy.primary_exchange, *policy.fallback_exchanges)):
        candidates = grouped.get(exchange, [])
        # Duplicate or conflicting observations for a venue are ambiguous;
        # the policy may fall back to its next declared venue.
        if len(candidates) == 1:
            row = candidates[0]
            if row.quality_status is QualityStatus.OBSERVED and row.close is not None:
                return SelectedVenuePrice(row, exchange, index > 0)
    return None


def combine_traded_activity(
    observations: Iterable[EodPriceObservation],
    *,
    policy: VenuePolicy,
    comparable: bool,
) -> CombinedActivity | None:
    """Sum venue volume and turnover only under an explicit comparable policy."""
    if not policy.allow_combined_activity or not comparable:
        return None
    rows = tuple(observations)
    if not rows:
        return None
    if any(row.quality_status is not QualityStatus.OBSERVED for row in rows):
        return None
    if len({row.exchange for row in rows}) != len(rows):
        return None
    if len({row.security_id for row in rows}) != 1 or len({row.trade_date for row in rows}) != 1:
        return None
    if any(row.volume is None or row.turnover is None for row in rows):
        return None
    return CombinedActivity(
        security_id=rows[0].security_id,
        trade_date=rows[0].trade_date,
        exchanges=tuple(sorted(row.exchange for row in rows)),
        total_volume=sum(row.volume for row in rows if row.volume is not None),
        total_turnover=sum((row.turnover for row in rows if row.turnover is not None), Decimal("0")),
    )
