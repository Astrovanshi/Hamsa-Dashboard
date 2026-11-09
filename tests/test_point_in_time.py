from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from hamsa.domain.financials import (
    AsReportedStatus,
    FinancialObservationRevision,
    PublicationPrecision,
    QualityStatus,
)
from hamsa.domain.trading_calendar import (
    AvailabilityMode,
    PublicAvailability,
    first_eligible_session,
)
from hamsa.storage.as_reported import as_reported_snapshot


IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
FRI = date(2024, 1, 5)
SPECIAL = date(2024, 1, 7)
MON = date(2024, 1, 8)


class SyntheticCalendar:
    version = "synthetic-v1"
    sessions = {FRI, SPECIAL, MON, date(2024, 1, 9)}

    def is_trading_session(self, session):
        return session in self.sessions

    def next_trading_session(self, after):
        later = sorted(day for day in self.sessions if day > after)
        if not later:
            raise ValueError("no later session in synthetic calendar")
        return later[0]


CAL = SyntheticCalendar()


def fact(
    observation_id,
    *,
    published_at=None,
    publication_date=FRI,
    precision=PublicationPrecision.TIMESTAMP,
    ingestion=None,
    revision=1,
    supersedes=None,
    value="100",
    status=QualityStatus.OBSERVED,
    source_doc=None,
):
    if precision is PublicationPrecision.TIMESTAMP and published_at is None:
        published_at = datetime(2024, 1, 5, 12, tzinfo=IST)
    return FinancialObservationRevision(
        observation_id=observation_id,
        subject_id="issuer-1",
        metric="revenue",
        raw_value=Decimal(value) if value is not None else None,
        raw_unit="INR crore",
        canonical_value=Decimal(value) if value is not None else None,
        canonical_unit="INR",
        period_end=date(2023, 12, 31),
        source_document_date=date(2024, 1, 4),
        publication_date=publication_date,
        publication_precision=precision,
        published_at=published_at,
        ingestion_timestamp=ingestion or datetime(2024, 1, 5, 10, tzinfo=IST),
        revision_number=revision,
        source_document_id=source_doc or f"doc-{observation_id}",
        as_reported_status=AsReportedStatus.ORIGINAL if revision == 1 else AsReportedStatus.RESTATEMENT,
        quality_status=status,
        source_locator="page:1/table:1/row:1",
        supersedes_observation_id=supersedes,
        parser_version="synthetic-parser-1",
        extraction_timestamp=datetime(2024, 1, 5, 10, tzinfo=IST),
    )


class PublicationCalendarTests(unittest.TestCase):
    def test_timestamp_at_cutoff_is_eligible_same_session(self):
        availability = PublicAvailability(FRI, datetime(2024, 1, 5, 15, 30, tzinfo=IST))
        self.assertEqual(first_eligible_session(availability, CAL), FRI)

    def test_after_cutoff_uses_next_exchange_session_including_special_session(self):
        availability = PublicAvailability(FRI, datetime(2024, 1, 5, 15, 31, tzinfo=IST))
        self.assertEqual(first_eligible_session(availability, CAL), SPECIAL)

    def test_date_only_uses_next_exchange_session_not_next_calendar_day(self):
        availability = PublicAvailability(FRI, None)
        self.assertEqual(first_eligible_session(availability, CAL), SPECIAL)

    def test_naive_publication_timestamp_is_rejected(self):
        availability = PublicAvailability(FRI, datetime(2024, 1, 5, 12, 0))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            first_eligible_session(availability, CAL)


class PointInTimeSnapshotTests(unittest.TestCase):
    def test_date_only_and_after_close_are_not_visible_same_day(self):
        rows = (
            fact("date-only", precision=PublicationPrecision.DATE_ONLY, published_at=None),
            fact("after-close", published_at=datetime(2024, 1, 5, 15, 31, tzinfo=IST)),
        )
        self.assertEqual(as_reported_snapshot(
            rows, as_of_session=FRI, mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL
        ), ())
        self.assertEqual(
            {row.observation_id for row in as_reported_snapshot(
                rows, as_of_session=SPECIAL, mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL
            )},
            {"date-only", "after-close"},
        )

    def test_public_backfill_and_hamsa_known_mode_are_independent(self):
        backfill = fact(
            "backfill",
            published_at=datetime(2024, 1, 5, 12, tzinfo=IST),
            ingestion=datetime(2024, 1, 8, 16, tzinfo=IST),
        )
        public = as_reported_snapshot(
            (backfill,), as_of_session=FRI, mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL
        )
        known = as_reported_snapshot(
            (backfill,), as_of_session=FRI, mode=AvailabilityMode.HAMSA_KNOWN_AS_OF, calendar=CAL
        )
        self.assertEqual([row.observation_id for row in public], ["backfill"])
        self.assertEqual(known, ())

    def test_restated_fact_only_replaces_original_after_publication_session(self):
        original = fact(
            "original",
            published_at=datetime(2024, 1, 5, 12, tzinfo=IST),
            value="100",
        )
        restatement = fact(
            "restatement",
            published_at=datetime(2024, 1, 8, 10, tzinfo=IST),
            publication_date=MON,
            ingestion=datetime(2024, 1, 8, 11, tzinfo=IST),
            revision=2,
            supersedes="original",
            value="80",
        )
        fri = as_reported_snapshot(
            (original, restatement), as_of_session=FRI,
            mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL,
        )
        mon = as_reported_snapshot(
            (original, restatement), as_of_session=MON,
            mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL,
        )
        self.assertEqual([row.observation_id for row in fri], ["original"])
        self.assertEqual([row.observation_id for row in mon], ["restatement"])
        self.assertEqual(original.canonical_value, Decimal("100"))

    def test_unsuperseded_conflicts_are_both_retained(self):
        first = fact("filing-a", value="100", source_doc="a")
        second = fact("filing-b", value="120", source_doc="b")
        snapshot = as_reported_snapshot(
            (first, second), as_of_session=FRI,
            mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL,
        )
        self.assertEqual({row.observation_id for row in snapshot}, {"filing-a", "filing-b"})
        self.assertTrue(all(row.quality_status is QualityStatus.CONFLICTED for row in snapshot))
        self.assertTrue(all(row.canonical_value is not None for row in snapshot))

    def test_distinct_period_starts_with_same_end_are_separate_series(self):
        quarter = fact("quarter", value="100")
        year = replace(quarter, observation_id="year", period_start=date(2023, 1, 1), canonical_value=Decimal("400"))
        rows = as_reported_snapshot(
            (quarter, year), as_of_session=FRI,
            mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL,
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.period_start for row in rows}, {None, date(2023, 1, 1)})

    def test_hamsa_known_mode_requires_aware_ingestion_time(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            fact("naive", ingestion=datetime(2024, 1, 5, 10))

    def test_non_session_screen_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a trading session"):
            as_reported_snapshot(
                (), as_of_session=date(2024, 1, 6),
                mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CAL,
            )


if __name__ == "__main__":
    unittest.main()
