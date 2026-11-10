"""Synthetic adapter edge cases; separate from tests against actual exchange files."""

from dataclasses import replace
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from hamsa.ingestion.pipeline import SyntheticFileSpec, SyntheticIngestionPipeline
from hamsa.providers.official_eod import parse_bse_stock_prices, parse_nse_delivery, parse_nse_udiff
from hamsa.storage.duckdb_repository import DuckDBRepository


HEADER = ("Date,Open Price,High Price,Low Price,Close Price,WAP,No.of Shares,No. of Trades,"
          "Total Turnover (Rs.),Deliverable Quantity,% Deli. Qty to Traded Qty,Spread High-Low,Spread Close-Open\n")
ROW = "9-November-2026,1029.50,1048.90,1022.15,1041.45,1038.597,1456011,36956,1512208913.00,877692,60.28,26.75,11.95\n"
MAPPING = {"instrument_id":"500112", "symbol":"SBIN", "isin":"INE062A01020",
           "effective_from":"2026-11-09", "company_name":"State Bank of India",
           "evidence_reference":"synthetic reviewed mapping reference"}


def spec(path: Path, *, parser_version="hamsa-official-eod-v1"):
    return SyntheticFileSpec(path=path, dataset="bse_stock_prices_eod", source_identifier="bse-sbin-2026-11-09",
        source_document_date=date(2026,11,9), publication_date=date(2026,11,9), published_at=None,
        source_as_of_date=date(2026,11,9), parser_version=parser_version, provider="BSE",
        license_reference="synthetic test", license_status="pending", retention_authorized=True,
        parser_options={"listing_mapping":MAPPING})


