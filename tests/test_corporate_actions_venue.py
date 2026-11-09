from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from hamsa.domain.financials import QualityStatus
from hamsa.domain.lifecycle import AdjustmentFactorRevision, ReviewStatus
from hamsa.domain.market_data import EodPriceObservation
from hamsa.screening.corporate_actions import (
    adjusted_price,
    factors_for_historical_screen,
    factors_for_retrospective_return,
)
from hamsa.screening.venue import VenuePolicy, combine_traded_activity, select_price


IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
AS_OF = date(2024, 1, 8)
CUTOFF = datetime(2024, 1, 8, 15, 30, tzinfo=IST)


def factor(
    factor_id,
    *,
    published_at=datetime(2024, 1, 9, 10, tzinfo=IST),
    effective_date=date(2024, 1, 8),
    terms_complete=True,
    status=ReviewStatus.APPROVED,
    price_factor=Decimal("0.5"),
    publication_date=date(2024, 1, 9),
    precision="timestamp",
    availability_session=date(2024, 1, 9),
):
    return AdjustmentFactorRevision(
        factor_id=factor_id,
        security_id="security-1",
        event_revision_id=f"event-{factor_id}",
        effective_date=effective_date,
        price_factor=price_factor,
        volume_factor=Decimal("2"),
        factor_version="factor-v1",
        formula_version="formula-v1",
        methodology_review_status=status,
        terms_complete=terms_complete,
        publication_date=publication_date,
        publication_precision=precision,
        publicly_available_at=published_at,
        public_availability_session=availability_session,
        availability_calendar_version="calendar-v1",
        source_document_id=f"doc-{factor_id}",
        input_observation_ids=(f"input-{factor_id}",),
    )


def bar(exchange, *, close="100", volume=10, turnover="1000", status=QualityStatus.OBSERVED, day=AS_OF):
    return EodPriceObservation(
        observation_id=f"{exchange}-{day}",
        security_id="security-1",
        listing_id=f"listing-{exchange}",
        exchange=exchange,
        trade_date=day,
        open=Decimal(close), high=Decimal(close), low=Decimal(close), close=Decimal(close),
        volume=volume,
        turnover=Decimal(turnover),
        source_document_id=f"doc-{exchange}",
        source_identifier=f"source-{exchange}",
        checksum_sha256="a" * 64,
        parser_version="synthetic-1",
        extraction_timestamp=datetime(2024, 1, 8, 18, tzinfo=IST),
        extraction_locator="row:1",
        quality_status=status,
    )


class CorporateActionTests(unittest.TestCase):
    def test_screen_does_not_see_factor_published_after_cutoff(self):
        later_confirmed = factor("split-1")
        selected = factors_for_historical_screen(
            (later_confirmed,), security_id="security-1", as_of_session=AS_OF,
            cutoff=CUTOFF, calendar_version="calendar-v1",
        )
        self.assertEqual(selected, ())

    def test_retrospective_return_can_use_later_confirmed_factor(self):
        later_confirmed = factor("split-1")
        selected = factors_for_retrospective_return(
            (later_confirmed,), security_id="security-1", through_date=AS_OF
        )
        self.assertEqual(selected, (later_confirmed,))
        self.assertEqual(adjusted_price(
            Decimal("100"), price_date=date(2024, 1, 5), factors=selected
        ), Decimal("50.0"))

    def test_screen_uses_only_published_effective_complete_approved_factors(self):
        valid = factor(
            "valid", published_at=datetime(2024, 1, 8, 15, 30, tzinfo=IST),
            publication_date=AS_OF, availability_session=AS_OF,
        )
        date_only = factor(
            "date-only", published_at=None, publication_date=AS_OF,
            precision="date_only", availability_session=date(2024, 1, 9),
        )
        future = factor(
            "future", published_at=datetime(2024, 1, 8, 10, tzinfo=IST),
            publication_date=AS_OF, availability_session=AS_OF, effective_date=date(2024, 1, 9),
        )
        selected = factors_for_historical_screen(
            (valid, date_only, future),
            security_id="security-1", as_of_session=AS_OF, cutoff=CUTOFF,
            calendar_version="calendar-v1",
        )
        self.assertEqual(selected, (valid,))

    def test_incomplete_or_unreviewed_terms_cannot_create_a_factor(self):
        with self.assertRaisesRegex(ValueError, "complete terms"):
            factor("incomplete", terms_complete=False)
        with self.assertRaisesRegex(ValueError, "approved methodology"):
            factor("pending", status=ReviewStatus.PENDING)

    def test_price_adjustment_does_not_mutate_raw_observation(self):
        raw = Decimal("100")
        adjusted = adjusted_price(raw, price_date=date(2024, 1, 5), factors=(factor(
            "split", published_at=datetime(2024, 1, 8, 10, tzinfo=IST),
            publication_date=AS_OF, availability_session=AS_OF,
        ),))
        self.assertEqual(raw, Decimal("100"))
        self.assertEqual(adjusted, Decimal("50.0"))


