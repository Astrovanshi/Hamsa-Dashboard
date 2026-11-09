"""Corporate-action factor selection without mutating original prices."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Iterable

from hamsa.domain.lifecycle import AdjustmentFactorRevision, ReviewStatus
from hamsa.domain.trading_calendar import MARKET_TIMEZONE


def factors_for_historical_screen(
    factors: Iterable[AdjustmentFactorRevision],
    *,
    security_id: str,
    as_of_session: date,
    cutoff: datetime,
    calendar_version: str,
) -> tuple[AdjustmentFactorRevision, ...]:
    """Select approved factors whose public-availability session has arrived."""
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("screen cutoff must be timezone-aware")
    local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
    if local_cutoff.date() != as_of_session or local_cutoff.time().replace(tzinfo=None) != time(15, 30):
        raise ValueError("corporate-action screen cutoff must be 15:30 Asia/Kolkata on as_of_session")
    selected = (
        factor for factor in factors
        if factor.security_id == security_id
        and factor.effective_date <= as_of_session
        and factor.availability_calendar_version == calendar_version
        and factor.public_availability_session <= as_of_session
    )
    return tuple(sorted(selected, key=lambda factor: (factor.effective_date, factor.factor_version, factor.factor_id)))


def factors_for_retrospective_return(
    factors: Iterable[AdjustmentFactorRevision],
    *,
    security_id: str,
    through_date: date,
) -> tuple[AdjustmentFactorRevision, ...]:
    """Allow later-confirmed approved events for retrospective return analysis."""
    selected = (
        factor for factor in factors
        if factor.security_id == security_id
        and factor.effective_date <= through_date
        and factor.terms_complete
        and factor.methodology_review_status is ReviewStatus.APPROVED
    )
    return tuple(sorted(selected, key=lambda factor: (factor.effective_date, factor.factor_version, factor.factor_id)))


def adjusted_price(
    raw_price: Decimal,
    *,
    price_date: date,
    factors: Iterable[AdjustmentFactorRevision],
) -> Decimal:
    """Return a derived price value; never writes or changes the raw price."""
    factor_product = Decimal("1")
    for factor in factors:
        if (
            factor.terms_complete
            and factor.methodology_review_status is ReviewStatus.APPROVED
            and price_date < factor.effective_date
        ):
            factor_product *= factor.price_factor
    return raw_price * factor_product
