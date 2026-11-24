"""DuckDB 2.0 integration tests for additive schema migration v3."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import duckdb

from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
UTC = timezone.utc
V3 = "0003_listing_classification_and_eod_reconciliation"
COMPARATOR = "eod-raw-ohlcv-turnover-v1"


def digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def seed_source(con, doc_id: str, provider="NSE", *, published="2024-01-05T10:00:00+05:30",
                ingested="2024-01-05T11:00:00+05:30", dataset="security_master", parser="parser-1",
                revision=1, supersedes=None):
    published_at = datetime.fromisoformat(published) if published else None
    ingestion_at = datetime.fromisoformat(ingested)
    publication_date = published_at.date() if published_at else date.fromisoformat("2024-01-05")
    file_id = f"file-{doc_id}"
    con.execute(
        """INSERT INTO raw_source_file
           (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
            source_as_of_date,license_review_reference,license_status,metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,'approved',NULL)""",
        [file_id, provider, dataset, f"{doc_id}.dat", digest(f"raw-{doc_id}"), f"archive/{doc_id}",
         ingestion_at, publication_date, "synthetic-test-license"],
    )
    con.execute(
        """INSERT INTO source_document_revision
           (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,revision_number,
            source_document_date,publication_date,published_at,ingestion_timestamp,parser_version,
            extraction_timestamp,extraction_locator,supersedes_source_document_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [doc_id, provider, dataset, f"source-{doc_id}", file_id, digest(f"doc-{doc_id}"), revision,
         publication_date, publication_date, published_at, ingestion_at, parser, ingestion_at,
         "$", supersedes],
    )
    return doc_id