class OfficialEodSyntheticEdgeTests(unittest.TestCase):
    def test_portable_nse_udiff_and_delivery_parser_fixtures(self):
        udiff = ("TradDt,Sgmt,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TtlTrfVal\n"
                 "2026-11-09,CM,STK,3045,INE062A01020,SBIN,EQ,1030,1048.6,1022.3,1042,24065897,24974519875.55\n"
                 "2026-11-09,CM,STK,88,INE062A01020,SBIN,SM,1,1,1,1,1,1\n")
        delivery = ("SYMBOL, SERIES, DATE1, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER\n"
                    "SBIN, EQ, 09-Nov-2026, 24065897, 11162506, 46.38\n"
                    "OTHER, EQ, 09-Nov-2026, 100, -, -\n")
        with TemporaryDirectory() as temp:
            root=Path(temp); zip_path=root/"udiff.zip"
            with ZipFile(zip_path,"w",compression=ZIP_DEFLATED) as archive:
                archive.writestr("sample.csv",udiff)
            parsed, _, excluded=parse_nse_udiff(zip_path,allowed_series={"EQ"})
            self.assertEqual((len(parsed),excluded),(1,1))
            self.assertEqual(parsed[0]["_source_locator"],"zip:sample.csv:csv:line:2")
            self.assertEqual(parsed[0]["turnover"],"24974519875.55")
            csv_path=root/"delivery.csv"; csv_path.write_text(delivery,encoding="utf-8")
            delivery_rows, lines, out_of_scope=parse_nse_delivery(csv_path,symbols_allowlist={"SBIN"})
            self.assertEqual((len(delivery_rows),lines,out_of_scope),(1,[2],1))
            self.assertEqual(delivery_rows[0]["delivery_quantity"],"11162506")

    def test_missing_required_bse_header_is_not_guessed(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"missing.csv"
            path.write_text("Date,Open Price\n9-November-2026,1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "BSE stock-history header missing"):
                parse_bse_stock_prices(path, listing_mapping=MAPPING)

    def test_missing_conflicting_and_invalid_bse_mappings_quarantine_rows(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"eod.csv"; path.write_text(HEADER+ROW,encoding="utf-8")
            conflicting=[MAPPING,{**MAPPING,"isin":"IN0000000011"}]
            for index,mapping in enumerate((None, conflicting, {**MAPPING,"isin":"INE0000000000"}),start=1):
                with self.subTest(mapping=mapping):
                    parsed,_=parse_bse_stock_prices(path,listing_mapping=mapping)
                    self.assertIn("_parse_error",parsed[0])
                    repo=DuckDBRepository(Path(temp)/"db.duckdb")
                    version=f"hamsa-official-eod-v{index}"
                    pipeline=SyntheticIngestionPipeline(repo,archive_root=Path(temp)/"archive",
                        metric_units={"revenue":"INR"},identity_map={"INE062A01020":("issuer-sbi","security-sbi")},
                        parser_version=version)
                    result=pipeline.ingest_file(replace(spec(path,parser_version=version),source_identifier=f"bse-{index}",
                        parser_options={"listing_mapping":mapping}))
                    self.assertEqual(result.quarantined,1)
                    self.assertEqual(repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0],0)
                    self.assertEqual(repo._connection.execute("SELECT count(*) FROM exchange_listing").fetchone()[0],0)
                    repo.close()

    def test_distinct_isins_mapped_to_one_security_are_not_merged(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/"eod.csv"; path.write_text(HEADER+ROW,encoding="utf-8")
            repo=DuckDBRepository(Path(temp)/"hamsa.duckdb")
            pipeline=SyntheticIngestionPipeline(repo,archive_root=Path(temp)/"archive",
                metric_units={"revenue":"INR"},
                identity_map={"INE062A01020":("issuer-sbi","security-sbi"),"IN0000000011":("issuer-other","security-sbi")},
                parser_version="hamsa-official-eod-v1")
            result=pipeline.ingest_file(spec(path))
            self.assertGreaterEqual(result.quarantined,1)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM equity_security").fetchone()[0],0)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0],0)
            repo.close()

    def test_duplicate_rows_and_conflicting_rows_are_reported(self):
        cases = ((ROW+ROW, (2,2,0), (1,1)),
                 (ROW+ROW.replace("1041.45","1042.45"), (1,1,2), (0,1)))
        for rows, expected, persisted in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as temp:
                path=Path(temp)/"eod.csv"; path.write_text(HEADER+rows, encoding="utf-8")
                repo=DuckDBRepository(Path(temp)/"hamsa.duckdb")
                pipeline=SyntheticIngestionPipeline(repo, archive_root=Path(temp)/"archive",
                    metric_units={"revenue":"INR"}, identity_map={"INE062A01020":("issuer-sbi","security-sbi")},
                    parser_version="hamsa-official-eod-v1")
                result=pipeline.ingest_file(spec(path))
                self.assertEqual((result.accepted,result.rejected,result.quarantined), expected)
                self.assertEqual((repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0],
                                  repo._connection.execute("SELECT count(*) FROM delivery_observation_revision").fetchone()[0]), persisted)
                repo.close()

    def test_malformed_nse_zip_is_archived_but_creates_no_observation(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); path=root/"bad.zip"; path.write_bytes(b"not a ZIP")
            repo=DuckDBRepository(root/"hamsa.duckdb")
            pipeline=SyntheticIngestionPipeline(repo, archive_root=root/"archive",
                metric_units={"revenue":"INR"}, identity_map={"INE062A01020":("issuer-sbi","security-sbi")},
                parser_version="hamsa-official-eod-v1")
            nse_spec=SyntheticFileSpec(path=path,dataset="nse_udiff_eod",source_identifier="bad-nse-zip",
                source_document_date=date(2026,11,9),publication_date=date(2026,11,9),published_at=None,
                source_as_of_date=date(2026,11,9),parser_version="hamsa-official-eod-v1",provider="NSE",
                license_reference="synthetic test",license_status="pending",retention_authorized=True,
                parser_options={"series_allowlist":["EQ"]})
            result=pipeline.ingest_file(nse_spec)
            self.assertEqual(result.rejected,1)
            self.assertIn("malformed NSE UDiFF ZIP",result.error)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0],0)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM raw_source_file").fetchone()[0],1)
            repo.close()

    def test_changed_source_bytes_create_a_document_and_observation_revision(self):
        with TemporaryDirectory() as temp:
            root=Path(temp); first=root/"first.csv"; corrected=root/"corrected.csv"
            first.write_text(HEADER+ROW, encoding="utf-8")
            corrected.write_text(HEADER+ROW.replace("1041.45","1042.45"), encoding="utf-8")
            repo=DuckDBRepository(root/"hamsa.duckdb")
            pipeline=SyntheticIngestionPipeline(repo, archive_root=root/"archive",
                metric_units={"revenue":"INR"}, identity_map={"INE062A01020":("issuer-sbi","security-sbi")},
                parser_version="hamsa-official-eod-v1")
            self.assertEqual(pipeline.ingest_file(spec(first)).accepted, 2)
            revised=pipeline.ingest_file(replace(spec(corrected), source_identifier="bse-sbin-2026-11-09"))
            self.assertEqual((revised.accepted,revised.revised), (0,2))
            self.assertEqual(repo._connection.execute("SELECT max(revision_number) FROM source_document_revision").fetchone()[0], 2)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 2)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM delivery_observation_revision").fetchone()[0], 2)
            repo.close()
