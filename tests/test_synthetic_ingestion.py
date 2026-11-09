from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import duckdb

from hamsa.domain.trading_calendar import AvailabilityMode
from hamsa.ingestion.pipeline import IngestionReport, SyntheticFileSpec, SyntheticIngestionPipeline
from hamsa.storage.duckdb_repository import DuckDBRepository


ROOT = Path(__file__).resolve().parent / "fixtures" / "synthetic"
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


class SyntheticCalendar:
    version = "synthetic-exchange-calendar-2024-v1"
    sessions = {
        date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9),
        date(2024, 1, 10), date(2024, 1, 11), date(2024, 1, 12),
    }

    def is_trading_session(self, session):
        return session in self.sessions

    def next_trading_session(self, after):
        return min(day for day in self.sessions if day > after)


def spec(filename, dataset, source_identifier, *, published, source_date=date(2024, 1, 5), as_of=None):
    return SyntheticFileSpec(
        path=ROOT / filename,
        dataset=dataset,
        source_identifier=source_identifier,
        source_document_date=source_date,
        publication_date=published.date() if published else source_date,
        published_at=published,
        source_as_of_date=as_of,
        parser_version="hamsa-synthetic-csv-v1",
    )


def complete_specs():
    return [
        spec("security_master_nse.csv", "security_master_nse", "synthetic-nse-master-2024", published=datetime(2024,1,2,10,tzinfo=IST), source_date=date(2024,1,2)),
        spec("security_master_bse.csv", "security_master_bse", "synthetic-bse-master-2024", published=datetime(2024,1,2,10,tzinfo=IST), source_date=date(2024,1,2)),
        spec("security_master_ambiguous.csv", "security_master_nse", "synthetic-nse-ambiguous", published=datetime(2024,1,2,10,tzinfo=IST), source_date=date(2024,1,2)),
        spec("eod_nse.csv", "eod_nse", "eod-nse-2024-01-05", published=None, as_of=date(2024,1,5)),
        spec("eod_bse.csv", "eod_bse", "eod-bse-2024-01-05", published=None, as_of=date(2024,1,5)),
        spec("eod_nse_corrected.csv", "eod_nse", "eod-nse-2024-01-05", published=None, source_date=date(2024,1,9), as_of=date(2024,1,5)),
        spec("quarterly_results_q3.csv", "quarterly_results", "results-q3-fy24", published=datetime(2024,1,5,14,tzinfo=IST)),
        spec("quarterly_results_q3_revised.csv", "quarterly_results", "results-q3-fy24", published=datetime(2024,1,8,15,31,tzinfo=IST), source_date=date(2024,1,8)),
        spec("quarterly_results_alternate.csv", "quarterly_results", "alternate-results-q3", published=datetime(2024,1,10,10,tzinfo=IST), source_date=date(2024,1,10)),
        spec("corporate_filings.csv", "corporate_filings", "synthetic-corporate-filings-2024", published=datetime(2024,1,5,12,tzinfo=IST)),
        spec("malformed_source.csv", "security_master_nse", "malformed-nse-master", published=datetime(2024,1,2,10,tzinfo=IST), source_date=date(2024,1,2)),
    ]


def new_pipeline(db_path, archive_root):
    repo = DuckDBRepository(db_path)
    pipeline = SyntheticIngestionPipeline(
        repo,
        archive_root=archive_root,
        metric_units={"revenue": "INR", "net_profit": "INR", "cash_flow": "INR"},
        identity_map={
            "IN0000000011": ("issuer-alpha", "security-alpha"),
            "IN0000000029": ("issuer-beta", "security-beta"),
        },
        parser_version="hamsa-synthetic-csv-v1",
        replay_mode=True,
        replay_clock=lambda: datetime(2024, 1, 1, 12, tzinfo=IST),
    )
    return repo, pipeline


def combine_reports(*reports):
    combined = IngestionReport()
    for report in reports:
        for item in report.files:
            combined.add(item)
    return combined