def make_v2_database(path: str | Path, *, seed_eod=False):
    con = duckdb.connect(str(path))
    con.execute((ROOT / "sql/duckdb_schema.sql").read_text(encoding="utf-8"))
    con.execute(
        """INSERT INTO schema_migration
           VALUES ('0001_initial_analytics',0,1,?,CURRENT_TIMESTAMP,'test')""",
        # Fixture represents an already-created v1 database.  Its migration
        # checksum must stay tied to the historical v1 baseline, not the
        # evolving current schema file.
        ["2a00ecaa3505f024092b56a1453ac3ac207c113765efcb71f14568c20c67dbee"],
    )
    v2_bytes = (ROOT / "sql/migrations/0002_ingestion_processing.sql").read_bytes()
    con.execute(v2_bytes.decode("utf-8"))
    con.execute(
        """INSERT INTO schema_migration
           VALUES ('0002_ingestion_processing',1,2,?,CURRENT_TIMESTAMP,'test')""",
        [sha256(v2_bytes).hexdigest()],
    )
    con.execute(
        "UPDATE schema_metadata SET current_version=2,current_migration='0002_ingestion_processing'"
    )
    if seed_eod:
        seed_source(con, "nse-master", "NSE")
        con.execute("INSERT INTO issuer_entity VALUES ('issuer-1', TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute("INSERT INTO equity_security VALUES ('security-1','issuer-1','ordinary',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-nse','security-1','NSE','NSE-1',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute(
            """INSERT INTO normalized_observation_registry
               (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                parser_version,extraction_timestamp,extraction_locator)
               SELECT 'eod-v2','eod_price',source_document_id,source_identifier,checksum_sha256,
                      'parser-1',extraction_timestamp,'row-1'
               FROM source_document_revision WHERE source_document_id='nse-master'"""
        )
        con.execute(
            """INSERT INTO eod_price_observation_revision
               (observation_id,observation_type,security_id,listing_id,exchange,trade_date,
                open_raw,high_raw,low_raw,close_raw,volume_raw,turnover_raw,source_document_id,
                source_identifier,checksum_sha256,parser_version,extraction_timestamp,extraction_locator,quality_status)
               SELECT 'eod-v2','eod_price','security-1','listing-nse','NSE',DATE '2024-01-05',
                      10,12,9,11,100,1100,source_document_id,source_identifier,checksum_sha256,
                      'parser-1',extraction_timestamp,'row-1','observed'
               FROM source_document_revision WHERE source_document_id='nse-master'"""
        )
    return con


class SchemaV3MigrationTests(TestCase):
    def test_v1_to_v6_in_memory_and_v6_reopen_on_disk(self):
        with DuckDBRepository(":memory:") as repo:
            self.assertEqual(repo._connection.execute(
                "SELECT current_version,current_migration FROM schema_metadata"
            ).fetchone(), (repo.SCHEMA_VERSION, repo.CURRENT_MIGRATION))
            migrations = repo._connection.execute(
                "SELECT migration_id,from_version,to_version FROM schema_migration ORDER BY to_version"
            ).fetchall()
            self.assertEqual(migrations, [
                ("0001_initial_analytics", 0, 1),
                ("0002_ingestion_processing", 1, 2),
                (V3, 2, 3),
                (repo.V4_MIGRATION, 3, 4),
                (repo.V5_MIGRATION, 4, 5),
                (repo.CURRENT_MIGRATION, 5, 6),
            ])
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                "('listing_classification_snapshot','listing_classification_review_revision',"
                "'exchange_listing_revision_review','eod_observation_reconciliation')"
            ).fetchone()[0], 4)
            snapshot_columns = {row[1] for row in repo._connection.execute(
                "SELECT * FROM pragma_table_info('listing_classification_snapshot')"
            ).fetchall()}
            self.assertNotIn("universe_disposition", snapshot_columns)
            self.assertNotIn("listing_status", snapshot_columns)
            self.assertEqual(repo._connection.execute(
                "SELECT count(*) FROM duckdb_indexes() WHERE table_name IN "
                "('listing_classification_snapshot','listing_classification_review_revision',"
                "'exchange_listing_revision_review','eod_observation_reconciliation')"
            ).fetchone()[0], 6)
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "hamsa-v3.duckdb"
            with DuckDBRepository(db) as repo:
                self.assertEqual(repo._connection.execute("SELECT current_version FROM schema_metadata").fetchone()[0], repo.SCHEMA_VERSION)
            with DuckDBRepository(db) as reopened:
                self.assertEqual(reopened._connection.execute(
                    "SELECT current_version,current_migration FROM schema_metadata"
                ).fetchone(), (repo.SCHEMA_VERSION, repo.CURRENT_MIGRATION))

    def test_v2_to_v6_preserves_existing_observations(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "preexisting-v2.duckdb"
            con = make_v2_database(db, seed_eod=True)
            before = con.execute("SELECT to_json(eod_price_observation_revision) FROM eod_price_observation_revision WHERE observation_id='eod-v2'").fetchone()
            con.close()
            with DuckDBRepository(db) as repo:
                after = repo._connection.execute(
                    "SELECT to_json(eod_price_observation_revision) FROM eod_price_observation_revision WHERE observation_id='eod-v2'"
                ).fetchone()
                self.assertEqual(after, before)
                self.assertEqual(repo._connection.execute("SELECT current_version FROM schema_metadata").fetchone()[0], repo.SCHEMA_VERSION)

    def test_v3_to_v6_preserves_traceable_legacy_decisions_and_fails_closed_for_incomplete_ones(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "preexisting-v3.duckdb"
            con = make_v2_database(db)
            v3_bytes = (ROOT / "sql/migrations" / f"{V3}.sql").read_bytes()
            con.execute(v3_bytes.decode("utf-8"))
            con.execute(
                "INSERT INTO schema_migration VALUES (?,2,3,?,CURRENT_TIMESTAMP,'test')",
                [V3, sha256(v3_bytes).hexdigest()],
            )
            con.execute("UPDATE schema_metadata SET current_version=3,current_migration=?", [V3])
            seed_source(con, "legacy-identity", "NSE")
            con.execute("INSERT INTO issuer_entity VALUES ('issuer-legacy', CURRENT_TIMESTAMP)")
            con.execute("INSERT INTO equity_security VALUES ('security-legacy','issuer-legacy','ordinary',CURRENT_TIMESTAMP)")
            con.execute(
                "INSERT INTO security_identifier_revision "
                "(identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,source_document_id,"
                "mapping_review_status,reviewed_by,reviewed_at,parser_version,extraction_timestamp,extraction_locator) "
                "VALUES ('legacy-complete','security-legacy','ISIN','INE000A01001',DATE '2020-01-01','legacy-identity',"
                "'approved','operator',TIMESTAMPTZ '2024-01-05 10:00:00+05:30','legacy',"
                "TIMESTAMPTZ '2024-01-05 10:00:00+05:30','row-complete')"
            )
            con.execute(
                "INSERT INTO security_identifier_revision "
                "(identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,source_document_id,"
                "mapping_review_status,parser_version,extraction_timestamp,extraction_locator) "
                "VALUES ('legacy-incomplete','security-legacy','ISIN','INE000A01002',DATE '2020-01-01','legacy-identity',"
                "'approved','legacy',TIMESTAMPTZ '2024-01-05 10:00:00+05:30','row-incomplete')"
            )
            con.execute(
                "INSERT INTO security_identifier_revision "
                "(identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,source_document_id,"
                "mapping_review_status,reviewed_by,reviewed_at,parser_version,extraction_timestamp) "
                "VALUES ('legacy-rejected','security-legacy','ISIN','INE000A01003',DATE '2020-01-01','legacy-identity',"
                "'rejected','operator',TIMESTAMPTZ '2024-01-05 10:00:00+05:30','legacy',"
                "TIMESTAMPTZ '2024-01-05 10:00:00+05:30')"
            )
            con.close()

            with DuckDBRepository(db) as repo:
                self.assertEqual(repo._connection.execute("SELECT current_version FROM schema_metadata").fetchone()[0], 6)
                rows = repo._connection.execute(
                    "SELECT identifier_revision_id,review_status,reviewed_by,CAST(reviewed_at AS VARCHAR) "
                    "FROM security_identifier_revision_review ORDER BY identifier_revision_id"
                ).fetchall()
                self.assertEqual(rows[0][:3], ("legacy-complete", "approved", "operator"))
                self.assertIsNotNone(rows[0][3])
                self.assertEqual(rows[1], ("legacy-incomplete", "pending", None, None))
                self.assertEqual(rows[2][:3], ("legacy-rejected", "rejected", "operator"))

    def test_v3_checksum_mismatch_is_rejected(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "checksum.duckdb"
            with DuckDBRepository(db) as repo:
                repo._connection.execute(
                    "UPDATE schema_migration SET migration_checksum_sha256=? WHERE migration_id=?",
                    ["0" * 64, V3],
                )
            with self.assertRaisesRegex(RepositoryIntegrityError, "checksum"):
                DuckDBRepository(db)

    def test_injected_v3_failure_rolls_back_ddl_and_metadata(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            sql_dir = root / "sql"
            migrations = sql_dir / "migrations"
            migrations.mkdir(parents=True)
            (sql_dir / "duckdb_schema.sql").write_bytes((ROOT / "sql/duckdb_schema.sql").read_bytes())
            (migrations / "0002_ingestion_processing.sql").write_bytes(
                (ROOT / "sql/migrations/0002_ingestion_processing.sql").read_bytes()
            )
            v3 = (ROOT / "sql/migrations" / f"{V3}.sql").read_text(encoding="utf-8")
            (migrations / f"{V3}.sql").write_text(
                v3 + "\nCREATE TABLE v3_failure_probe (value INTEGER CHECK (value > 0));\n"
                "INSERT INTO v3_failure_probe VALUES (-1);\n", encoding="utf-8"
            )
            db = root / "rollback.duckdb"
            with self.assertRaises(duckdb.ConstraintException):
                DuckDBRepository(db, schema_path=sql_dir / "duckdb_schema.sql")
            check = duckdb.connect(str(db), read_only=True)
            try:
                self.assertEqual(check.execute("SELECT current_version,current_migration FROM schema_metadata").fetchone(),
                                 (2, "0002_ingestion_processing"))
                self.assertEqual(check.execute(
                    "SELECT count(*) FROM information_schema.tables WHERE table_name='listing_classification_snapshot'"
                ).fetchone()[0], 0)
                self.assertEqual(check.execute(
                    "SELECT count(*) FROM schema_migration WHERE migration_id=?", [V3]
                ).fetchone()[0], 0)
            finally:
                check.close()


class SchemaV3RepositoryTests(TestCase):
    def make_repo(self):
        repo = DuckDBRepository(":memory:")
        con = repo._connection
        seed_source(con, "nse-evidence", "NSE", published="2024-01-05T10:00:00+05:30", ingested="2024-01-05T11:00:00+05:30")
        seed_source(con, "bse-evidence", "BSE", published="2024-01-05T10:00:00+05:30", ingested="2024-01-05T11:00:00+05:30")
        seed_source(con, "tej-source", "TejHQ", published="2024-01-05T10:00:00+05:30", ingested="2024-01-05T11:00:00+05:30", dataset="nse_eod")
        con.execute("INSERT INTO issuer_entity VALUES ('issuer-1', TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute("INSERT INTO equity_security VALUES ('security-1','issuer-1','ordinary',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-nse','security-1','NSE','NSE-1',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute("INSERT INTO exchange_listing VALUES ('listing-bse','security-1','BSE','BSE-1',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        con.execute(
            """INSERT INTO security_identifier_revision
               (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,effective_to,
                source_document_id,mapping_review_status,reviewed_by,reviewed_at)
               VALUES ('isin-1','security-1','ISIN','INE002A01018',DATE '2020-01-01',NULL,
                       'nse-evidence','approved','reviewer',TIMESTAMPTZ '2024-01-05 10:00:00+05:30')"""
        )
        con.execute(
            """INSERT INTO security_identifier_revision_review
               (review_id,identifier_revision_id,review_status,recorded_at,reviewed_by,reviewed_at,
                evidence_source_document_id,evidence_locator,rationale,supersedes_review_id)
               VALUES ('isin-1-review','isin-1','approved',TIMESTAMPTZ '2024-01-05 10:00:00+05:30',
                       'reviewer',TIMESTAMPTZ '2024-01-05 10:00:00+05:30','nse-evidence','identity-row',NULL,NULL)"""
        )
        con.execute(
            """INSERT INTO exchange_listing_revision
               (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id)
               VALUES ('listing-rev-nse','listing-nse','SBIN','EQ','active',DATE '2020-01-01',NULL,'nse-evidence')"""
        )
        con.execute(
            """INSERT INTO exchange_listing_revision
               (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id)
               VALUES ('listing-rev-bse','listing-bse','500112','A','active',DATE '2020-01-01',NULL,'bse-evidence')"""
        )
        return repo

    def tearDown(self):
        if getattr(self, "repo", None):
            self.repo.close()

    def test_wrong_registry_type_exchange_mismatch_and_check_constraints(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        con.execute(
            """INSERT INTO normalized_observation_registry
               (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                parser_version,extraction_timestamp,extraction_locator)
               SELECT 'wrong-type','financial',source_document_id,source_identifier,checksum_sha256,
                      'parser-1',extraction_timestamp,'row' FROM source_document_revision WHERE source_document_id='nse-evidence'"""
        )
        with self.assertRaises(duckdb.ConstraintException):
            con.execute(
                """INSERT INTO listing_classification_snapshot
                   (listing_classification_snapshot_id,observation_type,listing_id,exchange,source_document_id,
                    source_snapshot_date,source_fields_json,parser_version,extraction_timestamp,extraction_locator)
                   VALUES ('wrong-type','classification','listing-nse','NSE','nse-evidence',DATE '2024-01-05',
                           '{}'::JSON,'parser-1',CURRENT_TIMESTAMP,'row')"""
            )
        with self.assertRaises(duckdb.ConstraintException):
            con.execute(
                """INSERT INTO listing_classification_snapshot
                   (listing_classification_snapshot_id,observation_type,listing_id,exchange,source_document_id,
                    source_snapshot_date,source_fields_json,parser_version,extraction_timestamp,extraction_locator)
                   VALUES ('bad-type-check','financial','listing-nse','NSE','nse-evidence',DATE '2024-01-05',
                           '{}'::JSON,'parser-1',CURRENT_TIMESTAMP,'row')"""
            )
        with self.assertRaises(duckdb.ConstraintException):
            con.execute(
                """INSERT INTO listing_classification_snapshot
                   (listing_classification_snapshot_id,observation_type,listing_id,exchange,source_document_id,
                    source_snapshot_date,source_fields_json,parser_version,extraction_timestamp,extraction_locator)
                   VALUES ('bad-exchange-check','classification','listing-nse','OTC','nse-evidence',DATE '2024-01-05',
                           '{}'::JSON,'parser-1',CURRENT_TIMESTAMP,'row')"""
            )
        with self.assertRaisesRegex(RepositoryIntegrityError, "exchange disagrees"):
            self.repo.append_listing_classification_snapshot({
                "listing_classification_snapshot_id": "bad-exchange", "listing_id": "listing-bse",
                "exchange": "NSE", "source_document_id": "nse-evidence", "source_snapshot_date": date(2024, 1, 5),
            "parser_version": "parser-1", "extraction_locator": "row",
            })
        with self.assertRaises(duckdb.ConstraintException):
            con.execute(
                """INSERT INTO exchange_listing_revision_review
                   (listing_revision_review_id,listing_revision_id,review_status,recorded_by,recorded_at,
                    reviewed_by,reviewed_at,evidence_source_document_id,evidence_locator,rationale)
                   VALUES ('no-evidence','listing-rev-nse','approved','reviewer',CURRENT_TIMESTAMP,
                           'reviewer',CURRENT_TIMESTAMP,NULL,NULL,'missing')"""
            )
        self.assertEqual(con.execute("SELECT count(*) FROM listing_classification_snapshot").fetchone()[0], 0)

    def test_classification_snapshot_and_review_supersession_branching(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        with self.assertRaisesRegex(RepositoryIntegrityError, "unsupported classification snapshot fields"):
            self.repo.append_listing_classification_snapshot({
                "listing_classification_snapshot_id": "backdated-snapshot", "listing_id": "listing-nse",
                "exchange": "NSE", "source_document_id": "nse-evidence", "source_snapshot_date": date(2024, 1, 5),
                "parser_version": "parser-1", "extraction_locator": "row", "extraction_timestamp": datetime(2000, 1, 1, tzinfo=UTC),
            })
        snapshot = {
            "listing_classification_snapshot_id": "snapshot-1", "listing_id": "listing-nse", "exchange": "NSE",
            "source_document_id": "nse-evidence", "source_snapshot_date": date(2024, 1, 5),
            "raw_exchange_instrument_id": "NSE-1", "raw_isin": "INE002A01018", "raw_symbol": "SBIN",
            "raw_series": "EQ", "raw_listing_status": "active", "source_fields_json": {"series": "EQ"},
            "parser_version": "parser-1", "extraction_locator": "row-1",
        }
        self.repo.append_listing_classification_snapshot(snapshot)
        review = {
            "classification_review_revision_id": "class-review-1", "listing_classification_snapshot_id": "snapshot-1",
            "listing_id": "listing-nse", "rationale": "verified", "instrument_review_status": "approved",
            "instrument_class": "ordinary_equity", "instrument_valid_from": date(2020, 1, 1),
            "instrument_evidence_source_document_id": "nse-evidence", "instrument_evidence_locator": "row-1",
            "instrument_reviewed_by": "reviewer", "platform_review_status": "approved", "platform_class": "mainboard",
            "platform_valid_from": date(2020, 1, 1), "platform_evidence_source_document_id": "nse-evidence",
            "platform_evidence_locator": "row-1", "platform_reviewed_by": "reviewer",
        }
        self.repo.append_listing_classification_review_revision(review)
        child = dict(review, classification_review_revision_id="class-review-2",
                     supersedes_review_revision_id="class-review-1", rationale="reviewed again")
        self.repo.append_listing_classification_review_revision(child)
        corrected = dict(child, classification_review_revision_id="class-review-3",
                         supersedes_review_revision_id="class-review-2", platform_valid_from=date(2021, 1, 1),
                         rationale="new evidence-backed interval event")
        self.repo.append_listing_classification_review_revision(corrected)
        branch = dict(review, classification_review_revision_id="class-review-branch",
                      supersedes_review_revision_id="class-review-1", rationale="branch")
        with self.assertRaisesRegex(RepositoryIntegrityError, "successor"):
            self.repo.append_listing_classification_review_revision(branch)
        self.assertEqual(con.execute("SELECT count(*) FROM listing_classification_review_revision").fetchone()[0], 3)
        self.assertEqual(con.execute(
            "SELECT platform_valid_from FROM listing_classification_review_revision WHERE classification_review_revision_id='class-review-1'"
        ).fetchone()[0], date(2020, 1, 1))
        self.assertEqual(con.execute("SELECT count(*) FROM normalized_observation_registry WHERE observation_type='classification'").fetchone()[0], 1)
        seed_source(con, "nse-master-v2", "NSE", dataset="security_master", parser="parser-2")
        self.repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snapshot-2", "listing_id": "listing-nse", "exchange": "NSE",
            "source_document_id": "nse-master-v2", "source_snapshot_date": date(2024, 1, 8),
            "raw_isin": "INE002A01018", "parser_version": "parser-2", "extraction_locator": "row-1",
            "supersedes_snapshot_id": "snapshot-1",
        })
        self.assertEqual(con.execute(
            "SELECT supersedes_snapshot_id FROM listing_classification_snapshot WHERE listing_classification_snapshot_id='snapshot-2'"
        ).fetchone()[0], "snapshot-1")

    def test_listing_revision_review_requires_exchange_matched_evidence_and_is_append_only(self):
        self.repo = self.make_repo()
        with self.assertRaisesRegex(RepositoryIntegrityError, "evidence locator"):
            self.repo.append_exchange_listing_revision_review({
                "listing_revision_review_id": "missing", "listing_revision_id": "listing-rev-nse",
                "review_status": "approved", "reviewed_by": "reviewer", "rationale": "no evidence",
            })
        with self.assertRaisesRegex(RepositoryIntegrityError, "provider"):
            self.repo.append_exchange_listing_revision_review({
                "listing_revision_review_id": "wrong-provider", "listing_revision_id": "listing-rev-nse",
                "review_status": "approved", "reviewed_by": "reviewer", "evidence_source_document_id": "bse-evidence",
                "evidence_locator": "row-1", "rationale": "wrong venue",
            })
        self.repo.append_exchange_listing_revision_review({
            "listing_revision_review_id": "listing-review-1", "listing_revision_id": "listing-rev-nse",
            "review_status": "approved", "reviewed_by": "reviewer", "evidence_source_document_id": "nse-evidence",
            "evidence_locator": "listing-row-1", "rationale": "effective listing confirmed",
        })
        self.repo.append_exchange_listing_revision_review({
            "listing_revision_review_id": "listing-review-2", "listing_revision_id": "listing-rev-nse",
            "review_status": "approved", "reviewed_by": "reviewer", "evidence_source_document_id": "nse-evidence",
            "evidence_locator": "listing-row-1", "rationale": "review reaffirmed",
            "supersedes_review_id": "listing-review-1",
        })
        with self.assertRaisesRegex(RepositoryIntegrityError, "same listing revision"):
            self.repo.append_exchange_listing_revision_review({
                "listing_revision_review_id": "listing-review-wrong-target", "listing_revision_id": "listing-rev-bse",
                "review_status": "approved", "reviewed_by": "reviewer", "evidence_source_document_id": "bse-evidence",
                "evidence_locator": "listing-row-1", "rationale": "invalid chain", "supersedes_review_id": "listing-review-1",
            })
        con = self.repo._connection
        self.assertEqual(con.execute("SELECT count(*) FROM exchange_listing_revision_review").fetchone()[0], 2)

    def test_review_and_reconciliation_check_constraints_reject_invalid_shapes(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        self.repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snapshot-checks", "listing_id": "listing-nse", "exchange": "NSE",
            "source_document_id": "nse-evidence", "source_snapshot_date": date(2024, 1, 5),
            "parser_version": "parser-1", "extraction_locator": "row-checks",
        })
        # Exercise both duplicated dimension CHECK sets: status enum, approved
        # evidence/reviewer requirements, interval order, and pending purity.
        for dim in ("instrument", "platform"):
            status_col = f"{dim}_review_status"
            class_col = f"{dim}_class"
            start_col = f"{dim}_valid_from"
            end_col = f"{dim}_valid_to"
            evidence_col = f"{dim}_evidence_source_document_id"
            locator_col = f"{dim}_evidence_locator"
            reviewer_col = f"{dim}_reviewed_by"
            reviewed_at_col = f"{dim}_reviewed_at"
            for suffix, values in (
                ("bad-status", ("bogus", None, None, None, None, None, None, None)),
                ("missing-evidence", ("approved", "ordinary_equity" if dim == "instrument" else "mainboard",
                    date(2024, 1, 1), None, None, None, "reviewer", datetime.now(IST))),
                ("missing-interval", ("approved", "ordinary_equity" if dim == "instrument" else "mainboard",
                    None, None, "nse-evidence", "row", "reviewer", datetime.now(IST))),
                ("missing-reviewer", ("approved", "ordinary_equity" if dim == "instrument" else "mainboard",
                    date(2024, 1, 1), None, "nse-evidence", "row", None, None)),
                ("bad-class", ("approved", "not-a-class", date(2024, 1, 1), None,
                    "nse-evidence", "row", "reviewer", datetime.now(IST))),
                ("reversed-interval", ("approved", "ordinary_equity" if dim == "instrument" else "mainboard",
                    date(2024, 1, 8), date(2024, 1, 5), "nse-evidence", "row", "reviewer", datetime.now(IST))),
                ("dirty-pending", ("pending", None, None, None, None, None, "reviewer", datetime.now(IST))),
                ("rejected-no-reviewer", ("rejected", None, None, None, None, None, None, None)),
            ):
                other = "platform" if dim == "instrument" else "instrument"
                columns = [
                    "classification_review_revision_id", "listing_classification_snapshot_id", "listing_id",
                    "recorded_by", "recorded_at", "rationale", status_col, class_col, start_col, end_col,
                    evidence_col, locator_col, reviewer_col, reviewed_at_col,
                    f"{other}_review_status", f"{other}_class", f"{other}_valid_from", f"{other}_valid_to",
                    f"{other}_evidence_source_document_id", f"{other}_evidence_locator",
                    f"{other}_reviewed_by", f"{other}_reviewed_at", "supersedes_review_revision_id",
                ]
                row = [f"{dim}-{suffix}", "snapshot-checks", "listing-nse", "reviewer", datetime.now(IST), suffix,
                       *values, "pending", None, None, None, None, None, None, None, None]
                statement = f"INSERT INTO listing_classification_review_revision ({','.join(columns)}) VALUES ({','.join('?' for _ in row)})"
                with self.assertRaises(duckdb.ConstraintException, msg=f"{dim} {suffix}"):
                    con.execute(statement, row)

        for review_id, status, reviewed_by, reviewed_at, evidence, locator in (
            ("listing-bad-status", "bogus", None, None, None, None),
            ("listing-pending-with-evidence", "pending", None, None, "nse-evidence", "row"),
            ("listing-rejected-no-reviewer", "rejected", None, None, None, None),
            ("listing-approved-no-evidence", "approved", "reviewer", datetime.now(IST), None, None),
        ):
            with self.assertRaises(duckdb.ConstraintException, msg=review_id):
                con.execute(
                    """INSERT INTO exchange_listing_revision_review
                       (listing_revision_review_id,listing_revision_id,review_status,recorded_by,recorded_at,
                        reviewed_by,reviewed_at,evidence_source_document_id,evidence_locator,rationale)
                       VALUES (?,?,?,'reviewer',CURRENT_TIMESTAMP,?,?,?,?, 'bad-shape')""",
                    [review_id, "listing-rev-nse", status, reviewed_by, reviewed_at, evidence, locator],
                )

        seed_source(con, "nse-eod-check", "NSE", dataset="eod")
        seed_source(con, "tej-eod-check", "TejHQ", dataset="nse_eod")
        self.add_eod("official-check", provider="NSE", doc_id="nse-eod-check", values=(10, 12, 9, 11, 100, 1100))
        self.add_eod("secondary-check", provider="TejHQ", doc_id="tej-eod-check", values=(10, 12, 9, 11, 100, 1100))
        invalid_reconciliations = (
            ("bad-status", "wrong", "not_compared", "official-check", None, None, None, "no_counterpart"),
            ("matched-one-side", "matched", "exact_match", "official-check", None, "{}", "{}", None),
            ("unmatched-two-sides", "unmatched_official", "not_compared", "official-check", "secondary-check", None, None, "no_counterpart"),
            ("unknown-outcome", "matched", "unknown", "official-check", "secondary-check", "{}", "{}", None),
            ("exact-no-payload", "matched", "exact_match", "official-check", "secondary-check", None, None, None),
            ("exact-unmatched", "unmatched_official", "exact_match", "official-check", None, "{}", "{}", None),
            ("discrepancy-unmatched", "unmatched_official", "discrepancy", "official-check", None, "{}", "{}", None),
            ("discrepancy-no-payload", "matched", "discrepancy", "official-check", "secondary-check", None, None, None),
            ("not-compared-with-payload", "matched", "not_compared", "official-check", "secondary-check", "{}", None, "missing_comparable_value"),
        )
        for suffix, match, outcome, official, secondary, compared, differences, reason in invalid_reconciliations:
            with self.assertRaises(duckdb.ConstraintException, msg=suffix):
                con.execute(
                    """INSERT INTO eod_observation_reconciliation
                       (reconciliation_id,comparison_stream_id,comparator_version,official_observation_id,
                        secondary_observation_id,match_status,comparison_outcome,compared_fields_json,
                        differences_json,not_compared_reason_code,compared_at)
                       VALUES (?,?,'eod-raw-ohlcv-turnover-v1',?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
                    [f"invalid-{suffix}", f"stream-{suffix}", official, secondary, match, outcome,
                     compared, differences, reason],
                )

    def add_eod(self, observation_id, *, provider, doc_id, values, parser="parser-1", listing="listing-nse",
                exchange="NSE", trade_date=date(2024, 1, 5), supersedes=None, quality_status="observed"):
        con = self.repo._connection
        source = con.execute("SELECT source_identifier,checksum_sha256,CAST(extraction_timestamp AS VARCHAR) FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone()
        con.execute(
            """INSERT INTO normalized_observation_registry
               (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                parser_version,extraction_timestamp,extraction_locator)
               VALUES (?,'eod_price',?,?,?,?,?,?)""",
            [observation_id, doc_id, source[0], source[1], parser, source[2], observation_id],
        )
        con.execute(
            """INSERT INTO eod_price_observation_revision
               (observation_id,observation_type,security_id,listing_id,exchange,trade_date,open_raw,high_raw,low_raw,
                close_raw,volume_raw,turnover_raw,source_document_id,source_identifier,checksum_sha256,parser_version,
                extraction_timestamp,extraction_locator,quality_status,supersedes_observation_id)
               VALUES (?,'eod_price','security-1',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, ?,?)""",
            [observation_id, listing, exchange, trade_date, *values, doc_id, source[0], source[1], parser,
             source[2], observation_id, quality_status, supersedes],
        )

    @staticmethod
    def stream(listing="listing-nse", exchange="NSE", trade_date=date(2024, 1, 5)):
        return DuckDBRepository.eod_reconciliation_stream_id(exchange, listing, trade_date)

    def test_reconciliation_exact_discrepancy_not_compared_and_unmatched(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        seed_source(con, "nse-eod", "NSE", dataset="eod")
        seed_source(con, "tej-eod", "TejHQ", dataset="nse_eod")
        equal = (10, 12, 9, 11, 100, 1100)
        self.add_eod("official-exact", provider="NSE", doc_id="nse-eod", values=equal)
        self.add_eod("secondary-exact", provider="TejHQ", doc_id="tej-eod", values=equal)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-exact", comparison_stream_id=self.stream(), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-exact", secondary_observation_id="secondary-exact",
        ), ("rec-exact", "exact_match"))
        exact = con.execute("SELECT compared_fields_json::VARCHAR,differences_json::VARCHAR FROM eod_observation_reconciliation WHERE reconciliation_id='rec-exact'").fetchone()
        self.assertIn('"close_raw"', exact[0])
        self.assertEqual(exact[1], "{}")
        self.add_eod("secondary-bse", provider="TejHQ", doc_id="tej-eod", values=equal,
                     listing="listing-bse", exchange="BSE")
        with self.assertRaisesRegex(RepositoryIntegrityError, "match exchange, listing"):
            self.repo.append_eod_observation_reconciliation(
                reconciliation_id="rec-wrong-venue", comparison_stream_id=self.stream(),
                comparator_version=COMPARATOR, match_status="matched", official_observation_id="official-exact",
                secondary_observation_id="secondary-bse",
            )

        discrepancy = (10, 12, 9, 12, 101, 1100)
        day_diff = date(2024, 1, 8)
        self.add_eod("official-diff", provider="NSE", doc_id="nse-eod", values=equal, trade_date=day_diff)
        self.add_eod("secondary-diff", provider="TejHQ", doc_id="tej-eod", values=discrepancy, trade_date=day_diff)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-diff", comparison_stream_id=self.stream(trade_date=day_diff), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-diff", secondary_observation_id="secondary-diff",
        )[1], "discrepancy")
        diff_json = con.execute("SELECT differences_json::VARCHAR FROM eod_observation_reconciliation WHERE reconciliation_id='rec-diff'").fetchone()[0]
        self.assertIn('"official":"11.0000000000"', diff_json)
        self.assertIn('"delta":"1.0000000000"', diff_json)

        missing = (10, 12, 9, 11, None, 1100)
        day_missing = date(2024, 1, 9)
        self.add_eod("official-missing", provider="NSE", doc_id="nse-eod", values=missing, trade_date=day_missing)
        self.add_eod("secondary-missing", provider="TejHQ", doc_id="tej-eod", values=equal, trade_date=day_missing)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-not-compared", comparison_stream_id=self.stream(trade_date=day_missing), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-missing", secondary_observation_id="secondary-missing",
        )[1], "not_compared")
        null_payloads = con.execute("SELECT compared_fields_json,differences_json,not_compared_reason_code FROM eod_observation_reconciliation WHERE reconciliation_id='rec-not-compared'").fetchone()
        self.assertEqual(null_payloads, (None, None, "missing_comparable_value"))

        day_invalid = date(2024, 1, 10)
        self.add_eod("official-invalid", provider="NSE", doc_id="nse-eod", values=equal, quality_status="invalid", trade_date=day_invalid)
        self.add_eod("secondary-valid", provider="TejHQ", doc_id="tej-eod", values=equal, trade_date=day_invalid)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-invalid", comparison_stream_id=self.stream(trade_date=day_invalid), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-invalid", secondary_observation_id="secondary-valid",
        )[1], "not_compared")
        self.assertEqual(con.execute(
            "SELECT not_compared_reason_code FROM eod_observation_reconciliation WHERE reconciliation_id='rec-invalid'"
        ).fetchone()[0], "invalid_source_value")

        day_only_official = date(2024, 1, 11)
        self.add_eod("only-official", provider="NSE", doc_id="nse-eod", values=equal, trade_date=day_only_official)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-unmatched-o", comparison_stream_id=self.stream(trade_date=day_only_official), comparator_version=COMPARATOR,
            match_status="unmatched_official", official_observation_id="only-official", not_compared_reason_code="no_counterpart",
        )[1], "not_compared")
        day_only_secondary = date(2024, 1, 12)
        self.add_eod("only-secondary", provider="TejHQ", doc_id="tej-eod", values=equal, trade_date=day_only_secondary)
        self.assertEqual(self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-unmatched-s", comparison_stream_id=self.stream(trade_date=day_only_secondary), comparator_version=COMPARATOR,
            match_status="unmatched_secondary", secondary_observation_id="only-secondary", not_compared_reason_code="no_counterpart",
        )[1], "not_compared")
        with self.assertRaisesRegex(RepositoryIntegrityError, "supersede the active"):
            self.repo.append_eod_observation_reconciliation(
                reconciliation_id="rec-unmatched-o-duplicate", comparison_stream_id=self.stream(trade_date=day_only_official),
                comparator_version=COMPARATOR, match_status="unmatched_official", official_observation_id="only-official",
                not_compared_reason_code="no_counterpart",
            )
        self.assertEqual(con.execute("SELECT count(*) FROM eod_observation_reconciliation").fetchone()[0], 6)

        with self.assertRaisesRegex(RepositoryIntegrityError, "comparison stream does not match"):
            self.repo.append_eod_observation_reconciliation(
                reconciliation_id="rec-reused-stream", comparison_stream_id=self.stream(),
                comparator_version=COMPARATOR, match_status="unmatched_official", official_observation_id="only-official",
                not_compared_reason_code="no_counterpart",
            )

    def test_source_and_parser_revisions_are_preserved_and_reconciliation_supersedes(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        seed_source(con, "nse-eod-r1", "NSE", dataset="eod", revision=1)
        seed_source(con, "tej-eod-r1", "TejHQ", dataset="nse_eod", revision=1)
        seed_source(con, "nse-eod-r2", "NSE", dataset="eod", revision=2, supersedes="nse-eod-r1")
        vals = (10, 12, 9, 11, 100, 1100)
        session = date(2024, 1, 5)
        self.add_eod("official-r1", provider="NSE", doc_id="nse-eod-r1", values=vals)
        self.add_eod("secondary-parser-v1", provider="TejHQ", doc_id="tej-eod-r1", values=vals, parser="parser-1")
        self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-v1", comparison_stream_id=self.stream(trade_date=session), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-r1", secondary_observation_id="secondary-parser-v1",
        )
        self.add_eod("secondary-parser-v2", provider="TejHQ", doc_id="tej-eod-r1", values=vals, parser="parser-2", supersedes="secondary-parser-v1")
        self.add_eod("official-r2", provider="NSE", doc_id="nse-eod-r2", values=(10, 12, 9, 12, 100, 1200), supersedes="official-r1")
        _, outcome = self.repo.append_eod_observation_reconciliation(
            reconciliation_id="rec-v2", comparison_stream_id=self.stream(trade_date=session), comparator_version=COMPARATOR,
            match_status="matched", official_observation_id="official-r2", secondary_observation_id="secondary-parser-v2",
            supersedes_reconciliation_id="rec-v1",
        )
        self.assertEqual(outcome, "discrepancy")
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE source_document_id='tej-eod-r1'").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT count(*) FROM eod_observation_reconciliation WHERE comparison_stream_id=?", [self.stream(trade_date=session)]).fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT supersedes_reconciliation_id FROM eod_observation_reconciliation WHERE reconciliation_id='rec-v2'").fetchone()[0], "rec-v1")

    def test_point_in_time_modes_do_not_use_trade_date_or_snapshot_status_as_listing_status(self):
        # The status decision comes from the approved effective listing revision;
        # source snapshot status is never consulted by derive_universe_disposition.
        self.repo = self.make_repo()
        con = self.repo._connection
        today = datetime.now(IST).date() + timedelta(days=1)
        cutoff = datetime.combine(today, time(15, 30), tzinfo=IST)
        # Directly seed an observed session and historical facts with timestamps
        # representing their recorded availability; the production repository
        # API supplies review timestamps itself and cannot backdate them.
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',? ,TRUE,'regular','cal-v1','nse-evidence')", [today])
        self.repo.append_exchange_listing_revision_review({
            "listing_revision_review_id": "listing-review-current", "listing_revision_id": "listing-rev-nse",
            "review_status": "approved", "reviewed_by": "reviewer", "evidence_source_document_id": "nse-evidence",
            "evidence_locator": "listing-row", "rationale": "effective interval verified",
        })
        snap_doc = seed_source(con, "snapshot-current", "NSE", dataset="security_master")
        evidence = seed_source(con, "class-evidence-current", "NSE", dataset="circular")
        self.repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snapshot-current", "listing_id": "listing-nse", "exchange": "NSE",
            "source_document_id": snap_doc, "source_snapshot_date": today, "raw_isin": "INE002A01018",
            "raw_symbol": "SBIN", "raw_series": "EQ", "raw_listing_status": "suspended",
            "parser_version": "parser-1", "extraction_locator": "row-1",
        })
        self.repo.append_listing_classification_review_revision({
            "classification_review_revision_id": "class-current", "listing_classification_snapshot_id": "snapshot-current",
            "listing_id": "listing-nse", "rationale": "instrument and platform confirmed",
            "instrument_review_status": "approved", "instrument_class": "ordinary_equity", "instrument_valid_from": today,
            "instrument_evidence_source_document_id": evidence, "instrument_evidence_locator": "notice#1", "instrument_reviewed_by": "reviewer",
            "platform_review_status": "approved", "platform_class": "mainboard", "platform_valid_from": today,
            "platform_evidence_source_document_id": evidence, "platform_evidence_locator": "notice#1", "platform_reviewed_by": "reviewer",
        })
        # Reviews and extraction timestamps are system-recorded. A separate
        # late backfill below distinguishes public availability from HAMSA knowledge.
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=cutoff.date(), cutoff=cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ), "eligible_mainboard_ordinary_equity")
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=cutoff.date(), cutoff=cutoff,
            availability_mode="hamsa_known_as_of", calendar_version="cal-v1",
        ), "eligible_mainboard_ordinary_equity")
        backfill_doc = seed_source(
            con, "late-backfill", "NSE", dataset="security_master",
            published=(cutoff - timedelta(days=1)).isoformat(), ingested=(cutoff + timedelta(days=1)).isoformat(),
        )
        self.assertTrue(self.repo._source_available(
            backfill_doc, exchange="NSE", screen_date=cutoff.date(), cutoff=cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ))
        self.assertFalse(self.repo._source_available(
            backfill_doc, exchange="NSE", screen_date=cutoff.date(), cutoff=cutoff,
            availability_mode="hamsa_known_as_of", calendar_version="cal-v1",
        ))
        conflict_doc = seed_source(con, "snapshot-conflict", "NSE", dataset="security_master")
        conflict_evidence = seed_source(con, "conflict-evidence", "NSE", dataset="circular")
        self.repo.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": "snapshot-conflict", "listing_id": "listing-nse", "exchange": "NSE",
            "source_document_id": conflict_doc, "source_snapshot_date": cutoff.date(), "raw_isin": "INE002A01018",
            "raw_listing_status": "active", "parser_version": "parser-1", "extraction_locator": "row-conflict",
        })
        self.repo.append_listing_classification_review_revision({
            "classification_review_revision_id": "class-conflict", "listing_classification_snapshot_id": "snapshot-conflict",
            "listing_id": "listing-nse", "rationale": "deliberate cross-snapshot conflicting platform evidence",
            "platform_review_status": "approved", "platform_class": "sme", "platform_valid_from": cutoff.date(),
            "platform_evidence_source_document_id": conflict_evidence, "platform_evidence_locator": "notice#2",
            "platform_reviewed_by": "reviewer",
        })
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=cutoff.date(), cutoff=cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ), "unresolved_classification")
        con.execute("UPDATE exchange_listing_revision SET status='suspended' WHERE listing_revision_id='listing-rev-nse'")
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=cutoff.date(), cutoff=cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ), "excluded_inactive_non_trading")

    def test_date_only_classification_source_uses_next_exchange_session(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        doc = seed_source(con, "date-only-source", "NSE", published=None, ingested="2024-01-05T11:00:00+05:30")
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',DATE '2024-01-05',TRUE,'regular','date-cal','nse-evidence')")
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',DATE '2024-01-08',TRUE,'regular','date-cal','nse-evidence')")
        self.assertFalse(self.repo._source_available(
            doc, exchange="NSE", screen_date=date(2024, 1, 5),
            cutoff=datetime(2024, 1, 5, 15, 30, tzinfo=IST), availability_mode="public_as_of",
            calendar_version="date-cal",
        ))
        self.assertTrue(self.repo._source_available(
            doc, exchange="NSE", screen_date=date(2024, 1, 8),
            cutoff=datetime(2024, 1, 8, 15, 30, tzinfo=IST), availability_mode="hamsa_known_as_of",
            calendar_version="date-cal",
        ))

    def test_sme_to_mainboard_requires_independently_published_migration_date(self):
        self.repo = self.make_repo()
        con = self.repo._connection
        before = date(2024, 1, 5)
        migration_date = date(2024, 1, 8)
        before_cutoff = datetime(2024, 1, 5, 15, 30, tzinfo=IST)
        migration_cutoff = datetime(2024, 1, 8, 15, 30, tzinfo=IST)
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',?,TRUE,'regular','cal-v1','nse-evidence')", [before])
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',?,TRUE,'regular','cal-v1','nse-evidence')", [migration_date])
        migration_doc = seed_source(
            con, "migration-notice", "NSE", dataset="listing_circular",
            published="2024-01-05T12:00:00+05:30", ingested="2024-01-05T12:30:00+05:30",
        )
        # Both master rows report current active status. That fact does not set M.
        for sid, snapshot_date, extraction in (
            ("sme-snapshot", before, datetime(2024, 1, 5, 11, 15, tzinfo=IST)),
            ("mainboard-snapshot", migration_date, datetime(2024, 1, 5, 12, 35, tzinfo=IST)),
        ):
            self.repo.append_listing_classification_snapshot({
                "listing_classification_snapshot_id": sid, "listing_id": "listing-nse", "exchange": "NSE",
                "source_document_id": "nse-evidence", "source_snapshot_date": snapshot_date,
                "raw_isin": "INE002A01018", "raw_symbol": "SBIN", "raw_series": "EQ",
                "raw_listing_status": "active", "parser_version": "parser-1", "extraction_locator": sid,
            })
        con.execute(
            """INSERT INTO exchange_listing_revision_review
               (listing_revision_review_id,listing_revision_id,review_status,recorded_by,recorded_at,
                reviewed_by,reviewed_at,evidence_source_document_id,evidence_locator,rationale)
               VALUES ('historical-listing-review','listing-rev-nse','approved','reviewer',TIMESTAMPTZ '2024-01-05 11:20:00+05:30',
                       'reviewer',TIMESTAMPTZ '2024-01-05 11:20:00+05:30','nse-evidence','listing-row','historical status evidence')"""
        )
        con.execute(
            """INSERT INTO listing_classification_review_revision VALUES
               ('sme-review','sme-snapshot','listing-nse','reviewer',TIMESTAMPTZ '2024-01-05 12:00:00+05:30','verified before migration',
                'approved','ordinary_equity',DATE '2020-01-01',NULL,'nse-evidence','master-row','reviewer',TIMESTAMPTZ '2024-01-05 12:00:00+05:30',
                'approved','sme',DATE '2020-01-01',DATE '2024-01-07','nse-evidence','master-row','reviewer',TIMESTAMPTZ '2024-01-05 12:00:00+05:30',NULL)"""
        )
        con.execute(
            """INSERT INTO listing_classification_review_revision VALUES
               ('mainboard-review','mainboard-snapshot','listing-nse','reviewer',TIMESTAMPTZ '2024-01-05 12:45:00+05:30','independent migration notice supports M',
                'pending',NULL,NULL,NULL,NULL,NULL,NULL,NULL,
                'approved','mainboard',DATE '2024-01-08',NULL,?,'notice-page-2','reviewer',TIMESTAMPTZ '2024-01-05 12:45:00+05:30',NULL)""",
            [migration_doc],
        )
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=before, cutoff=before_cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ), "excluded_sme")
        self.assertEqual(self.repo.derive_universe_disposition(
            listing_id="listing-nse", observation_date=migration_date, cutoff=migration_cutoff,
            availability_mode="public_as_of", calendar_version="cal-v1",
        ), "eligible_mainboard_ordinary_equity")
