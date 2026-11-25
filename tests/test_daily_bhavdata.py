"""Integration tests for Daily NSE Security Bhavdata Ingestion Pipeline."""

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.ingestion.daily_nse_bhavdata import DailyNseBhavdataPipeline, NseBhavdataParser
from hamsa.storage.duckdb_repository import DuckDBRepository


class DailyNseBhavdataPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bhav_file = ROOT / "data" / "raw" / "real" / "eod" / "nse" / "sec_bhavdata_full_09112026.csv"

    def test_parser_and_validation_on_actual_bhavcopy(self):
        val, records = NseBhavdataParser.parse_file(self.bhav_file, date(2026, 11, 9))
        self.assertTrue(val.is_valid)
        self.assertEqual(len(records), 2743)
        self.assertEqual(val.delivery_available_count, 2743)
        self.assertEqual(val.invalid_ohlc_bounds_count, 0)

        # Inspect first record
        rec0 = records[0]
        self.assertEqual(rec0.series, "EQ")
        self.assertEqual(rec0.trade_date, date(2026, 11, 9))
        self.assertGreater(rec0.open_price, 0)
        self.assertGreater(rec0.close_price, 0)
        self.assertGreaterEqual(rec0.high_price, rec0.low_price)

    def test_parser_quarantines_mismatched_date(self):
        val, records = NseBhavdataParser.parse_file(self.bhav_file, date(2026, 11, 10))
        self.assertFalse(val.is_valid)
        self.assertGreater(len(val.quarantine_reasons), 0)
        self.assertEqual(len(records), 0)


if __name__ == "__main__":
    unittest.main()