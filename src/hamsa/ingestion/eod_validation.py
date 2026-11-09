"""Validation for normalized exchange EOD rows (no intraday input accepted)."""

from datetime import date
from decimal import Decimal
from typing import Iterable

from hamsa.domain.market_data import EodBar, EodValidationIssue, EodValidationResult


def validate_eod_bars(
    rows: Iterable[EodBar],
    *,
    expected_trade_date: date,
    known_listing_ids: set[str],
    source_file_id: str,
) -> EodValidationResult:
    """Validate a normalized single-date EOD batch, retaining row diagnostics.

    Provider parsers must normalize daily exchange records to ``EodBar``. They
    must not pass time-stamped intraday observations to this function.
    """
    accepted: list[EodBar] = []
    issues: list[EodValidationIssue] = []
    seen: set[str] = set()

    for index, row in enumerate(rows, start=1):
        errors: list[str] = []
        if row.trade_date != expected_trade_date:
            errors.append("trade date does not match requested EOD batch date")
        if row.exchange not in {"NSE", "BSE"}:
            errors.append("exchange must be NSE or BSE")
        if row.listing_id not in known_listing_ids:
            errors.append("unknown exchange listing reference")
        if row.source_file_id != source_file_id:
            errors.append("row source reference does not match batch source file")
        if row.listing_id in seen:
            errors.append("duplicate listing in one EOD source batch")
        else:
            seen.add(row.listing_id)

        prices = (row.open, row.high, row.low, row.close)
        if any(value is not None and value < 0 for value in prices):
            errors.append("price values cannot be negative")
        if row.high is not None and row.low is not None and row.high < row.low:
            errors.append("high is below low")
        if row.volume is not None and row.volume < 0:
            errors.append("volume cannot be negative")
        if row.turnover is not None and row.turnover < 0:
            errors.append("turnover cannot be negative")
        if not any(value is not None for value in prices):
            errors.append("row has no price observations")

        if errors:
            issues.append(EodValidationIssue(index, "; ".join(errors)))
        else:
            accepted.append(row)

    return EodValidationResult(tuple(accepted), tuple(issues))