class SyntheticIngestionEndToEndTests(unittest.TestCase):
    def test_complete_synthetic_vertical_slice_and_report(self):
        with TemporaryDirectory() as temp:
            repo, pipeline = new_pipeline(Path(temp) / "hamsa.duckdb", Path(temp) / "raw")
            specs = complete_specs()
            report = pipeline.ingest_files(specs + [specs[6]])
            self.assertEqual((report.accepted, report.rejected, report.quarantined, report.duplicates, report.revised), (14, 2, 3, 4, 5))

            # NSE and BSE instruments share two canonical securities; references remain venue-specific.
            con = repo._connection
            self.assertEqual(con.execute("SELECT count(*) FROM equity_security").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT exchange,count(*) FROM exchange_listing GROUP BY exchange ORDER BY exchange").fetchall(), [("BSE",2),("NSE",2)])
            self.assertEqual(con.execute("SELECT count(*) FROM exchange_listing_revision WHERE extraction_revision_id IS NOT NULL AND parser_version='hamsa-synthetic-csv-v1'").fetchone()[0], 4)
            self.assertEqual(con.execute("SELECT count(*) FROM observation_quarantine").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT count(*) FROM corporate_action_event_revision").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT count(*) FROM adjustment_factor_revision").fetchone()[0], 0)

            # Raw archive, checksums and source identifiers survive normalization.
            provenance = con.execute("""SELECT r.source_identifier,r.checksum_sha256,r.parser_version,r.extraction_locator,
                d.source_file_id,f.archive_path FROM normalized_observation_registry r
                JOIN source_document_revision d USING(source_document_id)
                JOIN raw_source_file f USING(source_file_id) WHERE r.observation_type='financial' LIMIT 1""").fetchone()
            self.assertEqual(provenance[0], "results-q3-fy24")
            self.assertEqual(len(provenance[1]), 64)
            self.assertEqual(provenance[2], "hamsa-synthetic-csv-v1")
            self.assertTrue(provenance[3].startswith("csv:line:"))
            self.assertTrue(Path(provenance[5]).is_file())

            # The original and correction remain stored; the EOD correction also points to its prior observation.
            price_versions = con.execute("""SELECT close_raw,supersedes_observation_id FROM eod_price_observation_revision
                JOIN source_document_revision USING(source_document_id)
                WHERE exchange='NSE' AND listing_id=(SELECT listing_id FROM exchange_listing WHERE exchange='NSE' AND exchange_instrument_id='NSE-100')
                ORDER BY source_document_revision.revision_number""").fetchall()
            self.assertEqual([row[0] for row in price_versions], [Decimal("102.0000000000"), Decimal("104.0000000000")])
            self.assertIsNone(price_versions[0][1])
            self.assertIsNotNone(price_versions[1][1])

            # Financial historical view sees a public restatement after cutoff;
            # HAMSA-known view excludes it until its later ingestion timestamp.
            calendar = SyntheticCalendar()
            before_next_session = pipeline.financial_snapshot(as_of_session=date(2024,1,8), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=calendar)
            public = pipeline.financial_snapshot(as_of_session=date(2024,1,9), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=calendar)
            known = pipeline.financial_snapshot(as_of_session=date(2024,1,9), mode=AvailabilityMode.HAMSA_KNOWN_AS_OF, calendar=calendar)
            alpha = con.execute("SELECT issuer_entity_id FROM equity_security WHERE security_id=(SELECT security_id FROM security_identifier_revision WHERE identifier_value='IN0000000011' LIMIT 1)").fetchone()[0]
            public_alpha_revenue = [row for row in public if row.subject_id==alpha and row.metric=="revenue"]
            known_alpha_revenue = [row for row in known if row.subject_id==alpha and row.metric=="revenue"]
            before_alpha_revenue = [row for row in before_next_session if row.subject_id==alpha and row.metric=="revenue"]
            self.assertEqual([row.canonical_value for row in before_alpha_revenue], [Decimal("100.000000000000")])
            self.assertEqual([row.canonical_value for row in public_alpha_revenue], [Decimal("125.000000000000")])
            self.assertEqual(known_alpha_revenue, [])
            timestamps = con.execute("SELECT CAST(ingestion_timestamp AS VARCHAR),CAST(replay_timestamp AS VARCHAR) FROM source_document_revision WHERE source_identifier='results-q3-fy24'").fetchone()
            self.assertGreater(int(timestamps[0][:4]), 2024)
            self.assertIn("2024-01-01 12:00:00+05:30", timestamps[1])
            # Blank quarterly net profit remains a missing NULL, not numeric zero.
            missing = con.execute("SELECT canonical_value,quality_status FROM financial_observation_revision WHERE metric='net_profit' AND quality_status='missing'").fetchone()
            self.assertEqual(missing, (None, "missing"))

            # A separate, later-published source disagrees. Both facts remain visible and become conflicted in the view.
            final = pipeline.financial_snapshot(as_of_session=date(2024,1,11), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=calendar)
            conflict = [row for row in final if row.subject_id==alpha and row.metric=="revenue" and row.quality_status.value=="conflicted"]
            self.assertEqual({row.canonical_value for row in conflict}, {Decimal("125.000000000000"), Decimal("130.000000000000")})

            # Same file is idempotent; records are reported as duplicates and no new rows appear.
            before = con.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0]
            duplicate = pipeline.ingest_file(complete_specs()[6])
            self.assertEqual(duplicate.duplicates, 4)
            self.assertEqual(con.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], before)
            report_dict = report.as_dict()
            self.assertEqual(report_dict["accepted"], 14)
            self.assertEqual(report_dict["duplicates"], 4)
            repo.close()

    def test_replay_into_fresh_database_has_equivalent_normalized_rows_and_lineage(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "raw"
            repo_a, pipeline_a = new_pipeline(Path(temp) / "first.duckdb", archive)
            repo_b, pipeline_b = new_pipeline(Path(temp) / "second.duckdb", archive)
            first = pipeline_a.ingest_files(complete_specs())
            second = pipeline_b.ingest_files(complete_specs())
            self.assertEqual(first.as_dict(), second.as_dict())
            queries = (
                "SELECT observation_id,observation_type,source_identifier,checksum_sha256,parser_version,extraction_locator FROM normalized_observation_registry ORDER BY observation_id",
                "SELECT observation_id,subject_entity_id,metric,CAST(canonical_value AS VARCHAR),period_start,period_end,source_document_id,revision_number,supersedes_observation_id,quality_status FROM financial_observation_revision ORDER BY observation_id",
                "SELECT observation_id,security_id,listing_id,exchange,trade_date,CAST(close_raw AS VARCHAR),source_document_id,supersedes_observation_id FROM eod_price_observation_revision ORDER BY observation_id",
                "SELECT event_revision_id,event_id,revision_number,action_type,source_document_id,supersedes_event_revision_id FROM corporate_action_event_revision ORDER BY event_revision_id",
                "SELECT source_identifier,checksum_sha256,revision_number,supersedes_source_document_id FROM source_document_revision ORDER BY source_identifier,revision_number",
                "SELECT d.source_identifier,p.parser_version,p.attempt_number,CAST(p.replay_timestamp AS VARCHAR),p.status FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) ORDER BY d.source_identifier,p.parser_version,p.attempt_number",
            )
            for query in queries:
                self.assertEqual(repo_a._connection.execute(query).fetchall(), repo_b._connection.execute(query).fetchall())
            repo_a.close()
            repo_b.close()

    def test_failed_file_transaction_rolls_back_all_observations(self):
        with TemporaryDirectory() as temp:
            repo, pipeline = new_pipeline(Path(temp) / "atomic.duckdb", Path(temp) / "raw")
            # First row is valid. The second overflows DuckDB DECIMAL after the
            # first insert has occurred, forcing a genuine transaction rollback.
            source = Path(temp) / "overflow.csv"
            source.write_text(
                "isin,metric,value,unit,period_start,period_end,reporting_scope\n"
                "IN0000000011,revenue,100,INR,2023-10-01,2023-12-31,consolidated\n"
                "IN0000000011,revenue,999999999999999999999999999999999999999999999999999,INR,2023-10-01,2023-12-31,consolidated\n",
                encoding="utf-8",
            )
            # Seed the minimum valid security identity through the same files.
            pipeline.ingest_files(complete_specs()[:2])
            result = pipeline.ingest_file(SyntheticFileSpec(
                path=source,dataset="quarterly_results",source_identifier="overflow-results",
                source_document_date=date(2024,1,5),publication_date=date(2024,1,5),
                published_at=datetime(2024,1,5,14,tzinfo=IST),
                source_as_of_date=None,parser_version="hamsa-synthetic-csv-v1",
            ))
            self.assertEqual(result.accepted, 0)
            self.assertIn("transaction rolled back", result.error)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], 0)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM normalized_observation_registry WHERE observation_type='financial'").fetchone()[0], 0)
            # The raw file and its document stay archived for diagnosis.
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM raw_source_file WHERE dataset='quarterly_results'").fetchone()[0], 1)
            self.assertEqual(repo._connection.execute("SELECT status FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='overflow-results' ORDER BY attempt_number DESC LIMIT 1").fetchone()[0], "failed")
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='overflow-results' AND p.status='started'").fetchone()[0], 0)
            repo.close()

    def test_production_ingestion_clock_is_system_generated_and_replay_is_separate(self):
        with TemporaryDirectory() as temp:
            repo = DuckDBRepository(Path(temp) / "production.duckdb")
            pipeline = SyntheticIngestionPipeline(
                repo, archive_root=Path(temp) / "raw", metric_units={"revenue": "INR"},
                identity_map={"IN0000000011": ("issuer-alpha", "security-alpha")},
                parser_version="hamsa-synthetic-csv-v1",
            )
            with self.assertRaises(TypeError):
                SyntheticFileSpec(
                    path=ROOT / "security_master_nse.csv", dataset="security_master_nse",
                    source_identifier="backdated", source_document_date=date(2024,1,2),
                    publication_date=date(2024,1,2), published_at=datetime(2024,1,2,10,tzinfo=IST),
                    source_as_of_date=None, parser_version="hamsa-synthetic-csv-v1",
                    ingestion_timestamp=datetime(2020,1,1,tzinfo=timezone.utc),
                )
            pipeline.ingest_file(complete_specs()[0])
            actual, replay = repo._connection.execute(
                "SELECT CAST(ingestion_timestamp AS VARCHAR),CAST(replay_timestamp AS VARCHAR) FROM source_document_revision WHERE source_identifier='synthetic-nse-master-2024'"
            ).fetchone()
            self.assertGreater(int(actual[:4]), 2024)
            self.assertIsNone(replay)
            repo.close()

    def test_new_parser_reparses_same_bytes_without_source_revision(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "parser-revisions.duckdb"
            archive = Path(temp) / "raw"
            repo, v1 = new_pipeline(db, archive)
            v1.ingest_files(complete_specs()[:2])
            original = complete_specs()[6]
            first = v1.ingest_file(original)
            self.assertEqual((first.accepted,first.quarantined),(3,1))
            source_docs_before = repo._connection.execute(
                "SELECT count(*) FROM source_document_revision WHERE source_identifier='results-q3-fy24'"
            ).fetchone()[0]
            v2 = SyntheticIngestionPipeline(
                repo, archive_root=archive,
                metric_units={"revenue":"INR","net_profit":"INR","cash_flow":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha"),"IN0000000029":("issuer-beta","security-beta")},
                parser_version="hamsa-synthetic-csv-v2", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,2,12,tzinfo=IST),
            )
            revised = v2.ingest_file(replace(original, parser_version="hamsa-synthetic-csv-v2"))
            self.assertEqual((revised.accepted,revised.revised,revised.duplicates,revised.quarantined),(0,3,0,1))
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM source_document_revision WHERE source_identifier='results-q3-fy24'"
            ).fetchone()[0], source_docs_before)
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM financial_observation_revision f JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='results-q3-fy24'"
            ).fetchone()[0], 6)
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM financial_observation_revision WHERE parser_version='hamsa-synthetic-csv-v1' AND source_document_id=(SELECT source_document_id FROM source_document_revision WHERE source_identifier='results-q3-fy24')"
            ).fetchone()[0], 3)
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM financial_observation_revision WHERE parser_version='hamsa-synthetic-csv-v2' AND as_reported_status='recast' AND supersedes_observation_id IS NOT NULL"
            ).fetchone()[0], 3)
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM normalized_observation_registry r JOIN source_document_revision d USING(source_document_id) LEFT JOIN source_document_processing_revision p ON p.processing_revision_id=r.extraction_revision_id WHERE d.source_identifier='results-q3-fy24' AND (p.processing_revision_id IS NULL OR p.parser_version<>r.parser_version)"
            ).fetchone()[0], 0)
            parser_v1_snapshot = v2.financial_snapshot(
                as_of_session=date(2024,1,5), mode=AvailabilityMode.PUBLIC_AS_OF,
                calendar=SyntheticCalendar(), parser_version="hamsa-synthetic-csv-v1",
            )
            parser_v2_snapshot = v2.financial_snapshot(
                as_of_session=date(2024,1,5), mode=AvailabilityMode.PUBLIC_AS_OF,
                calendar=SyntheticCalendar(), parser_version="hamsa-synthetic-csv-v2",
            )
            v1_revenue = [row for row in parser_v1_snapshot if row.subject_id=="issuer-alpha" and row.metric=="revenue"]
            v2_revenue = [row for row in parser_v2_snapshot if row.subject_id=="issuer-alpha" and row.metric=="revenue"]
            self.assertEqual(len(v1_revenue),1)
            self.assertEqual(len(v2_revenue),1)
            self.assertEqual(v1_revenue[0].canonical_value,v2_revenue[0].canonical_value)
            self.assertNotEqual(v1_revenue[0].observation_id,v2_revenue[0].observation_id)
            duplicate = v2.ingest_file(replace(original, parser_version="hamsa-synthetic-csv-v2"))
            self.assertEqual((duplicate.duplicates,duplicate.accepted,duplicate.revised),(4,0,0))
            repo.close()

    def test_archived_but_unprocessed_source_is_recovered_idempotently(self):
        with TemporaryDirectory() as temp:
            db = Path(temp) / "recovery.duckdb"
            archive = Path(temp) / "raw"
            repo = DuckDBRepository(db)
            fired = []
            def crash(stage):
                if stage == "after_archive_before_database" and not fired:
                    fired.append(True)
                    raise RuntimeError("synthetic crash after archive")
            crashing = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST), fault_hook=crash,
            )
            with self.assertRaisesRegex(RuntimeError, "after archive"):
                crashing.ingest_file(complete_specs()[0])
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM source_document_revision").fetchone()[0], 0)
            self.assertEqual(len(list((archive / "_manifests").glob("*.json"))), 1)
            recovery = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST),
            )
            recovered = recovery.recover_archived_sources()
            self.assertEqual(recovered.accepted, 1)
            count = repo._connection.execute("SELECT count(*) FROM exchange_listing_revision").fetchone()[0]
            self.assertEqual(count, 1)
            self.assertEqual(recovery.recover_archived_sources().files, [])
            self.assertEqual(recovery.ingest_file(complete_specs()[0]).duplicates, 2)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM exchange_listing_revision").fetchone()[0], count)
            repo.close()

    def test_recovery_after_database_commit_before_manifest_update_is_idempotent(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "raw"
            repo = DuckDBRepository(Path(temp) / "post-commit-crash.duckdb")
            armed = [False]
            crashed = [False]
            def crash(stage):
                if armed[0] and stage == "after_database_commit_before_manifest" and not crashed[0]:
                    crashed[0] = True
                    raise RuntimeError("crash after database commit")
            pipeline = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR","net_profit":"INR","cash_flow":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha"),"IN0000000029":("issuer-beta","security-beta")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST), fault_hook=crash,
            )
            pipeline.ingest_files(complete_specs()[:2])
            armed[0] = True
            with self.assertRaisesRegex(RuntimeError, "after database commit"):
                pipeline.ingest_file(complete_specs()[6])
            before = repo._connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0]
            self.assertEqual(before, 3)
            self.assertEqual(repo._connection.execute("SELECT status FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='results-q3-fy24'").fetchone()[0], "succeeded")
            recovered = pipeline.recover_archived_sources()
            self.assertEqual(recovered.files, [])
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], before)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM source_document_revision WHERE source_identifier='results-q3-fy24'").fetchone()[0], 1)
            manifests = [json.loads(path.read_text(encoding="utf-8")) for path in (archive / "_manifests").glob("*.json")]
            manifest = next(item for item in manifests if item["source_identifier"] == "results-q3-fy24")
            self.assertIn("hamsa-synthetic-csv-v1", manifest["processed_parser_versions"])
            repo.close()

    def test_incomplete_observation_transaction_rolls_back_then_retries(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "raw"
            repo = DuckDBRepository(Path(temp) / "retry-transaction.duckdb")
            armed = [False]
            failed_once = [False]
            def fail_once(stage):
                if armed[0] and stage == "after_normalized_writes_before_commit" and not failed_once[0]:
                    failed_once[0] = True
                    raise RuntimeError("transient pre-commit fault")
            pipeline = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR","net_profit":"INR","cash_flow":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha"),"IN0000000029":("issuer-beta","security-beta")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST), fault_hook=fail_once,
            )
            pipeline.ingest_files(complete_specs()[:2])
            armed[0] = True
            failed = pipeline.ingest_file(complete_specs()[6])
            self.assertIn("transaction rolled back", failed.error)
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], 0)
            statuses = repo._connection.execute("SELECT status FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='results-q3-fy24' ORDER BY attempt_number").fetchall()
            self.assertEqual(statuses,[("failed",)])
            retried = pipeline.recover_archived_sources()
            self.assertEqual((retried.accepted,retried.quarantined),(3,1))
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], 3)
            self.assertEqual(repo._connection.execute("SELECT status FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id) WHERE d.source_identifier='results-q3-fy24' ORDER BY attempt_number").fetchall(),[("failed",),("succeeded",)])
            repo.close()

    def test_recovery_rejects_corrupted_archive_by_checksum_failure(self):
        with TemporaryDirectory() as temp:
            archive = Path(temp) / "raw"
            repo = DuckDBRepository(Path(temp) / "corruption.duckdb")
            crashing = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST),
                fault_hook=lambda _stage: (_ for _ in ()).throw(RuntimeError("crash")),
            )
            with self.assertRaisesRegex(RuntimeError, "crash"):
                crashing.ingest_file(complete_specs()[0])
            manifest_path = next((archive / "_manifests").glob("*.json"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            archived = Path(manifest["archive_path"])
            archived.write_bytes(archived.read_bytes() + b"tamper")
            recovery = SyntheticIngestionPipeline(
                repo, archive_root=archive, metric_units={"revenue":"INR"},
                identity_map={"IN0000000011":("issuer-alpha","security-alpha")},
                parser_version="hamsa-synthetic-csv-v1", replay_mode=True,
                replay_clock=lambda: datetime(2024,1,1,12,tzinfo=IST),
            )
            with self.assertRaisesRegex(ValueError, "checksum does not match"):
                recovery.recover_archived_sources()
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM source_document_revision").fetchone()[0], 0)
            repo.close()

    def test_rejects_invalid_units_and_malformed_files_without_zero_filling(self):
        with TemporaryDirectory() as temp:
            repo, pipeline = new_pipeline(Path(temp) / "quality.duckdb", Path(temp) / "raw")
            pipeline.ingest_files(complete_specs()[:2])
            report = pipeline.ingest_files(complete_specs()[6:7] + complete_specs()[-1:])
            self.assertEqual((report.accepted, report.rejected, report.quarantined), (3, 1, 1))
            self.assertEqual(repo._connection.execute("SELECT reason_code FROM observation_quarantine ORDER BY reason_code").fetchall(), [("invalid_or_unreviewed_unit",)])
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM financial_observation_revision WHERE quality_status='missing' AND canonical_value IS NULL").fetchone()[0], 1)
            repo.close()

    def test_missing_reviewed_identity_map_is_quarantined_instead_of_inferred(self):
        with TemporaryDirectory() as temp:
            repo = DuckDBRepository(Path(temp) / "identity.duckdb")
            pipeline = SyntheticIngestionPipeline(
                repo,
                archive_root=Path(temp) / "raw",
                metric_units={"revenue": "INR"},
                identity_map={"IN0000000029": ("issuer-beta", "security-beta")},
                parser_version="hamsa-synthetic-csv-v1",
            )
            result = pipeline.ingest_file(complete_specs()[0])
            self.assertEqual((result.accepted, result.quarantined), (1, 1))
            self.assertEqual(repo._connection.execute("SELECT reason_code FROM observation_quarantine").fetchone()[0], "unreviewed_identity_mapping")
            self.assertEqual(repo._connection.execute("SELECT count(*) FROM equity_security").fetchone()[0], 1)
            repo.close()


if __name__ == "__main__":
    unittest.main()