class VenuePolicyTests(unittest.TestCase):
    def test_prices_use_primary_and_are_never_averaged(self):
        selected = select_price(
            (bar("NSE", close="100"), bar("BSE", close="102")),
            policy=VenuePolicy("NSE", ("BSE",)),
        )
        self.assertIsNotNone(selected)
        self.assertEqual(selected.observation.close, Decimal("100"))
        self.assertFalse(selected.used_fallback)

    def test_explicit_fallback_used_when_primary_invalid(self):
        selected = select_price(
            (bar("NSE", close="100", status=QualityStatus.INVALID), bar("BSE", close="102")),
            policy=VenuePolicy("NSE", ("BSE",)),
        )
        self.assertEqual(selected.selected_exchange, "BSE")
        self.assertTrue(selected.used_fallback)

    def test_ambiguous_primary_venue_is_not_silently_chosen(self):
        primary_a = bar("NSE", close="100")
        primary_b = replace(primary_a, observation_id="NSE-duplicate", close=Decimal("99"))
        selected = select_price(
            (primary_a, primary_b, bar("BSE", close="102")),
            policy=VenuePolicy("NSE", ("BSE",)),
        )
        self.assertEqual(selected.selected_exchange, "BSE")

    def test_combined_volume_and_turnover_require_explicit_comparable_policy(self):
        rows = (bar("NSE", volume=10, turnover="1000"), bar("BSE", volume=5, turnover="550"))
        permitted = combine_traded_activity(
            rows, policy=VenuePolicy("NSE", ("BSE",), allow_combined_activity=True), comparable=True
        )
        self.assertEqual(permitted.total_volume, 15)
        self.assertEqual(permitted.total_turnover, Decimal("1550"))
        denied = combine_traded_activity(
            rows, policy=VenuePolicy("NSE", ("BSE",), allow_combined_activity=True), comparable=False
        )
        self.assertIsNone(denied)

    def test_delivery_observations_have_no_aggregation_path(self):
        from hamsa.domain.market_data import DeliveryObservation

        nse = DeliveryObservation(
            "d1", "security-1", "l1", "NSE", AS_OF, 7, 10, Decimal("70"), "doc-nse",
            "source-nse", "a" * 64, "parser-v1", datetime(2024, 1, 8, 18, tzinfo=IST), "row:1",
        )
        bse = DeliveryObservation(
            "d2", "security-1", "l2", "BSE", AS_OF, 4, 5, Decimal("80"), "doc-bse",
            "source-bse", "b" * 64, "parser-v1", datetime(2024, 1, 8, 18, tzinfo=IST), "row:2",
        )
        self.assertNotEqual(nse.delivery_percentage, bse.delivery_percentage)
        self.assertEqual((nse.exchange, bse.exchange), ("NSE", "BSE"))


if __name__ == "__main__":
    unittest.main()
