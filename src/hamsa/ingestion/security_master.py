"""Deterministic ISIN-first mapping for NSE/BSE security-master rows."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Iterable

from hamsa.domain.security import InstrumentListing, ListingCandidate, MappingIssue, is_valid_isin


@dataclass(frozen=True, slots=True)
class SecurityMasterResult:
    listings: tuple[InstrumentListing, ...]
    issues: tuple[MappingIssue, ...]

    @property
    def companies(self) -> tuple[str, ...]:
        """Unique company identities, deduplicated strictly by validated ISIN."""
        return tuple(sorted({listing.company_isin for listing in self.listings}))


def _listing_id(row: ListingCandidate) -> str:
    key = "|".join((
        row.exchange.value,
        row.exchange_instrument_id.strip(),
        row.effective_from.isoformat(),
        (row.isin or "").strip().upper(),
    ))
    return sha256(key.encode("utf-8")).hexdigest()


def build_security_master(rows: Iterable[ListingCandidate]) -> SecurityMasterResult:
    """Map listings by ISIN and quarantine ambiguous/invalid source rows.

    NSE and BSE instrument references are retained as distinct listings. Names
    and symbols are never used to merge companies. Duplicate source keys with
    conflicting data are all quarantined instead of selecting a winner.
    """
    candidates = tuple(rows)
    issues: list[MappingIssue] = []
    eligible: list[ListingCandidate] = []

    for row in candidates:
        if not row.exchange_instrument_id.strip() or not row.symbol.strip() or not row.source_file_id.strip():
            issues.append(MappingIssue(row, "missing exchange instrument ID, symbol, or source file reference"))
        elif row.isin is None or not row.isin.strip():
            issues.append(MappingIssue(row, "missing ISIN; cannot deduplicate safely"))
        elif not is_valid_isin(row.isin):
            issues.append(MappingIssue(row, "invalid ISIN shape or check digit"))
        elif row.effective_to is not None and row.effective_to < row.effective_from:
            issues.append(MappingIssue(row, "effective_to precedes effective_from"))
        else:
            eligible.append(row)

    # A repeated exchange instrument key on the same effective date is only
    # safe to collapse if all identifying values agree exactly. Identical rows
    # retain every contributing source-file reference.
    groups: dict[tuple[str, str, str], list[ListingCandidate]] = {}
    for row in eligible:
        key = (row.exchange.value, row.exchange_instrument_id.strip(), row.effective_from.isoformat())
        groups.setdefault(key, []).append(row)

    accepted: list[ListingCandidate] = []
    for group in groups.values():
        fingerprints = {
            (row.isin.strip().upper(), row.symbol.strip(), row.series, row.effective_to)
            for row in group
        }
        if len(fingerprints) > 1:
            issues.extend(MappingIssue(row, "conflicting rows for exchange instrument and effective date") for row in group)
        else:
            accepted.append(group[0])

    listings = tuple(sorted((
        InstrumentListing(
            listing_id=_listing_id(row),
            company_isin=row.isin.strip().upper(),
            exchange=row.exchange,
            exchange_instrument_id=row.exchange_instrument_id.strip(),
            symbol=row.symbol.strip(),
            series=row.series,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            source_file_ids=tuple(sorted({
                candidate.source_file_id.strip()
                for candidate in groups[(row.exchange.value, row.exchange_instrument_id.strip(), row.effective_from.isoformat())]
            })),
            source_document_ids=tuple(sorted({
                candidate.source_document_id.strip()
                for candidate in groups[(row.exchange.value, row.exchange_instrument_id.strip(), row.effective_from.isoformat())]
            })),
        )
        for row in accepted
    ), key=lambda listing: (listing.company_isin, listing.exchange.value, listing.exchange_instrument_id)))
    return SecurityMasterResult(listings=listings, issues=tuple(issues))
