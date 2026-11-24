"""Portable synthetic tests for the local TejHQ Parquet importer."""

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

import duckdb

from hamsa.ingestion.tejhq_parquet import TejHQParquetImporter, TejHQPartition
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
TRADE_DAY = date(2026, 11, 9)
PUBLIC_DAY = date(2026, 11, 6)


def seed_source(con, doc_id: str, provider: str, *, dataset: str, published_at=None, publication_date=date(2020, 1, 2)):
    checksum = sha256(doc_id.encode()).hexdigest()
    captured = datetime(2020, 1, 2, 10, tzinfo=IST)
    con.execute(
        """INSERT INTO raw_source_file
           (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
            source_as_of_date,license_review_reference,license_status,metadata_json)
           VALUES (?,?,?,?,?,?,?,?,?,'approved','{}'::JSON)""",
        [f"raw-{doc_id}", provider, dataset, f"{doc_id}.csv", checksum, f"archive/{doc_id}", captured,
         publication_date, "synthetic-test"],
    )
    con.execute(
        """INSERT INTO source_document_revision
           (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,revision_number,
            source_document_date,publication_date,published_at,ingestion_timestamp,parser_version,
            extraction_timestamp,extraction_locator)
           VALUES (?,?,?,?,?,?,1,?,?,?,?, 'fixture-v1',?,'fixture')""",
        [doc_id, provider, dataset, doc_id, f"raw-{doc_id}", checksum, publication_date, publication_date,
         published_at, datetime(2020, 1, 2, 11, tzinfo=IST), datetime(2020, 1, 2, 11, tzinfo=IST)],
    )


def write_parquet(path: Path, rows):
    con = duckdb.connect(":memory:")
    try:
        con.execute("""CREATE TABLE fixture AS SELECT
           CAST(NULL AS DATE) date, CAST(NULL AS VARCHAR) symbol, CAST(NULL AS VARCHAR) series,
           CAST(NULL AS VARCHAR) isin, CAST(NULL AS DOUBLE) open, CAST(NULL AS DOUBLE) high,
           CAST(NULL AS DOUBLE) low, CAST(NULL AS DOUBLE) close, CAST(NULL AS BIGINT) volume,
           CAST(NULL AS DOUBLE) turnover WHERE FALSE""")
        for row in rows:
            con.execute("INSERT INTO fixture VALUES (?,?,?,?,?,?,?,?,?,?)", row)
        con.execute('COPY (SELECT *, year(date)::INTEGER AS "year", month(date)::TINYINT AS "month" FROM fixture) TO ? (FORMAT PARQUET)', [str(path)])
    finally:
        con.close()


class TejHQImporterTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = DuckDBRepository(":memory:")
        self.source_path = self.root / "nse.parquet"
        self.rows = [
            (TRADE_DAY, "SBIN", "EQ", "INE062A01020", 10.0, 12.0, 9.0, 11.0, 100, 1100.0),
        ]
        write_parquet(self.source_path, self.rows)

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def partition(self, *, path=None, exchange="NSE", parser="tejhq-parquet-v1", revision="abcdef1", dataset_path=None):
        return TejHQPartition(
            path=path or self.source_path, exchange=exchange, dataset_id="tejhq/indian-markets",
            dataset_revision=revision, original_dataset_path=dataset_path or f"{exchange.lower()}/year=2026/sample.parquet",
            source_document_date=PUBLIC_DAY, first_verified_public_date=PUBLIC_DAY, retrieval_date=PUBLIC_DAY,
            parser_version=parser,
        )

    def add_mapping(self, *, exchange="NSE", security="security-sbi", listing="listing-sbi",
                    isin="INE062A01020", instrument_class="ordinary_equity", platform_class="mainboard"):
        con = self.repo._connection
        evidence = f"{exchange.lower()}-evidence"
        seed_source(con, evidence, exchange, dataset="official_master")
        if con.execute("SELECT 1 FROM issuer_entity WHERE entity_id='issuer-sbi'").fetchone() is None:
            con.execute("INSERT INTO issuer_entity VALUES ('issuer-sbi',TIMESTAMPTZ '2020-01-01 00:00:00+00')")
        if con.execute("SELECT 1 FROM equity_security WHERE security_id=?", [security]).fetchone() is None:
            con.execute("INSERT INTO equity_security VALUES (?, 'issuer-sbi','ordinary',TIMESTAMPTZ '2020-01-01 00:00:00+00')", [security])
        if con.execute("SELECT 1 FROM exchange_listing WHERE listing_id=?", [listing]).fetchone() is None:
            con.execute("INSERT INTO exchange_listing VALUES (?,?,?, ?,TIMESTAMPTZ '2020-01-01 00:00:00+00')", [listing, security, exchange, f"{exchange}-instrument"])
        if con.execute("SELECT 1 FROM security_identifier_revision WHERE security_id=?", [security]).fetchone() is None:
            con.execute(
                """INSERT INTO security_identifier_revision
                   (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,effective_to,
                    source_document_id,mapping_review_status,reviewed_by,reviewed_at)
                   VALUES (?,?, 'ISIN', ?, DATE '2020-01-01',NULL,?,'approved','reviewer',TIMESTAMPTZ '2020-01-02 12:00:00+05:30')""",
                [f"isin-{security}", security, isin, evidence],
            )
        identity_review_id = f"isin-review-{security}"
        if con.execute("SELECT 1 FROM security_identifier_revision_review WHERE review_id=?", [identity_review_id]).fetchone() is None:
            con.execute(
                """INSERT INTO security_identifier_revision_review
                   (review_id,identifier_revision_id,review_status,recorded_at,reviewed_by,reviewed_at,
                    evidence_source_document_id,evidence_locator,rationale,supersedes_review_id)
                   VALUES (?,?,'approved',TIMESTAMPTZ '2020-01-02 12:00:00+05:30','reviewer',
                           TIMESTAMPTZ '2020-01-02 12:00:00+05:30',?,'synthetic-fixture:identity',NULL,NULL)""",
                [identity_review_id, f"isin-{security}", evidence],
            )
        revision_id = f"listing-revision-{listing}"
        if con.execute("SELECT 1 FROM exchange_listing_revision WHERE listing_revision_id=?", [revision_id]).fetchone() is None:
            con.execute(
                """INSERT INTO exchange_listing_revision
                   (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id)
                   VALUES (?,?, 'SBIN','EQ','active',DATE '2020-01-01',NULL,?)""", [revision_id, listing, evidence]
            )
            self.repo.append_exchange_listing_revision_review({
                "listing_revision_review_id": f"listing-review-{listing}", "listing_revision_id": revision_id,
                "review_status": "approved", "reviewed_by": "test-reviewer", "evidence_source_document_id": evidence,
                "evidence_locator": "synthetic-fixture:listing", "rationale": "synthetic test fixture",
            })
        snapshot_id = f"snapshot-{listing}"
        if con.execute("SELECT 1 FROM listing_classification_snapshot WHERE listing_classification_snapshot_id=?", [snapshot_id]).fetchone() is None:
            self.repo.append_listing_classification_snapshot({
                "listing_classification_snapshot_id": snapshot_id, "listing_id": listing, "exchange": exchange,
                "source_document_id": evidence, "source_snapshot_date": date(2020, 1, 2), "raw_isin": isin,
                "raw_symbol": "SBIN", "raw_series": "EQ", "parser_version": "fixture-v1",
                "extraction_locator": "synthetic-fixture:classification",
            })
            self.repo.append_listing_classification_review_revision({
                "classification_review_revision_id": f"class-review-{listing}",
                "listing_classification_snapshot_id": snapshot_id, "listing_id": listing,
                "rationale": "synthetic test fixture only",
                "instrument_review_status": "approved", "instrument_class": instrument_class,
                "instrument_valid_from": date(2020, 1, 1), "instrument_evidence_source_document_id": evidence,
                "instrument_evidence_locator": "synthetic-fixture:instrument", "instrument_reviewed_by": "test-reviewer",
                "platform_review_status": "approved", "platform_class": platform_class,
                "platform_valid_from": date(2020, 1, 1), "platform_evidence_source_document_id": evidence,
                "platform_evidence_locator": "synthetic-fixture:platform", "platform_reviewed_by": "test-reviewer",
            })
        return security, listing

    def add_official(self, *, exchange="NSE", listing="listing-sbi", security="security-sbi", values=None):
        con = self.repo._connection
        doc_id = f"{exchange.lower()}-official-eod"
        if con.execute("SELECT 1 FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone() is None:
            seed_source(con, doc_id, exchange, dataset="official_eod")
        source = con.execute("SELECT source_identifier,checksum_sha256,CAST(ingestion_timestamp AS VARCHAR) FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone()
        process_id = f"process-{doc_id}"
        if con.execute("SELECT 1 FROM source_document_processing_revision WHERE processing_revision_id=?", [process_id]).fetchone() is None:
            con.execute(
                """INSERT INTO source_document_processing_revision
                   (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,
                    status,accepted_count,rejected_count,quarantined_count)
                   VALUES (?,?, 'official-fixture-v1',1,CURRENT_TIMESTAMP,'started',0,0,0)""", [process_id, doc_id]
            )
        o, h, l, c, v, t = values or (10, 12, 9, 11, 100, 1100)
        self.repo.append_eod_price_observation({
            "observation_id": f"official-{exchange}-sample", "security_id": security, "listing_id": listing,
            "exchange": exchange, "trade_date": TRADE_DAY, "open_raw": o, "high_raw": h, "low_raw": l,
            "close_raw": c, "volume_raw": v, "turnover_raw": t, "source_document_id": doc_id,
            "source_identifier": source[0], "checksum_sha256": source[1], "parser_version": "official-fixture-v1",
            "extraction_timestamp": datetime.now(timezone.utc), "extraction_locator": "synthetic-official-row",
            "quality_status": "observed", "extraction_revision_id": process_id,
        })

    def ingest(self, *, partition=None, symbols=("SBIN",), trade_date=TRADE_DAY, **kwargs):
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive", **kwargs) as importer:
            return importer.ingest_pilot(partition or self.partition(), trade_date=trade_date, symbols=symbols)

    def test_portable_parquet_parse_and_required_source_fields(self):
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            schema, rows = importer.read_rows(self.partition(), trade_date=TRADE_DAY, symbols=("SBIN",))
        self.assertIn(("isin", "VARCHAR"), schema)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].symbol, rows[0].series, rows[0].isin), ("SBIN", "EQ", "INE062A01020"))
        self.assertEqual(rows[0].locator, "parquet:file_row_number:0")

    def test_unresolved_identity_is_quarantined_and_never_symbol_mapped(self):
        result = self.ingest()
        con = self.repo._connection
        self.assertEqual((result.accepted, result.quarantined), (0, 1))
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT reason_code FROM observation_quarantine").fetchone()[0], "unresolved_isin_mapping")
        self.assertEqual(con.execute("SELECT provider,dataset FROM source_document_revision").fetchone(), ("TejHQ", "tejhq/indian-markets"))
        metadata = con.execute("SELECT metadata_json::VARCHAR FROM raw_source_file").fetchone()[0]
        self.assertIn("dataset_revision", metadata)
        self.assertIn("schema_fingerprint", metadata)
        repeated = self.ingest()
        self.assertEqual((repeated.duplicates, repeated.quarantined), (0, 1))
        self.assertEqual(con.execute("SELECT count(*) FROM observation_quarantine").fetchone()[0], 1)

    def test_out_of_scope_retry_remains_out_of_scope_not_duplicate(self):
        row = (TRADE_DAY, "NIFTYBEES", "EQ", "INF204KB14I2", 10.0, 12.0, 9.0, 11.0, 100, 1100.0)
        write_parquet(self.source_path, [row])
        self.add_mapping(isin="INF204KB14I2", instrument_class="etf", platform_class="mainboard")
        first = self.ingest(symbols=("NIFTYBEES",))
        second = self.ingest(symbols=("NIFTYBEES",))
        self.assertEqual((first.out_of_scope, first.duplicates), (1, 0))
        self.assertEqual((second.out_of_scope, second.duplicates), (1, 0))

    def test_approved_identity_classification_append_reconcile_and_idempotency(self):
        self.add_mapping()
        self.add_official()
        result = self.ingest()
        self.assertEqual((result.accepted, result.reconciled, result.not_compared), (1, 1, 0))
        con = self.repo._connection
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE exchange='NSE'").fetchone()[0], 2)
        reconciliation = con.execute("SELECT comparison_outcome,differences_json::VARCHAR FROM eod_observation_reconciliation").fetchone()
        self.assertEqual(reconciliation, ("exact_match", "{}"))
        repeated = self.ingest()
        self.assertEqual(repeated.duplicates, 1)
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE source_document_id LIKE 'doc-%'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT count(*) FROM eod_observation_reconciliation").fetchone()[0], 1)

    def test_retry_reconciles_late_official_observation_once(self):
        self.add_mapping()
        first = self.ingest()
        self.assertEqual((first.accepted, first.not_compared), (1, 1))
        con = self.repo._connection
        self.assertEqual(con.execute("SELECT match_status FROM eod_observation_reconciliation").fetchone()[0], "unmatched_secondary")

        self.add_official()
        second = self.ingest()
        self.assertEqual((second.duplicates, second.reconciled, second.not_compared), (1, 1, 0))
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE source_identifier LIKE 'nse/year=%'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT count(*) FROM eod_observation_reconciliation").fetchone()[0], 2)
        active = con.execute(
            """SELECT match_status,comparison_outcome FROM eod_observation_reconciliation r
               WHERE NOT EXISTS (SELECT 1 FROM eod_observation_reconciliation n
                                 WHERE n.supersedes_reconciliation_id=r.reconciliation_id)"""
        ).fetchone()
        self.assertEqual(active, ("matched", "exact_match"))

        repeated = self.ingest()
        self.assertEqual((repeated.duplicates, repeated.reconciled), (1, 0))
        self.assertEqual(con.execute("SELECT count(*) FROM eod_observation_reconciliation").fetchone()[0], 2)

    def test_bse_listing_remains_distinct_from_nse_for_same_isin(self):
        self.add_mapping(exchange="NSE", listing="listing-sbi-nse")
        self.add_mapping(exchange="BSE", listing="listing-sbi-bse")
        self.add_official(exchange="NSE", listing="listing-sbi-nse", values=(10, 12, 9, 11, 100, 1100))
        self.add_official(exchange="BSE", listing="listing-sbi-bse", values=(20, 22, 19, 21, 200, 2200))
        bse_partition = self.partition(exchange="BSE", dataset_path="bse/year=2026/sample.parquet")
        result = self.ingest(partition=bse_partition)
        self.assertEqual((result.accepted, result.reconciled), (1, 1))
        observations = self.repo._connection.execute(
            "SELECT exchange,listing_id FROM eod_price_observation_revision WHERE trade_date=? ORDER BY exchange",
            [TRADE_DAY],
        ).fetchall()
        self.assertEqual(observations, [
            ("BSE", "listing-sbi-bse"), ("BSE", "listing-sbi-bse"), ("NSE", "listing-sbi-nse"),
        ])

    def test_non_equity_classification_is_out_of_scope(self):
        # Synthetic source rows exercise the negative classification path.
        row = (TRADE_DAY, "NIFTYBEES", "EQ", "INF204KB14I2", 10.0, 12.0, 9.0, 11.0, 100, 1100.0)
        write_parquet(self.source_path, [row])
        self.add_mapping(isin="INF204KB14I2", instrument_class="etf", platform_class="mainboard")
        result = self.ingest(symbols=("NIFTYBEES",))
        self.assertEqual((result.accepted, result.quarantined, result.out_of_scope), (0, 0, 1))
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 0)

    def test_unknown_classification_is_quarantined_not_treated_as_excluded(self):
        self.add_mapping(instrument_class="unknown", platform_class="mainboard")
        result = self.ingest()
        self.assertEqual((result.accepted, result.quarantined, result.out_of_scope), (0, 1, 0))

    def test_ambiguous_isin_and_missing_isin_are_quarantined(self):
        self.add_mapping()
        con = self.repo._connection
        con.execute("INSERT INTO equity_security VALUES ('security-other','issuer-sbi','ordinary',CURRENT_TIMESTAMP)")
        con.execute(
            """INSERT INTO security_identifier_revision
               (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,effective_to,
                source_document_id,mapping_review_status,reviewed_by,reviewed_at)
               VALUES ('isin-conflict','security-other','ISIN','INE062A01020',DATE '2021-01-01',NULL,
                       'nse-evidence','approved','reviewer',CURRENT_TIMESTAMP)"""
        )
        con.execute(
            """INSERT INTO security_identifier_revision_review
               (review_id,identifier_revision_id,review_status,recorded_at,reviewed_by,reviewed_at,
                evidence_source_document_id,evidence_locator,rationale,supersedes_review_id)
               VALUES ('isin-conflict-review','isin-conflict','approved',CURRENT_TIMESTAMP,'reviewer',CURRENT_TIMESTAMP,
                       'nse-evidence','synthetic-fixture:conflict',NULL,NULL)"""
        )
        ambiguous = self.ingest()
        self.assertEqual((ambiguous.accepted, ambiguous.quarantined), (0, 1))
        write_parquet(self.source_path, [(TRADE_DAY, "SBIN", "EQ", None, 10., 12., 9., 11., 100, 1100.)])
        missing = self.ingest(partition=self.partition(dataset_path="nse/year=2026/null_isin.parquet", revision="7654321"))
        self.assertEqual(missing.quarantined, 1)
        reasons = {row[0] for row in con.execute("SELECT DISTINCT reason_code FROM observation_quarantine").fetchall()}
        self.assertEqual(reasons, {"unresolved_isin_mapping", "missing_or_invalid_isin"})

    def test_conflicting_duplicate_rows_are_quarantined_and_nonfinite_values_rejected(self):
        duplicate = self.rows[0]
        write_parquet(self.source_path, [duplicate, duplicate])
        self.add_mapping()
        exact_duplicates = self.ingest()
        self.assertEqual((exact_duplicates.accepted, exact_duplicates.duplicates), (1, 1))
        changed = self.root / "conflict.parquet"
        write_parquet(changed, [duplicate, (TRADE_DAY, "SBIN", "EQ", "INE062A01020", 10., 13., 9., 11., 100, 1100.)])
        conflict = self.ingest(partition=self.partition(path=changed, dataset_path="nse/year=2026/conflict.parquet", revision="1234567"))
        self.assertEqual(conflict.quarantined, 2)
        nonfinite = self.root / "nonfinite.parquet"
        write_parquet(nonfinite, [(TRADE_DAY, "SBIN", "EQ", "INE062A01020", float("nan"), 12., 9., 11., 100, 1100.)])
        invalid = self.ingest(partition=self.partition(path=nonfinite, dataset_path="nse/year=2026/nonfinite.parquet", revision="2345678"))
        self.assertEqual(invalid.rejected, 1)

    def test_parser_revision_preserves_document_and_supersedes_observation(self):
        self.add_mapping()
        first = self.ingest()
        self.assertEqual(first.accepted, 1)
        second = self.ingest(partition=self.partition(parser="tejhq-parquet-v2"))
        con = self.repo._connection
        self.assertEqual(second.revised, 1)
        self.assertEqual(con.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT count(DISTINCT parser_version) FROM eod_price_observation_revision WHERE exchange='NSE'").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE supersedes_observation_id IS NOT NULL").fetchone()[0], 1)

    def test_public_as_of_and_hamsa_known_as_of_select_different_revisions(self):
        self.add_mapping()
        con = self.repo._connection
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',DATE '2026-11-09',TRUE,'regular','test-cal','nse-evidence')")
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',DATE '2026-11-11',TRUE,'regular','test-cal','nse-evidence')")
        # Add a future session so the later_cutoff is always after now().
        from datetime import timedelta
        future_date = (datetime.now(IST) + timedelta(days=2)).date()
        con.execute("INSERT INTO exchange_trading_session VALUES ('NSE',?,TRUE,'regular','test-cal','nse-evidence')",
                    [future_date])
        self.ingest()
        old_cutoff = datetime(2026, 11, 9, 15, 30, tzinfo=IST)
        public = self.repo.eod_observations_as_of(
            exchange="NSE", trade_date=TRADE_DAY, cutoff=old_cutoff, availability_mode="public_as_of",
            calendar_version="test-cal",
        )
        known = self.repo.eod_observations_as_of(
            exchange="NSE", trade_date=TRADE_DAY, cutoff=old_cutoff, availability_mode="hamsa_known_as_of",
            calendar_version="test-cal",
        )
        self.assertEqual(len(public), 1)
        self.assertEqual(known, [])
        self.ingest(partition=self.partition(parser="tejhq-parquet-v2"))
        pinned_old_parser = self.repo.eod_observations_as_of(
            exchange="NSE", trade_date=TRADE_DAY, cutoff=old_cutoff, availability_mode="public_as_of",
            calendar_version="test-cal", parser_version="tejhq-parquet-v1",
        )
        self.assertEqual(pinned_old_parser[0]["parser_version"], "tejhq-parquet-v1")
        # Use a future cutoff so extraction_timestamp (now()) <= cutoff.
        later_cutoff = datetime.combine(future_date, time(15, 30), tzinfo=IST)
        later_known = self.repo.eod_observations_as_of(
            exchange="NSE", trade_date=TRADE_DAY, cutoff=later_cutoff, availability_mode="hamsa_known_as_of",
            calendar_version="test-cal",
        )
        self.assertEqual(later_known[0]["parser_version"], "tejhq-parquet-v2")
        with self.assertRaisesRegex(RepositoryIntegrityError, "15:30 Asia/Kolkata"):
            self.repo.eod_observations_as_of(
                exchange="NSE", trade_date=TRADE_DAY,
                cutoff=datetime(2026, 11, 9, 15, 29, tzinfo=IST),
                availability_mode="public_as_of", calendar_version="test-cal",
            )

    def test_changed_bytes_create_new_source_and_observation_revisions(self):
        self.add_mapping()
        self.ingest()
        changed = self.root / "changed.parquet"
        write_parquet(changed, [(TRADE_DAY, "SBIN", "EQ", "INE062A01020", 10., 13., 9., 12., 101, 1200.)])
        second = self.ingest(partition=self.partition(path=changed, dataset_path="nse/year=2026/sample.parquet"))
        con = self.repo._connection
        self.assertEqual(second.revised, 1)
        docs = con.execute("SELECT revision_number,supersedes_source_document_id FROM source_document_revision WHERE provider='TejHQ' ORDER BY revision_number").fetchall()
        self.assertEqual((len(docs), docs[1][0], docs[1][1] is not None), (2, 2, True))
        self.assertEqual(con.execute("SELECT count(*) FROM eod_price_observation_revision WHERE supersedes_observation_id IS NOT NULL").fetchone()[0], 1)

    def test_new_immutable_dataset_commit_extends_file_revision_lineage(self):
        self.add_mapping()
        self.ingest()
        changed = self.root / "commit-revised.parquet"
        write_parquet(changed, [(TRADE_DAY, "SBIN", "EQ", "INE062A01020", 10., 13., 9., 12., 101, 1200.)])
        self.ingest(partition=self.partition(
            path=changed, revision="7654321", dataset_path="nse/year=2026/sample.parquet",
        ))
        con = self.repo._connection
        docs = con.execute(
            """SELECT source_identifier,revision_number,supersedes_source_document_id
               FROM source_document_revision WHERE provider='TejHQ' ORDER BY revision_number"""
        ).fetchall()
        self.assertEqual(len(docs), 2)
        self.assertTrue(docs[0][0].endswith("@abcdef1"))
        self.assertTrue(docs[1][0].endswith("@7654321"))
        self.assertEqual((docs[1][1], docs[1][2] is not None), (2, True))

    def test_archive_crash_retry_and_database_rollback(self):
        self.add_mapping()
        def crash(stage):
            if stage == "after_archive_before_database":
                raise RuntimeError("injected archive-boundary crash")
        with self.assertRaisesRegex(RuntimeError, "archive-boundary"):
            self.ingest(test_mode=True, fault_hook=crash)
        archives = list((self.root / "archive").glob("[0-9a-f][0-9a-f]/*"))
        self.assertEqual(len(archives), 1)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 0)
        self.source_path.unlink()
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            recovered = importer.recover_archived_sources()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].accepted, 1)

        # A failure after row writes but before commit rolls all normalized and
        # processing records back. The immutable archive remains retryable.
        changed = self.root / "rollback.parquet"
        write_parquet(changed, [(TRADE_DAY, "SBIN", "EQ", "INE062A01020", 10., 12., 9., 11., 100, 1100.)])
        rollback_partition = self.partition(path=changed, dataset_path="nse/year=2026/rollback.parquet", revision="7654321")
        def fail_transaction(stage):
            if stage == "before_database_commit":
                raise RuntimeError("injected database failure")
        with self.assertRaisesRegex(RuntimeError, "database failure"):
            self.ingest(partition=rollback_partition, test_mode=True, fault_hook=fail_transaction)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision WHERE source_identifier='nse/year=2026/rollback.parquet'").fetchone()[0], 0)
        retried_rollback = self.ingest(partition=rollback_partition)
        self.assertEqual(retried_rollback.revised, 1)

    def test_commit_before_return_retry_is_idempotent(self):
        self.add_mapping()
        def crash(stage):
            if stage == "after_database_commit_before_return":
                raise RuntimeError("simulated process exit after commit")
        with self.assertRaisesRegex(RuntimeError, "after commit"):
            self.ingest(test_mode=True, fault_hook=crash)
        count = self.repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0]
        self.assertEqual(count, 1)
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            recovered = importer.recover_archived_sources()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].duplicates, 1)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM eod_price_observation_revision").fetchone()[0], 1)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM eod_observation_reconciliation").fetchone()[0], 1)

    def test_crash_inside_source_registration_rolls_back_and_recovers(self):
        self.add_mapping()

        def crash(stage):
            if stage == "after_raw_file_registration_before_source_document":
                raise RuntimeError("injected source registration failure")

        with self.assertRaisesRegex(RuntimeError, "source registration"):
            self.ingest(test_mode=True, fault_hook=crash)
        con = self.repo._connection
        self.assertEqual(con.execute("SELECT count(*) FROM raw_source_file WHERE provider='TejHQ'").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 0)
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            recovered = importer.recover_archived_sources()
        self.assertEqual((len(recovered), recovered[0].accepted), (1, 1))

    def test_crash_after_source_registration_recovers_without_revising_source(self):
        self.add_mapping()

        def crash(stage):
            if stage == "after_source_registration_before_processing":
                raise RuntimeError("injected pre-processing crash")

        with self.assertRaisesRegex(RuntimeError, "pre-processing"):
            self.ingest(test_mode=True, fault_hook=crash)
        con = self.repo._connection
        self.assertEqual(con.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 1)
        self.assertEqual(con.execute(
            """SELECT count(*) FROM source_document_processing_revision p
               JOIN source_document_revision d USING(source_document_id) WHERE d.provider='TejHQ'"""
        ).fetchone()[0], 0)
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            recovered = importer.recover_archived_sources()
        self.assertEqual((len(recovered), recovered[0].accepted), (1, 1))
        self.assertEqual(con.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 1)

    def test_recovery_refuses_archived_bytes_with_wrong_manifest_checksum(self):
        def crash(stage):
            if stage == "after_archive_before_database":
                raise RuntimeError("injected archive crash")

        with self.assertRaisesRegex(RuntimeError, "archive crash"):
            self.ingest(test_mode=True, fault_hook=crash)
        archive_file = next((self.root / "archive").glob("[0-9a-f][0-9a-f]/*"))
        archive_file.write_bytes(b"tampered")
        with TejHQParquetImporter(self.repo, archive_root=self.root / "archive") as importer:
            with self.assertRaisesRegex(RepositoryIntegrityError, "do not match the archived checksum"):
                importer.recover_archived_sources()
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM source_document_revision WHERE provider='TejHQ'").fetchone()[0], 0)

    def test_invalid_parquet_and_mutable_revision_rejected(self):
        with self.assertRaisesRegex(ValueError, "immutable Git commit"):
            self.partition(revision="main")
        invalid = self.root / "bad.parquet"
        con = duckdb.connect(":memory:")
        try:
            con.execute("COPY (SELECT 1 AS wrong) TO ? (FORMAT PARQUET)", [str(invalid)])
        finally:
            con.close()
        bad_partition = self.partition(path=invalid, dataset_path="nse/year=2026/bad.parquet", revision="7654321")
        with self.assertRaisesRegex(ValueError, "missing columns"):
            self.ingest(partition=bad_partition)


if __name__ == "__main__":
    import unittest
    unittest.main()
