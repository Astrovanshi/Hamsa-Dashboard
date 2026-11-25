"""Comprehensive tests for Tiered Universe & Intelligent Data Acquisition Architecture."""

import json
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hamsa.dossiers.repository import DossierReviewRepository
from hamsa.screening.tiered_universe import (
    IntelligenceTier,
    TieredUniverseManager,
    TransitionType,
)
from hamsa.storage.duckdb_repository import DuckDBRepository

SCHEMA_SQL = ROOT / "sql" / "sqlite_schema.sql"


class TieredUniverseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.duck_path = self.temp_dir / "test_tiered.duckdb"
        self.sql_path = self.temp_dir / "test_tiered_reviews.sqlite3"

        self.repo = DuckDBRepository(self.duck_path)
        self.reviews = DossierReviewRepository(
            self.sql_path, schema_path=SCHEMA_SQL, analytics_repository=self.repo
        )
        self.manager = TieredUniverseManager(self.repo, self.reviews)

        # Seed raw_source_file and source_document_revision
        con = self.repo._connection
        con.execute("""
            INSERT INTO raw_source_file (
                source_file_id, provider, dataset, original_filename, checksum_sha256,
                archive_path, captured_at, source_as_of_date, license_review_reference, license_status
            ) VALUES (
                'raw-test-1', 'NSE', 'CM-security', 'test.csv', '0000000000000000000000000000000000000000000000000000000000000000',
                'path/test', CURRENT_TIMESTAMP, '2026-11-09', 'lic-ref-1', 'approved'
            )
        """)

        con.execute("""
            INSERT INTO source_document_revision (
                source_document_id, provider, dataset, source_identifier, checksum_sha256,
                source_file_id, revision_number, source_document_date, publication_date, ingestion_timestamp, parser_version,
                extraction_timestamp, extraction_locator
            ) VALUES (
                'doc-test-1', 'NSE', 'CM-security', 'TEST_DOC', '0000000000000000000000000000000000000000000000000000000000000000',
                'raw-test-1', 1, '2026-11-09', '2026-11-09', CURRENT_TIMESTAMP, 'test-v1', '2026-11-09 15:30:00+00', 'loc-1'
            )
        """)

        # Seed test entity
        con.execute("INSERT INTO issuer_entity (entity_id, created_at) VALUES ('issuer-test', '2026-11-24 20:39:06+00')")
        con.execute("""
            INSERT INTO issuer_name_revision (name_revision_id, entity_id, legal_name, effective_from, source_document_id)
            VALUES ('name-test', 'issuer-test', 'Test Dynamics Limited', '2015-01-01', 'doc-test-1')
        """)
        con.execute("INSERT INTO equity_security (security_id, issuer_entity_id, share_class, created_at) VALUES ('sec-test', 'issuer-test', 'ordinary', '2026-11-24 20:39:06+00')")
        con.execute("INSERT INTO exchange_listing (listing_id, security_id, exchange, exchange_instrument_id, created_at) VALUES ('listing-test', 'sec-test', 'NSE', '9999', '2026-11-24 20:39:06+00')")
        con.execute("INSERT INTO exchange_listing_revision (listing_revision_id, listing_id, symbol, series, status, effective_from, source_document_id) VALUES ('lrev-test', 'listing-test', 'TESTDYN', 'EQ', 'active', '2015-01-01', 'doc-test-1')")

    def tearDown(self):
        self.reviews.close()
        self.repo.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_tier_defaults_to_radar(self):
        tier = self.manager.get_current_tier("issuer-test")
        self.assertEqual(tier, IntelligenceTier.RADAR.value)

    def test_lifecycle_transition_and_history(self):
        ev1 = self.manager.record_tier_transition(
            entity_id="issuer-test",
            new_tier=IntelligenceTier.CANDIDATE,
            transition_type=TransitionType.AUTOMATED_SIGNAL,
            primary_trigger="Volume Surge 3.2x",
            trigger_detail="Breakout from 20-day base",
            supporting_signals={"vol_mult": 3.2, "deliv_chg": 8.5},
            source_document_id="doc-test-1",
        )
        self.assertTrue(ev1.startswith("tier-issuer-test-candidate-"))
        self.assertEqual(self.manager.get_current_tier("issuer-test"), IntelligenceTier.CANDIDATE.value)

        ev2 = self.manager.promote_candidate_to_investigation(
            entity_id="issuer-test",
            reason="High asymmetric opportunity identified by analyst",
            reviewer="senior-analyst",
        )
        self.assertEqual(self.manager.get_current_tier("issuer-test"), IntelligenceTier.INVESTIGATION.value)

        wl_status = self.reviews.connection.execute(
            "SELECT status FROM research_watchlist_revision WHERE entity_id='issuer-test' ORDER BY recorded_at DESC LIMIT 1"
        ).fetchone()[0]
        self.assertEqual(wl_status, "research_priority")

        self.manager.demote_candidate_to_radar(
            entity_id="issuer-test",
            reason="Catalyst played out; returning to continuous radar monitoring",
        )
        self.assertEqual(self.manager.get_current_tier("issuer-test"), IntelligenceTier.RADAR.value)

        hist = self.manager.get_lifecycle_history("issuer-test")
        self.assertEqual(len(hist), 3)
        self.assertEqual(hist[0]["new_tier"], "RADAR")
        self.assertEqual(hist[1]["new_tier"], "INVESTIGATION")
        self.assertEqual(hist[2]["new_tier"], "CANDIDATE")

    def test_archived_company_automatic_re_entry(self):
        self.manager.archive_company("issuer-test", reason="Lack of institutional participation")
        self.assertEqual(self.manager.get_current_tier("issuer-test"), IntelligenceTier.ARCHIVED.value)

        ev = self.manager.record_tier_transition(
            entity_id="issuer-test",
            new_tier=IntelligenceTier.CANDIDATE,
            transition_type=TransitionType.RE_ENTRY,
            primary_trigger="Sudden Re-Emergence: Unusual Volume 4.5x",
            trigger_detail="DII bulk purchase detected",
            source_document_id="doc-test-1",
        )
        self.assertEqual(self.manager.get_current_tier("issuer-test"), IntelligenceTier.CANDIDATE.value)
        hist = self.manager.get_lifecycle_history("issuer-test")
        self.assertEqual(hist[0]["transition_type"], "re_entry")

    def test_tier_breakdown_metrics(self):
        counts = self.manager.get_tier_breakdown()
        self.assertIn("RADAR", counts)
        self.assertIn("CANDIDATE", counts)
        self.assertIn("INVESTIGATION", counts)
        self.assertEqual(counts["RADAR"], 1)
        self.assertEqual(counts["CANDIDATE"], 0)


if __name__ == "__main__":
    unittest.main()