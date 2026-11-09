"""Explainable, non-recommendation screen output types."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ScreenSignal:
    subject_entity_id: str
    engine: str
    as_of_date: date
    profile_id: str
    profile_version: str
    calculation_expression: str
    evaluated_inputs: tuple[tuple[str, Decimal | str | int | None], ...]
    source_document_ids: tuple[str, ...]
    source_observation_ids: tuple[str, ...]
    result: str
