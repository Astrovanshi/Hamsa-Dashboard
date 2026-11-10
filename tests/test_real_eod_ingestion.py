"""Tests against downloaded official NSE/BSE EOD samples (not synthetic fixtures).

The sample archive is deliberately gitignored. These tests run when the user
has downloaded the documented files into data/raw/real/eod; otherwise they
skip and do not substitute generated data.
"""

from datetime import date
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hamsa.ingestion.pipeline import IngestionReport, SyntheticFileSpec, SyntheticIngestionPipeline
from hamsa.providers.official_eod import parse_bse_stock_prices, parse_nse_delivery, parse_nse_udiff
from hamsa.storage.duckdb_repository import DuckDBRepository


ROOT = Path(__file__).resolve().parents[1] / "data" / "raw" / "real" / "eod"
NSE_PRICE = ROOT / "nse" / "BhavCopy_NSE_CM_0_0_0_20261109_F_0000.csv.zip"
NSE_DELIVERY = ROOT / "nse" / "sec_bhavdata_full_09112026.csv"
BSE_PRICE = ROOT / "bse" / "bse_sbin_2026-11-09.csv"
DAY = date(2026, 11, 9)
IDENTITY_MAP = {"INE062A01020": ("issuer-sbi", "security-ine062a01020")}
BSE_MAPPING = {
    "instrument_id": "500112", "symbol": "SBIN", "isin": "INE062A01020",
    "effective_from": "2026-11-09", "company_name": "State Bank of India",
    "evidence_reference": "BSE Stock Prices public lookup, SBIN/INE062A01020/500112, 2026-11-09",
}


def real_spec(path: Path, dataset: str, *, provider: str, options=None):
    return SyntheticFileSpec(
        path=path, dataset=dataset, source_identifier=path.name,
        source_document_date=DAY, publication_date=date(2026, 11, 10), published_at=None,
        source_as_of_date=DAY, parser_version="hamsa-official-eod-v1",
        original_filename=path.name, provider=provider,
        license_reference="user-directed-public-file-ingestion; terms unreviewed",
        license_status="pending", retention_authorized=True,
        parser_options=options or {},
    )


@unittest.skipUnless(NSE_PRICE.is_file() and NSE_DELIVERY.is_file() and BSE_PRICE.is_file(),
                     "downloaded official NSE/BSE EOD samples are not present")
