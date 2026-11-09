"""Hamsa 11 catalog and human-review types.

This module records a review decision supplied by a person. It does not infer
qualitative filter outcomes from data or text.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FilterKey(StrEnum):
    GAP = "gap"
    CHOKE_POINT = "choke_point"
    TURBO = "turbo"
    REAL_BUYERS = "real_buyers"
    STACK = "stack"
    TRIGGER = "trigger"
    JOCKEY = "jockey"
    THIN_FLOAT = "thin_float"
    CEILING = "ceiling"
    WHAT_KILLS_IT = "what_kills_it"
    EXTREME_LIQUIDITY = "extreme_liquidity"


class ReviewStatus(StrEnum):
    PASS = "Pass"
    UNPROVEN = "Unproven"
    FAIL = "Fail"


@dataclass(frozen=True, slots=True)
class FilterDefinition:
    key: FilterKey
    name: str
    prompt: str


FILTERS: tuple[FilterDefinition, ...] = (
    FilterDefinition(FilterKey.GAP, "Gap", "Market perception versus what the business is becoming."),
    FilterDefinition(FilterKey.CHOKE_POINT, "Choke Point", "Durable moat/bottleneck and replication difficulty within approximately 18 months."),
    FilterDefinition(FilterKey.TURBO, "Turbo", "Operating leverage and fixed-cost absorption."),
    FilterDefinition(FilterKey.REAL_BUYERS, "Real Buyers", "Actual cash, customer advances, executable orders and collections, not just MoUs."),
    FilterDefinition(FilterKey.STACK, "Stack", "At least three mutually reinforcing advantages."),
    FilterDefinition(FilterKey.TRIGGER, "Trigger", "Dated, observable catalyst that could force rerating."),
    FilterDefinition(FilterKey.JOCKEY, "Jockey", "Management execution, capital allocation, integrity, incentives, ownership and promoter pledges."),
    FilterDefinition(FilterKey.THIN_FLOAT, "Thin Float", "Genuine tradable supply and potential overhang."),
    FilterDefinition(FilterKey.CEILING, "Ceiling", "Obtainable market and realistic long-term growth potential."),
    FilterDefinition(FilterKey.WHAT_KILLS_IT, "What Kills It", "Explicit thesis killers, permanent impairment risks and pre-mortem."),
    FilterDefinition(FilterKey.EXTREME_LIQUIDITY, "Extreme Liquidity", "Forced/structural selling versus fundamental selling, measured against actual absorption capacity."),
)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    source_document_id: str
    source_identifier: str
    checksum_sha256: str
    locator: str
    note: str


@dataclass(frozen=True, slots=True)
class FilterReview:
    """One human-authored review event; later reviews must be appended."""

    issuer_entity_id: str
    filter_key: FilterKey
    status: ReviewStatus
    reviewer: str
    reviewed_at: datetime
    rationale: str
    evidence: tuple[EvidenceReference, ...]
