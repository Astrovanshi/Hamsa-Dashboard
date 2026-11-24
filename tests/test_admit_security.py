from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.storage.duckdb_repository import DuckDBRepository
import scripts.admit_security as admit


class AdmitSecurityCLITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.db_path = self.root / "test_hamsa.duckdb"
        self.sqlite_path = self.root / "test_reviews.sqlite3"
        self.archive_root = self.root / "archive"
        self.archive_root.mkdir()

        # Seed source document
        with DuckDBRepository(self.db_path) as repo:
            doc_file = self.root / "nse_bhavcopy.csv"
            doc_file.write_text("dummy source", encoding="utf-8")
            reg = repo.register_local_source_document(
                doc_file,
                archive_root=self.archive_root,
                exchange="NSE",
                dataset="bhavcopy",
                source_identifier="NSE_BHAV_TEST",
                source_document_date=date(2026, 11, 8),
                publication_date=date(2026, 11, 8),
                published_at=datetime(2026, 11, 8, 10, 0, tzinfo=MARKET_TIMEZONE),
                parser_version="test-parser-v1",
                retention_authorized=True,
            )
            self.source_doc_id = reg.source_document_id

            # Seed calendar: two historical sessions plus one future session so
            # the final audit can use a cutoff that is always after now().
            future_date = (datetime.now(MARKET_TIMEZONE) + timedelta(days=2)).date()
            repo._connection.execute(
                "INSERT INTO exchange_trading_session VALUES ('NSE', DATE '2026-11-09', TRUE, 'regular', 'test-cal-v1', ?)",
                [self.source_doc_id],
            )
            repo._connection.execute(
                "INSERT INTO exchange_trading_session VALUES ('NSE', DATE '2026-11-11', TRUE, 'regular', 'test-cal-v1', ?)",
                [self.source_doc_id],
            )
            repo._connection.execute(
                "INSERT INTO exchange_trading_session VALUES ('NSE', ?, TRUE, 'regular', 'test-cal-v1', ?)",
                [future_date, self.source_doc_id],
            )
            self.future_date = future_date

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_admission_workflow_and_audit(self):
        with DuckDBRepository(self.db_path) as repo:
            res = repo.append_security_identity_candidate(
                issuer_entity_id="issuer-test-sbin",
                security_id="sec-test-sbin",
                listing_id="listing-nse-sbin",
                exchange="NSE",
                exchange_instrument_id="3045",
                isin="INE062A01020",
                legal_name="State Bank of India",
                identity_observed_from=date(1995, 3, 1),
                source_document_id=self.source_doc_id,
                source_locator="FinInstrmId:3045",
            )
            mapping_id = res["identifier_revision_id"]

            list_rev_id = repo.append_exchange_listing_revision({
                "listing_revision_id": "rev-listing-sbin",
                "listing_id": "listing-nse-sbin",
                "symbol": "SBIN",
                "series": "EQ",
                "status": "active",
                "effective_from": date(1995, 3, 1),
                "source_document_id": self.source_doc_id,
                "extraction_locator": "line 1",
                "parser_version": "test-v1",
            })

            # Historical pre-review audit: no approved identity yet, so
            # disposition must be unresolved regardless of cutoff.
            cutoff = datetime.combine(date(2026, 11, 9), time(15, 30), tzinfo=MARKET_TIMEZONE)
            audit_initial = repo.security_admission_checklist(
                listing_id="listing-nse-sbin",
                observation_date=date(2026, 11, 9),
                cutoff=cutoff,
                availability_mode="public_as_of",
                calendar_version="test-cal-v1",
            )
            self.assertEqual(audit_initial["disposition"], "unresolved_classification")

            # Review Identity -> Approved FIRST so classification snapshot
            # can link to the approved ISIN mapping.
            # New signature: no supersedes_identifier_revision_id.
            review_id = repo.append_security_identifier_review(
                identifier_revision_id=mapping_id,
                review_status="approved",
                reviewer="operator",
                reviewer_actor_type="human",
                evidence_source_document_id=self.source_doc_id,
                evidence_locator="row FinInstrmId=3045",
                rationale="SBIN identity confirmed from NSE bhavcopy",
            )

            # Verify the candidate row was NOT mutated — it must remain pending.
            raw = repo._connection.execute(
                "SELECT mapping_review_status FROM security_identifier_revision WHERE identifier_revision_id=?",
                [mapping_id],
            ).fetchone()
            self.assertEqual(raw[0], "pending",
                             "candidate row must remain pending after review")

            # Verify the review row was inserted with correct fields.
            rev_row = repo._connection.execute(
                "SELECT review_status,reviewed_by,reviewer_actor_type FROM security_identifier_revision_review WHERE review_id=?",
                [review_id],
            ).fetchone()
            self.assertIsNotNone(rev_row)
            self.assertEqual(rev_row[0], "approved")
            self.assertEqual(rev_row[1], "operator")
            self.assertEqual(rev_row[2], "human")

            # Listing classification snapshot (requires approved ISIN mapping).
            snap_id = repo.append_listing_classification_snapshot({
                "listing_classification_snapshot_id": "snap-sbin-v1",
                "listing_id": "listing-nse-sbin",
                "exchange": "NSE",
                "source_document_id": self.source_doc_id,
                "source_snapshot_date": date(2026, 11, 9),
                "raw_isin": "INE062A01020",
                "raw_symbol": "SBIN",
                "raw_series": "EQ",
                "raw_listing_status": "active",
                "source_fields_json": {"symbol": "SBIN"},
                "parser_version": "test-v1",
                "extraction_locator": "line 1",
            })

            # Review Listing -> Approved
            repo.append_exchange_listing_revision_review({
                "listing_revision_review_id": "chk-list-sbin",
                "listing_revision_id": list_rev_id,
                "review_status": "approved",
                "reviewed_by": "operator",
                "evidence_source_document_id": self.source_doc_id,
                "evidence_locator": "bhavcopy row 1",
                "rationale": "evidenced admission active",
            })

            # Review Classification -> instrument approved, platform approved
            repo.append_listing_classification_review_revision({
                "classification_review_revision_id": "chk-class-sbin",
                "listing_classification_snapshot_id": snap_id,
                "listing_id": "listing-nse-sbin",
                "rationale": "ordinary equity on mainboard",
                "instrument_review_status": "approved",
                "instrument_class": "ordinary_equity",
                "instrument_valid_from": date(1995, 3, 1),
                "instrument_evidence_source_document_id": self.source_doc_id,
                "instrument_evidence_locator": "SBI Act 1955 Section 4",
                "instrument_reviewed_by": "operator",
                "platform_review_status": "approved",
                "platform_class": "mainboard",
                "platform_valid_from": date(1995, 3, 1),
                "platform_evidence_source_document_id": self.source_doc_id,
                "platform_evidence_locator": "NSE Capital Market Bhavcopy Segment CM",
                "platform_reviewed_by": "operator",
            })

            # Final audit uses a future cutoff (always after the reviews just
            # recorded via now()) so recorded_at <= cutoff is always satisfied.
            audit_cutoff = datetime.combine(self.future_date, time(15, 30), tzinfo=MARKET_TIMEZONE)
            audit_approved = repo.security_admission_checklist(
                listing_id="listing-nse-sbin",
                observation_date=self.future_date,
                cutoff=audit_cutoff,
                availability_mode="public_as_of",
                calendar_version="test-cal-v1",
            )
            self.assertEqual(audit_approved["disposition"], "eligible_mainboard_ordinary_equity")
            for c in audit_approved["checks"]:
                self.assertEqual(c["status"], "Approved")

        # SQLite Business Sector Review
        with DuckDBRepository(self.db_path) as a_repo:
            d_repo = admit.DossierReviewRepository(
                self.sqlite_path, schema_path=ROOT / "sql" / "sqlite_schema.sql", analytics_repository=a_repo
            )
            rev_id = d_repo.append_business_classification_review(
                entity_id="issuer-test-sbin",
                business_class="financial",
                valid_from="1995-03-01",
                valid_to=None,
                reviewer="operator",
                rationale="Public sector bank governed by RBI and SBI Act",
                source_document_id=self.source_doc_id,
                locator="SBI Act 1955",
                review_status="approved",
            )
            d_repo.close()
            self.assertTrue(rev_id.startswith("business-class-"))

        # Verify active-review supersession enforcement on listing and classification reviews
        with DuckDBRepository(self.db_path) as repo:
            with self.assertRaisesRegex(Exception, "supersedes_review_id"):
                repo.append_exchange_listing_revision_review({
                    "listing_revision_review_id": "chk-list-sbin-dup",
                    "listing_revision_id": "rev-listing-sbin",
                    "review_status": "approved",
                    "reviewed_by": "operator",
                    "evidence_source_document_id": self.source_doc_id,
                    "evidence_locator": "bhavcopy row 1",
                    "rationale": "duplicate without supersedes",
                })
            with self.assertRaisesRegex(Exception, "supersedes_review_revision_id"):
                repo.append_listing_classification_review_revision({
                    "classification_review_revision_id": "chk-class-sbin-dup",
                    "listing_classification_snapshot_id": "snap-sbin-v1",
                    "listing_id": "listing-nse-sbin",
                    "rationale": "duplicate without supersedes",
                    "instrument_review_status": "approved",
                    "instrument_class": "ordinary_equity",
                    "instrument_valid_from": date(1995, 3, 1),
                    "instrument_evidence_source_document_id": self.source_doc_id,
                    "instrument_evidence_locator": "SBI Act 1955 Section 4",
                    "instrument_reviewed_by": "operator",
                    "platform_review_status": "approved",
                    "platform_class": "mainboard",
                    "platform_valid_from": date(1995, 3, 1),
                    "platform_evidence_source_document_id": self.source_doc_id,
                    "platform_evidence_locator": "NSE Capital Market Bhavcopy Segment CM",
                    "platform_reviewed_by": "operator",
                })

            # Verify unit conversion rule and local financial results CLI ingestion for admitted security
            rule_id = repo.append_unit_conversion_rule(
                conversion_rule_id="rule-inr-crore-v1",
                source_unit="INR_CRORE",
                canonical_unit="INR",
                dimension="currency",
                multiplier=admit.Decimal("10000000"),
                rule_description="Convert INR Crore to canonical INR",
                rule_version="v1",
                review_status="approved",
                source_document_id=self.source_doc_id,
            )
            self.assertEqual(rule_id, "rule-inr-crore-v1")

        fin_csv = self.root / "sbin_results.csv"
        fin_csv.write_text(
            "isin,metric,value,unit,period_start,period_end,reporting_scope\n"
            "INE062A01020,revenue,500,INR_CRORE,2026-07-01,2026-09-30,consolidated\n"
            "INE062A01020,pat,100,INR_CRORE,2026-07-01,2026-09-30,consolidated\n",
            encoding="utf-8",
        )
        import scripts.ingest_financial_results as ingest_fin
        sys.argv = [
            "ingest_financial_results.py",
            "--database", str(self.db_path),
            "--archive-root", str(self.archive_root / "fin"),
            "--source-file", str(fin_csv),
            "--provider", "NSE",
            "--source-identifier", "SBIN_Q2_FY27_RESULTS",
            "--source-document-date", "2026-11-08",
            "--publication-date", "2026-11-08",
            "--published-at", "2026-11-08T14:00:00+05:30",
            "--authorize-local-retention",
        ]
        self.assertEqual(ingest_fin.main(), 0)
        with DuckDBRepository(self.db_path) as repo:
            fin_rows = repo._connection.execute(
                "SELECT metric, raw_value, raw_unit, canonical_value, canonical_unit, conversion_rule_id "
                "FROM financial_observation_revision ORDER BY metric"
            ).fetchall()
            self.assertEqual(len(fin_rows), 2)
            self.assertEqual(fin_rows[0][0], "pat")
            self.assertEqual(fin_rows[0][3], admit.Decimal("1000000000"))
            self.assertEqual(fin_rows[0][5], "rule-inr-crore-v1")

    def test_cli_subcommands_dry_run(self):
        # Verify dry-run flags on all subcommands
        sys.argv = ["admit_security.py", "stage-candidate",
                    "--database", str(self.db_path),
                    "--issuer-entity-id", "iss-dry",
                    "--security-id", "sec-dry",
                    "--listing-id", "list-dry",
                    "--exchange", "NSE",
                    "--exchange-instrument-id", "dry-instr",
                    "--isin", "INE000A01000",
                    "--legal-name", "Dry Run Corp",
                    "--identity-observed-from", "2026-01-01",
                    "--source-document-id", self.source_doc_id,
                    "--source-locator", "loc",
                    "--symbol", "DRY",
                    "--dry-run"]
        self.assertEqual(admit.main(), 0)


if __name__ == "__main__":
    unittest.main()