class RealEodFileTests(unittest.TestCase):
    def test_official_headers_dates_fields_and_sbin_values(self):
        nse_rows, _, excluded = parse_nse_udiff(NSE_PRICE, allowed_series={"EQ"})
        nse = next(row for row in nse_rows if row.get("isin") == "INE062A01020")
        self.assertEqual((nse["trade_date"], nse["instrument_id"], nse["symbol"], nse["series"]),
                         ("2026-11-09", "3045", "SBIN", "EQ"))
        self.assertEqual((nse["open"], nse["high"], nse["low"], nse["close"]),
                         ("1030.00", "1048.60", "1022.30", "1042.00"))
        self.assertEqual(nse["volume"], "24065897")
        self.assertEqual(nse["turnover"], "24974519875.55")
        self.assertEqual(excluded, 961)

        delivery, _, _ = parse_nse_delivery(NSE_DELIVERY)
        nse_delivery = next(row for row in delivery if row["symbol"] == "SBIN" and row["series"] == "EQ")
        self.assertEqual((nse_delivery["delivery_quantity"], nse_delivery["delivery_percentage"]),
                         ("11162506", "46.38"))

        bse, _ = parse_bse_stock_prices(BSE_PRICE, listing_mapping=BSE_MAPPING)
        self.assertEqual(len(bse), 1)
        self.assertEqual((bse[0]["trade_date"], bse[0]["isin"], bse[0]["instrument_id"]),
                         ("2026-11-09", "INE062A01020", "500112"))
        self.assertEqual((bse[0]["open"], bse[0]["high"], bse[0]["low"], bse[0]["close"]),
                         ("1029.50", "1048.90", "1022.15", "1041.45"))
        self.assertEqual(bse[0]["turnover"], "1512208913.00")
        self.assertEqual((bse[0]["delivery_quantity"], bse[0]["delivery_percentage"]), ("877692", "60.28"))

    def test_end_to_end_cross_exchange_persistence_provenance_and_idempotency(self):
        with TemporaryDirectory() as temp:
            repo = DuckDBRepository(Path(temp) / "real-eod.duckdb")
            pipeline = SyntheticIngestionPipeline(repo, archive_root=Path(temp) / "archive",
                metric_units={"revenue": "INR"}, identity_map=IDENTITY_MAP,
                parser_version="hamsa-official-eod-v1")
            nse_spec = real_spec(NSE_PRICE, "nse_udiff_eod", provider="NSE",
                options={"series_allowlist": ["EQ"], "isin_allowlist": ["INE062A01020"]})
            bse_spec = real_spec(BSE_PRICE, "bse_stock_prices_eod", provider="BSE",
                options={"listing_mapping": BSE_MAPPING})
            delivery_spec = real_spec(NSE_DELIVERY, "nse_delivery", provider="NSE",
                options={"symbols_allowlist": ["SBIN"]})

            nse_result = pipeline.ingest_file(nse_spec)
            bse_result = pipeline.ingest_file(bse_spec)
            delivery_result = pipeline.ingest_file(delivery_spec)
            self.assertEqual((nse_result.accepted, nse_result.quarantined, nse_result.rejected, nse_result.out_of_scope), (1, 0, 0, 3703))
            self.assertEqual((bse_result.accepted, bse_result.quarantined), (2, 0))
            self.assertEqual((delivery_result.accepted, delivery_result.quarantined, delivery_result.rejected, delivery_result.out_of_scope), (1, 0, 0, 3550))
            report=IngestionReport()
            for result in (nse_result,delivery_result,bse_result):
                report.add(result)
            self.assertEqual((report.accepted,report.rejected,report.out_of_scope,report.quarantined,report.duplicates,report.revised),
                             (4,0,7253,0,0,0))

            con = repo._connection
            self.assertEqual(con.execute("SELECT count(*) FROM equity_security WHERE security_id=?", ["security-ine062a01020"]).fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT exchange,exchange_instrument_id FROM exchange_listing ORDER BY exchange").fetchall(),
                             [("BSE", "500112"), ("NSE", "3045")])
            prices = con.execute("""SELECT exchange,open_raw::DOUBLE,high_raw::DOUBLE,low_raw::DOUBLE,close_raw::DOUBLE,
                volume_raw::DOUBLE,turnover_raw::DOUBLE
                FROM eod_price_observation_revision ORDER BY exchange""").fetchall()
            self.assertEqual(prices, [
                ("BSE", 1029.5, 1048.9, 1022.15, 1041.45, 1456011.0, 1512208913.0),
                ("NSE", 1030.0, 1048.6, 1022.3, 1042.0, 24065897.0, 24974519875.55),
            ])
            self.assertEqual(con.execute("SELECT exchange,delivery_quantity_raw::DOUBLE,delivery_percentage_raw::DOUBLE FROM delivery_observation_revision ORDER BY exchange").fetchall(),
                             [("BSE", 877692.0, 60.28), ("NSE", 11162506.0, 46.38)])
            provenance = con.execute("""SELECT r.source_identifier,r.checksum_sha256,r.parser_version,r.extraction_locator
                FROM normalized_observation_registry r ORDER BY r.observation_type,r.source_identifier""").fetchall()
            self.assertEqual(len(provenance), 4)
            self.assertTrue(all(len(item[1]) == 64 and item[2] == "hamsa-official-eod-v1" and item[3] for item in provenance))
            self.assertEqual(con.execute("SELECT license_status FROM raw_source_file ORDER BY provider,dataset").fetchall(),
                             [("pending",), ("pending",), ("pending",)])
            availability = con.execute("""SELECT publication_date,CAST(published_at AS VARCHAR),
                CAST(ingestion_timestamp AS VARCHAR),CAST(replay_timestamp AS VARCHAR)
                FROM source_document_revision WHERE source_identifier=?""", [NSE_PRICE.name]).fetchone()
            self.assertEqual(availability[0], date(2026, 11, 10))
            self.assertIsNone(availability[1])
            self.assertIsNone(availability[3])
            self.assertRegex(availability[2], r"[+-]\d\d:\d\d$")
            self.assertGreaterEqual(availability[2][:10], DAY.isoformat())

            before = con.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0]
            duplicate = pipeline.ingest_file(nse_spec)
            self.assertEqual(duplicate.duplicates, 1)
            self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], before)
            docs_before = con.execute("SELECT count(*) FROM source_document_revision").fetchone()[0]
            v2_spec = replace(nse_spec, parser_version="hamsa-official-eod-v2")
            v2_pipeline = SyntheticIngestionPipeline(repo, archive_root=Path(temp) / "archive",
                metric_units={"revenue": "INR"}, identity_map=IDENTITY_MAP,
                parser_version="hamsa-official-eod-v2")
            v2_result = v2_pipeline.ingest_file(v2_spec)
            self.assertEqual((v2_result.accepted, v2_result.revised), (0, 1))
            self.assertEqual(con.execute("SELECT count(*) FROM source_document_revision").fetchone()[0], docs_before)
            self.assertEqual(con.execute("SELECT count(DISTINCT parser_version) FROM eod_price_observation_revision").fetchone()[0], 2)
            with self.assertRaisesRegex(ValueError, "parser options changed"):
                v2_pipeline.ingest_file(replace(v2_spec, parser_options={"series_allowlist": ["EQ", "SM"], "isin_allowlist": ["INE062A01020"]}))
            repo.close()
