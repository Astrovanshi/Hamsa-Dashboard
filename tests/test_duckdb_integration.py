"""Integration tests executed by the pinned DuckDB 2.0 Python engine."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import duckdb

from hamsa.domain.financials import (
    AsReportedStatus,
    FinancialObservationRevision,
    PublicationPrecision,
    QualityStatus,
)
from hamsa.domain.trading_calendar import AvailabilityMode
from hamsa.storage.as_reported import as_reported_snapshot
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "sql" / "duckdb_schema.sql"
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
UTC = timezone.utc


class CalendarFixture:
    version = "synthetic-calendar-v1"
    sessions = {date(2024, 1, 5), date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10)}

    def is_trading_session(self, session):
        return session in self.sessions

    def next_trading_session(self, after):
        return min(day for day in self.sessions if day > after)


class DuckDBSchemaIntegrationTests(TestCase):
    def connection(self):
        con = duckdb.connect(":memory:")
        con.execute(SCHEMA.read_text(encoding="utf-8"))
        return con

    @staticmethod
    def checksum(label):
        return sha256(label.encode("utf-8")).hexdigest()

    def seed_source(self, con, suffix="1", *, published="2024-01-05 10:00:00+05:30", ingested="2024-01-05 11:00:00+05:30"):
        file_id, doc_id = f"file-{suffix}", f"doc-{suffix}"
        con.execute(
            """INSERT INTO raw_source_file VALUES (?, 'synthetic', 'results', ?, ?, ?,
               ?, DATE '2024-01-05', 'synthetic-license-review', 'approved', NULL)""",
            [file_id, f"archive-{suffix}.bin", self.checksum(f"file-{suffix}"), f"archive/{suffix}", datetime.fromisoformat("2024-01-05T12:00:00+05:30")],
        )
        con.execute(
            """INSERT INTO source_document_revision VALUES
               (?, 'synthetic', 'results', ?, ?, ?, 1, DATE '2024-01-05', ?,
                ?, ?, 'parser-1', ?, '$.results', NULL)""",
            [doc_id, f"filing-{suffix}", file_id, self.checksum(f"document-{suffix}"), datetime.fromisoformat(published).date(), datetime.fromisoformat(published), datetime.fromisoformat(ingested), datetime.fromisoformat("2024-01-05T12:05:00+05:30")],
        )
        return doc_id

    def seed_identity(self, con):
        con.execute("INSERT INTO issuer_entity VALUES ('issuer-1', TIMESTAMPTZ '2024-01-01 00:00:00+00')")
        con.execute("INSERT INTO equity_security VALUES ('security-1', 'issuer-1', 'EQ', TIMESTAMPTZ '2024-01-01 00:00:00+00')")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-nse', 'security-1', 'NSE', 'NSE-1', TIMESTAMPTZ '2024-01-01 00:00:00+00')")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-bse', 'security-1', 'BSE', 'BSE-1', TIMESTAMPTZ '2024-01-01 00:00:00+00')")

    def financial(self, observation_id, doc_id, *, value, publication, ingested, revision=1, supersedes=None, period_start=date(2023, 4, 1)):
        return FinancialObservationRevision(
            observation_id=observation_id, subject_id="issuer-1", metric="revenue", raw_value=Decimal(value),
            raw_unit="INR", canonical_value=Decimal(value), canonical_unit="INR", period_start=period_start,
            period_end=date(2023, 12, 31), source_document_date=date(2024, 1, 5), publication_date=publication.date(),
            publication_precision=PublicationPrecision.TIMESTAMP, published_at=publication,
            ingestion_timestamp=ingested, revision_number=revision, source_document_id=doc_id,
            as_reported_status=AsReportedStatus.ORIGINAL if revision == 1 else AsReportedStatus.RESTATEMENT,
            quality_status=QualityStatus.OBSERVED, quality_reason=None, reporting_scope="consolidated",
            source_locator="$.revenue", parser_version="parser-1", extraction_timestamp=ingested,
            supersedes_observation_id=supersedes,
        )

    def test_schema_executes_and_metadata_types_indexes_constraints_transactions(self):
        con = self.connection()
        tables = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='main'").fetchone()[0]
        self.assertEqual(tables, 39)
        self.assertEqual(con.execute("SELECT count(*) FROM duckdb_indexes() WHERE schema_name='main'").fetchone()[0], 4)
        self.assertEqual(con.execute("SELECT current_version,current_migration FROM schema_metadata").fetchone(), (1, "0001_initial_analytics"))
        self.assertEqual(con.execute("SELECT data_type FROM information_schema.columns WHERE table_name='financial_observation_revision' AND column_name='period_start'").fetchone()[0], "DATE")

        con.execute("BEGIN TRANSACTION")
        con.execute("INSERT INTO issuer_entity VALUES ('transient', CURRENT_TIMESTAMP)")
        con.execute("ROLLBACK")
        self.assertEqual(con.execute("SELECT count(*) FROM issuer_entity WHERE entity_id='transient'").fetchone()[0], 0)
        con.execute("INSERT INTO issuer_entity VALUES ('issuer-x', CURRENT_TIMESTAMP)")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO issuer_entity VALUES ('issuer-x', CURRENT_TIMESTAMP)")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO schema_metadata VALUES ('bad-schema', 0, 'bad', CURRENT_TIMESTAMP)")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO security_identifier_revision VALUES ('bad', 'unknown-security', 'ISIN', 'X', DATE '2020-01-01', NULL, 'missing-doc', 'approved', NULL, NULL, NULL)")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO observation_lineage_input VALUES ('missing', 'financial', 'also-missing', 'eod_price', 'formula-1')")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO screen_result_source_observation VALUES ('missing-result', 'missing-obs', 'financial')")

    def test_duckdb_20_documented_trigger_action_and_limitations(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE target (id INTEGER, val INTEGER)")
        con.execute("CREATE TABLE audit (id INTEGER, old_val INTEGER, new_val INTEGER)")
        # DuckDB 2.0's documented statement-level AFTER action is one DML statement.
        con.execute("""CREATE TRIGGER trg_audit AFTER UPDATE ON target
            REFERENCING OLD TABLE AS o NEW TABLE AS n FOR EACH STATEMENT
            INSERT INTO audit SELECT n.id, o.val, n.val FROM o JOIN n ON o.id=n.id""")
        con.execute("INSERT INTO target VALUES (1,10),(2,20)")
        con.execute("UPDATE target SET val=val*10")
        self.assertEqual(con.execute("SELECT * FROM audit ORDER BY id").fetchall(), [(1,10,100),(2,20,200)])
        self.assertEqual(con.execute("SELECT val FROM target WHERE id=1").fetchone()[0], 100)
        with self.assertRaises(duckdb.ParserException):
            con.execute("CREATE TRIGGER bad_select AFTER UPDATE ON target FOR EACH STATEMENT SELECT error('stop')")
        with self.assertRaises(Exception) as raised:
            con.execute("CREATE TRIGGER unsupported_row_update BEFORE UPDATE ON target FOR EACH ROW INSERT INTO audit VALUES (OLD.id, OLD.val, NEW.val)")
        self.assertRegex(str(raised.exception).lower(), "not supported|not yet supported|unsupported|parser|syntax")

    def test_nse_bse_resolve_to_one_security_and_historical_mappings(self):
        con = self.connection()
        doc = self.seed_source(con)
        self.seed_identity(con)
        con.execute("""INSERT INTO security_identifier_revision VALUES
            ('isin-old','security-1','ISIN','INE000A01000',DATE '2020-01-01',DATE '2023-12-31',?,'approved','reviewer',TIMESTAMPTZ '2024-01-01 00:00:00+00',NULL)""", [doc])
        con.execute("""INSERT INTO security_identifier_revision VALUES
            ('isin-new','security-1','ISIN','INE000A01001',DATE '2024-01-01',NULL,?,'approved','reviewer',TIMESTAMPTZ '2024-01-01 00:00:00+00','isin-old')""", [doc])
        con.execute("""INSERT INTO exchange_listing_revision VALUES
            ('symbol-old','listing-nse','OLD', 'EQ','active',DATE '2020-01-01',DATE '2023-12-31',?,NULL)""", [doc])
        con.execute("""INSERT INTO exchange_listing_revision VALUES
            ('symbol-new','listing-nse','NEW', 'EQ','active',DATE '2024-01-01',NULL,?,'symbol-old')""", [doc])
        rows = con.execute("SELECT l.exchange, l.security_id FROM exchange_listing l ORDER BY l.exchange").fetchall()
        self.assertEqual(rows, [("BSE", "security-1"), ("NSE", "security-1")])
        old = con.execute("SELECT security_id FROM security_identifier_revision WHERE identifier_value='INE000A01000'").fetchone()[0]
        new = con.execute("SELECT security_id FROM security_identifier_revision WHERE identifier_value='INE000A01001'").fetchone()[0]
        self.assertEqual(old, new)
        self.assertEqual(con.execute("SELECT symbol FROM exchange_listing_revision WHERE effective_from<=DATE '2022-01-01' AND (effective_to IS NULL OR effective_to>=DATE '2022-01-01')").fetchone()[0], "OLD")

    def test_financial_revision_pit_modes_period_start_and_provenance(self):
        con = self.connection()
        self.seed_source(con, "r1", published="2024-01-05 14:00:00+05:30", ingested="2024-01-05 14:30:00+05:30")
        self.seed_source(con, "r2", published="2024-01-08 15:31:00+05:30", ingested="2024-01-10 09:00:00+05:30")
        self.seed_identity(con)
        con.execute("INSERT INTO financial_metric_definition VALUES ('revenue','INR','currency','Revenue','v1')")
        with DuckDBRepository(":memory:") as repo:
            # The repository schema is independent from this test connection.
            c = repo._connection
            for suffix in ("r1", "r2"):
                self.seed_source(c, suffix, published="2024-01-05 14:00:00+05:30" if suffix == "r1" else "2024-01-08 15:31:00+05:30", ingested="2024-01-05 14:30:00+05:30" if suffix == "r1" else "2024-01-10 09:00:00+05:30")
            self.seed_identity(c)
            c.execute("INSERT INTO financial_metric_definition VALUES ('revenue','INR','currency','Revenue','v1')")
            first_pub = datetime(2024, 1, 5, 14, 0, tzinfo=IST)
            first_ing = datetime(2024, 1, 5, 14, 30, tzinfo=IST)
            revised_pub = datetime(2024, 1, 8, 15, 31, tzinfo=IST)
            revised_ing = datetime(2024, 1, 10, 9, 0, tzinfo=IST)
            o1 = self.financial("obs-r1", "doc-r1", value="100", publication=first_pub, ingested=first_ing)
            o2 = self.financial("obs-r2", "doc-r2", value="125", publication=revised_pub, ingested=revised_ing, revision=2, supersedes="obs-r1")
            repo.append_financial_observation(o1)
            repo.append_financial_observation(o2)
            # Natural key includes period_start; a different start period is distinct.
            other = self.financial("obs-other-period", "doc-r1", value="99", publication=first_pub, ingested=first_ing, period_start=date(2023, 1, 1))
            repo.append_financial_observation(other)
            rows = c.execute("""SELECT observation_id, subject_entity_id, metric, CAST(raw_value AS VARCHAR), canonical_unit,
                period_start, period_end, source_document_date, publication_date, CAST(published_at AS VARCHAR), CAST(ingestion_timestamp AS VARCHAR),
                revision_number, source_document_id, as_reported_status, quality_status, parser_version, extraction_locator
                FROM financial_observation_revision WHERE observation_id IN ('obs-r1','obs-r2') ORDER BY revision_number""").fetchall()
            self.assertEqual(len(rows), 2)
            prov = c.execute("""SELECT r.source_identifier, r.checksum_sha256, r.parser_version, r.extraction_locator,
                d.source_file_id, f.checksum_sha256 FROM normalized_observation_registry r
                JOIN source_document_revision d USING(source_document_id)
                JOIN raw_source_file f USING(source_file_id) WHERE r.observation_id='obs-r1'""").fetchone()
            self.assertEqual(prov[0], "filing-r1")
            self.assertEqual(prov[1], self.checksum("document-r1"))
            self.assertEqual(prov[2:], ("parser-1", "$.revenue", "file-r1", self.checksum("file-r1")))

            calendar = CalendarFixture()
            available = [o1, o2]
            public_jan8 = as_reported_snapshot(available, as_of_session=date(2024, 1, 8), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=calendar)
            known_jan8 = as_reported_snapshot(available, as_of_session=date(2024, 1, 8), mode=AvailabilityMode.HAMSA_KNOWN_AS_OF, calendar=calendar)
            public_jan9 = as_reported_snapshot(available, as_of_session=date(2024, 1, 9), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=calendar)
            known_jan9 = as_reported_snapshot(available, as_of_session=date(2024, 1, 9), mode=AvailabilityMode.HAMSA_KNOWN_AS_OF, calendar=calendar)
            self.assertEqual([x.observation_id for x in public_jan8], ["obs-r1"])
            self.assertEqual([x.observation_id for x in known_jan8], ["obs-r1"])
            self.assertEqual([x.observation_id for x in public_jan9], ["obs-r2"])
            self.assertEqual([x.observation_id for x in known_jan9], ["obs-r1"])

    def test_after_cutoff_and_date_only_follow_calendar(self):
        from hamsa.domain.trading_calendar import PublicAvailability, first_eligible_session

        cal = CalendarFixture()
        self.assertEqual(first_eligible_session(PublicAvailability(date(2024, 1, 8), datetime(2024, 1, 8, 15, 30, tzinfo=IST)), cal), date(2024, 1, 8))
        self.assertEqual(first_eligible_session(PublicAvailability(date(2024, 1, 8), datetime(2024, 1, 8, 15, 31, tzinfo=IST)), cal), date(2024, 1, 9))
        # Date-only published Friday becomes eligible Monday, skipping weekend.
        self.assertEqual(first_eligible_session(PublicAvailability(date(2024, 1, 5), None), cal), date(2024, 1, 8))

    def test_typed_lineage_conflict_quarantine_and_screen_source_integrity(self):
        con = self.connection()
        doc = self.seed_source(con)
        self.seed_identity(con)
        con.execute("INSERT INTO normalized_observation_registry VALUES ('input','eod_price',?,?,?,? ,CURRENT_TIMESTAMP,'$.close',NULL)", [doc, "market-file", self.checksum("document-1"), "parser-1"])
        con.execute("INSERT INTO normalized_observation_registry VALUES ('derived','financial',?,?,?,? ,CURRENT_TIMESTAMP,'$.calc','formula-1')", [doc, "filing-1", self.checksum("document-1"), "parser-1"])
        con.execute("INSERT INTO observation_lineage_input VALUES ('derived','financial','input','eod_price','formula-1')")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO observation_lineage_input VALUES ('derived','financial','input','financial','formula-1')")
        con.execute("INSERT INTO observation_quarantine VALUES ('q1',?,'$.bad','unit_conflict','ambiguous units',CURRENT_TIMESTAMP,NULL,NULL)", [doc])
        self.assertEqual(con.execute("SELECT reason_code FROM observation_quarantine WHERE quarantine_id='q1'").fetchone()[0], "unit_conflict")
        with self.assertRaises(duckdb.ConstraintException):
            con.execute("INSERT INTO screen_result_source_document VALUES ('missing-result',?)", [doc])

    def test_corporate_action_revision_and_adjusted_price_reproducibility(self):
        con = self.connection()
        doc = self.seed_source(con)
        self.seed_identity(con)
        for obs_id, kind in (("price", "eod_price"), ("action-v1", "corporate_action"), ("action-v2", "corporate_action"), ("factor-v1", "adjustment_factor"), ("adjusted-1", "adjusted_price")):
            con.execute("""INSERT INTO normalized_observation_registry
                (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,parser_version,extraction_timestamp,extraction_locator,formula_version)
                VALUES (?, ?, ?, ?, ?, 'parser-1', CURRENT_TIMESTAMP, '$.record', ?)""", [obs_id, kind, doc, obs_id, self.checksum(obs_id), "formula-1" if kind in ("adjustment_factor", "adjusted_price") else None])
        con.execute("""INSERT INTO eod_price_observation_revision VALUES
            ('price','eod_price','security-1','listing-nse','NSE',DATE '2024-01-05',10,11,9,10,'INR_PER_SHARE',100,'SHARES',1000,'INR',?, 'price-file', ?, 'parser-1', CURRENT_TIMESTAMP,'$.close','observed',NULL,NULL)""", [doc, self.checksum("price")])
        con.execute("""INSERT INTO corporate_action_event_revision VALUES
            ('action-v1','corporate_action','bonus-1',1,'bonus','security-1',NULL,?,DATE '2024-01-05',TIMESTAMPTZ '2024-01-05 10:00:00+05:30',DATE '2024-01-04',DATE '2024-02-01',DATE '2024-02-02',DATE '2024-02-02',TRUE,'{"ratio":"1:1"}',NULL)""", [doc])
        con.execute("""INSERT INTO corporate_action_event_revision VALUES
            ('action-v2','corporate_action','bonus-1',2,'bonus','security-1',NULL,?,DATE '2024-01-08',TIMESTAMPTZ '2024-01-08 10:00:00+05:30',DATE '2024-01-08',DATE '2024-02-01',DATE '2024-02-02',DATE '2024-02-02',TRUE,'{"ratio":"2:1"}','action-v1')""", [doc])
        con.execute("""INSERT INTO adjustment_factor_revision VALUES
            ('factor-v1','adjustment_factor','security-1','action-v2',DATE '2024-02-02',0.5,2.0,'set-v1','formula-1','approved',TRUE,DATE '2024-01-08','timestamp',TIMESTAMPTZ '2024-01-08 10:00:00+05:30',DATE '2024-01-08','calendar-v1',?,CURRENT_TIMESTAMP,'reviewer')""", [doc])
        con.execute("INSERT INTO adjustment_factor_input_price VALUES ('factor-v1','price','formula-1')")
        con.execute("""INSERT INTO adjusted_price_series_revision VALUES
            ('series-v1','security-1',DATE '2024-02-02','set-v1','retrospective',TIMESTAMPTZ '2024-02-03 16:00:00+05:30','formula-1',CURRENT_TIMESTAMP)""")
        con.execute("INSERT INTO adjusted_price_factor_input VALUES ('series-v1','factor-v1')")
        con.execute("""INSERT INTO adjusted_price_point VALUES
            ('adjusted-1','adjusted_price','series-v1','price',5,5.5,4.5,5,200,'formula-1')""")
        result = con.execute("""SELECT p.close_raw, a.adjusted_close, f.price_factor, e.revision_number
            FROM eod_price_observation_revision p JOIN adjusted_price_point a ON a.raw_observation_id=p.observation_id
            JOIN adjustment_factor_input_price i ON i.input_observation_id=p.observation_id
            JOIN adjustment_factor_revision f ON f.factor_id=i.factor_id
            JOIN corporate_action_event_revision e ON e.event_revision_id=f.event_revision_id""").fetchone()
        self.assertEqual(result, (Decimal("10.0000000000"), Decimal("5.0000000000000000"), Decimal("0.5000000000000000"), 2))
        # Raw observation is unchanged and the factor can be replayed exactly.
        self.assertEqual(result[0] * result[2], result[1])

    def test_repository_is_append_only_and_rejects_invalid_revision_atomically(self):
        with DuckDBRepository(":memory:") as repo:
            self.assertFalse(hasattr(repo, "update_financial_observation"))
            self.assertFalse(hasattr(repo, "delete_financial_observation"))
            self.assertFalse(hasattr(repo, "execute"))
            c = repo._connection
            doc = self.seed_source(c)
            self.seed_identity(c)
            c.execute("INSERT INTO financial_metric_definition VALUES ('revenue','INR','currency','Revenue','v1')")
            observation = self.financial("obs1", doc, value="10", publication=datetime(2024,1,5,10,tzinfo=IST), ingested=datetime(2024,1,5,11,tzinfo=IST))
            repo.append_financial_observation(observation)
            invalid = self.financial("obs2", doc, value="11", publication=datetime(2024,1,5,10,tzinfo=IST), ingested=datetime(2024,1,5,11,tzinfo=IST), revision=2, supersedes="obs1", period_start=date(2023,1,1))
            with self.assertRaises(RepositoryIntegrityError):
                repo.append_financial_observation(invalid)
            self.assertEqual(c.execute("SELECT count(*) FROM financial_observation_revision").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM normalized_observation_registry").fetchone()[0], 1)

    def test_conflicting_persisted_observations_remain_visible_and_are_flagged(self):
        with DuckDBRepository(":memory:") as repo:
            c = repo._connection
            doc_a = self.seed_source(c, "conflict-a", published="2024-01-05 12:00:00+05:30", ingested="2024-01-05 13:00:00+05:30")
            doc_b = self.seed_source(c, "conflict-b", published="2024-01-05 12:00:00+05:30", ingested="2024-01-05 13:00:00+05:30")
            self.seed_identity(c)
            c.execute("INSERT INTO financial_metric_definition VALUES ('revenue','INR','currency','Revenue','v1')")
            pub = datetime(2024, 1, 5, 12, tzinfo=IST)
            ingested = datetime(2024, 1, 5, 13, tzinfo=IST)
            a = self.financial("conflict-a", doc_a, value="100", publication=pub, ingested=ingested)
            b = self.financial("conflict-b", doc_b, value="105", publication=pub, ingested=ingested)
            repo.append_financial_observation(a)
            repo.append_financial_observation(b)
            persisted = c.execute("SELECT observation_id, CAST(canonical_value AS VARCHAR) FROM financial_observation_revision ORDER BY observation_id").fetchall()
            self.assertEqual(persisted, [("conflict-a", "100.000000000000"), ("conflict-b", "105.000000000000")])
            snapshot = as_reported_snapshot([a, b], as_of_session=date(2024, 1, 5), mode=AvailabilityMode.PUBLIC_AS_OF, calendar=CalendarFixture())
            self.assertEqual({item.quality_status for item in snapshot}, {QualityStatus.CONFLICTED})

    def test_on_disk_persistence_after_close_and_reopen(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "analytics.duckdb"
            with DuckDBRepository(path) as repo:
                repo._connection.execute("INSERT INTO issuer_entity VALUES ('persisted', CURRENT_TIMESTAMP)")
            with DuckDBRepository(path) as reopened:
                self.assertEqual(reopened._connection.execute("SELECT entity_id FROM issuer_entity").fetchall(), [("persisted",)])
                self.assertEqual(reopened._connection.execute("SELECT current_version FROM schema_metadata").fetchone()[0], 1)
                migration_checksum = reopened._connection.execute("SELECT migration_checksum_sha256 FROM schema_migration WHERE migration_id='0001_initial_analytics'").fetchone()[0]
                self.assertEqual(migration_checksum, sha256(SCHEMA.read_bytes()).hexdigest())


if __name__ == "__main__":
    import unittest

    unittest.main()
