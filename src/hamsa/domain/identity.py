"""Effective-dated ISIN mappings without automatic history consolidation."""

from dataclasses import dataclass
from datetime import date

from hamsa.domain.lifecycle import ReviewStatus


@dataclass(frozen=True, slots=True)
class SecurityIdentifierMapping:
    security_id: str
    issuer_entity_id: str
    isin: str
    effective_from: date
    effective_to: date | None
    source_document_id: str
    review_status: ReviewStatus


class AmbiguousIdentityMapping(ValueError):
    """More than one approved security mapping covers the requested date."""


def resolve_isin(
    mappings: tuple[SecurityIdentifierMapping, ...],
    *,
    isin: str,
    on_date: date,
) -> SecurityIdentifierMapping | None:
    normalized = isin.strip().upper()
    matches = tuple(
        row for row in mappings
        if row.isin.strip().upper() == normalized
        and row.review_status is ReviewStatus.APPROVED
        and row.effective_from <= on_date
        and (row.effective_to is None or on_date <= row.effective_to)
    )
    if len(matches) > 1:
        raise AmbiguousIdentityMapping(f"multiple approved mappings for {normalized} on {on_date}")
    return matches[0] if matches else None
