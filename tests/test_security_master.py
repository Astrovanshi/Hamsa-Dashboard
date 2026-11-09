from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from hashlib import sha256
import unittest

from hamsa.domain.security import Exchange, ListingCandidate, is_valid_isin
from hamsa.ingestion.security_master import build_security_master

IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class IsinTests(unittest.TestCase):
    def test_known_isins_and_checksum(self):
        self.assertTrue(is_valid_isin("INE669E01016"))
        self.assertTrue(is_valid_isin("INE009A01021"))
        self.assertFalse(is_valid_isin("INE669E01017"))
        self.assertFalse(is_valid_isin("not-an-isin"))


class SecurityMasterTests(unittest.TestCase):
    def row(self, exchange, code, symbol, isin, source="fixture"):
        return ListingCandidate(
            exchange=exchange,
            exchange_instrument_id=code,
            symbol=symbol,
            isin=isin,
            effective_from=date(2025, 1, 1),
            effective_to=None,
            source_file_id=source,
            source_document_id=f"doc-{source}",
            checksum_sha256=sha256(source.encode()).hexdigest(),
            parser_version="synthetic-security-master-1",
            extraction_timestamp=datetime(2025, 1, 2, 18, tzinfo=IST),
            extraction_locator="row:1",
            series="EQ",
            company_name="Same Name Is Not The Key",
        )

    def test_cross_exchange_listings_share_isin_but_remain_distinct(self):
        result = build_security_master((
            self.row(Exchange.NSE, "NSE123", "ABC", "INE669E01016", "nse-file"),
            self.row(Exchange.BSE, "BSE456", "ABC", "INE669E01016", "bse-file"),
        ))
        self.assertEqual(result.companies, ("INE669E01016",))
        self.assertEqual(len(result.listings), 2)
        self.assertEqual({row.exchange for row in result.listings}, {Exchange.NSE, Exchange.BSE})
        self.assertEqual({source for row in result.listings for source in row.source_file_ids}, {"nse-file", "bse-file"})
        self.assertEqual(result.issues, ())

    def test_same_name_different_isins_remain_separate(self):
        result = build_security_master((
            self.row(Exchange.NSE, "NSE123", "ABC", "INE669E01016"),
            self.row(Exchange.BSE, "BSE456", "ABC", "INE009A01021"),
        ))
        self.assertEqual(len(result.companies), 2)
        self.assertEqual(len(result.listings), 2)

    def test_identical_listing_rows_preserve_all_source_references(self):
        result = build_security_master((
            self.row(Exchange.NSE, "NSE123", "ABC", "INE669E01016", "master-1"),
            self.row(Exchange.NSE, "NSE123", "ABC", "INE669E01016", "master-2"),
        ))
        self.assertEqual(len(result.listings), 1)
        self.assertEqual(result.listings[0].source_file_ids, ("master-1", "master-2"))
        self.assertEqual(result.listings[0].source_document_ids, ("doc-master-1", "doc-master-2"))

    def test_symbol_change_keeps_sourced_effective_dated_listing_history(self):
        old = self.row(Exchange.NSE, "NSE123", "OLD", "INE669E01016", "master-old")
        new = ListingCandidate(
            exchange=Exchange.NSE,
            exchange_instrument_id="NSE123",
            symbol="NEW",
            isin="INE669E01016",
            effective_from=date(2024, 1, 1),
            effective_to=None,
            source_file_id="master-new",
            source_document_id="doc-master-new",
            checksum_sha256=sha256(b"master-new").hexdigest(),
            parser_version="synthetic-security-master-1",
            extraction_timestamp=datetime(2025, 1, 2, 18, tzinfo=IST),
            extraction_locator="row:1",
        )
        result = build_security_master((old, new))
        self.assertEqual(len(result.listings), 2)
        self.assertEqual({row.symbol for row in result.listings}, {"OLD", "NEW"})
        self.assertEqual({row.company_isin for row in result.listings}, {"INE669E01016"})
        self.assertEqual(len({row.listing_id for row in result.listings}), 1)

    def test_isin_change_creates_distinct_listing_identity(self):
        result = build_security_master((
            replace(self.row(Exchange.NSE, "NSE-100", "OLD", "INE669E01016", "old-isin"), effective_from=date(2020,1,1)),
            replace(self.row(Exchange.NSE, "NSE-100", "NEW", "INE009A01021", "new-isin"), effective_from=date(2025,1,1)),
        ))
        self.assertEqual(len(result.listings), 2)
        self.assertEqual(len({row.listing_id for row in result.listings}), 2)

    def test_missing_or_invalid_isin_is_quarantined(self):
        result = build_security_master((
            self.row(Exchange.NSE, "NSE123", "ABC", None),
            self.row(Exchange.BSE, "BSE456", "ABC", "INE669E01017"),
        ))
        self.assertEqual(result.listings, ())
        self.assertEqual(len(result.issues), 2)

    def test_conflicting_duplicate_source_key_is_quarantined(self):
        result = build_security_master((
            self.row(Exchange.NSE, "NSE123", "ABC", "INE669E01016"),
            self.row(Exchange.NSE, "NSE123", "XYZ", "INE009A01021"),
        ))
        self.assertEqual(result.listings, ())
        self.assertEqual(len(result.issues), 2)


if __name__ == "__main__":
    unittest.main()
