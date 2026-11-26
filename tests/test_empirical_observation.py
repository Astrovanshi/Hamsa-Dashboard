"""Tests for HAMSA Phase II Empirical Market Intelligence & Observation Engine."""

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

from hamsa.screening.empirical_observation import EmpiricalObservationEngine
from hamsa.storage.duckdb_repository import DuckDBRepository


class EmpiricalObservationEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.duck_path = self.temp_dir / "test_empirical.duckdb"
        self.repo = DuckDBRepository(self.duck_path)
        self.engine = EmpiricalObservationEngine(self.repo)
        con = self.repo._connection

        # Seed minimal raw source file and document
        con.execute("""
            INSERT INTO raw_source_file (
                source_file_id, provider, dataset, original_filename, checksum_sha256,
                archive_path, captured_at, source_as_of_date, license_review_reference, license_status
            ) VALUES (
                'raw-1', 'NSE', 'CM-security', 'test.csv', '0000000000000000000000000000000000000000000000000000000000000000',
                'p/test', CURRENT_TIMESTAMP, '2026-11-09', 'LIC_TEST', 'approved'
            )
        """)
        con.execute("""
            INSERT INTO source_document_revision (
                source_document_id, provider, dataset, source_identifier, checksum_sha256,
                source_file_id, revision_number, source_document_date, publication_date,
                ingestion_timestamp, parser_version, extraction_timestamp, extraction_locator
            ) VALUES (
                'doc-1', 'NSE', 'CM-security', 'TEST_DOC', '0000000000000000000000000000000000000000000000000000000000000000',
                'raw-1', 1, '2026-11-09', '2026-11-09', CURRENT_TIMESTAMP, 'v1', CURRENT_TIMESTAMP, 'loc'
            )
        """)

        # Seed universe registry
        con.execute("""
            INSERT INTO security_universe_registry (
                isin, symbol, company_name, exchange, series, operational_state,
                entity_id, security_id, listing_id, registered_at, updated_at, source_document_id
            ) VALUES (
                'INE000A01001', 'TESTEMP', 'Test Empirical Ltd', 'NSE', 'EQ', 'RADAR_READY',
                'issuer-testemp', 'sec-testemp', 'listing-nse-testemp', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'doc-1'
            )
        """)

        # Seed canonical identities
        con.execute("INSERT INTO issuer_entity (entity_id, created_at) VALUES ('issuer-testemp', CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO issuer_name_revision (name_revision_id, entity_id, legal_name, effective_from, source_document_id) VALUES ('name-1', 'issuer-testemp', 'Test Empirical Ltd', '2015-01-01', 'doc-1')")
        con.execute("INSERT INTO equity_security (security_id, issuer_entity_id, share_class, created_at) VALUES ('sec-testemp', 'issuer-testemp', 'ordinary', CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO security_identifier_revision (identifier_revision_id, security_id, identifier_type, identifier_value, effective_from, source_document_id, mapping_review_status, reviewed_by, reviewed_at, parser_version, extraction_timestamp, extraction_locator, extraction_revision_id) VALUES ('isin-1', 'sec-testemp', 'ISIN', 'INE000A01001', '2015-01-01', 'doc-1', 'approved', 'tester', CURRENT_TIMESTAMP, 'v1', CURRENT_TIMESTAMP, 'loc', 'ext-1')")
        con.execute("INSERT INTO exchange_listing (listing_id, security_id, exchange, exchange_instrument_id, created_at) VALUES ('listing-nse-testemp', 'sec-testemp', 'NSE', 'INE000A01001', CURRENT_TIMESTAMP)")
        con.execute("INSERT INTO exchange_listing_revision (listing_revision_id, listing_id, symbol, series, status, effective_from, source_document_id) VALUES ('lrev-1', 'listing-nse-testemp', 'TESTEMP', 'EQ', 'active', '2015-01-01', 'doc-1')")

        # Seed coverage & eod price for signal date 2026-11-09
        con.execute("INSERT INTO security_historical_coverage (isin, total_eod_sessions, rolling_20d_ready, avg_turnover_20d_cr, liquidity_tier, calculated_at) VALUES ('INE000A01001', 25, TRUE, 5.5, 'MID_LIQUID', CURRENT_TIMESTAMP)")
        con.execute("""
            INSERT INTO normalized_observation_registry (
                observation_id, observation_type, source_document_id, source_identifier, checksum_sha256,
                parser_version, extraction_timestamp, extraction_locator
            ) VALUES (
                'eod-1', 'eod_price', 'doc-1', 'TEST', '0000000000000000000000000000000000000000000000000000000000000000',
                'v1', CURRENT_TIMESTAMP, 'loc'
            )
        """)
        con.execute("""
            INSERT INTO eod_price_observation_revision (
                observation_id, observation_type, security_id, listing_id, exchange, trade_date,
                open_raw, high_raw, low_raw, close_raw, price_unit, volume_raw, volume_unit, turnover_raw, turnover_unit,
                source_document_id, source_identifier, checksum_sha256, parser_version, extraction_timestamp, extraction_locator, quality_status
            ) VALUES (
                'eod-1', 'eod_price', 'sec-testemp', 'listing-nse-testemp', 'NSE', '2026-11-09',
                100.0, 110.0, 95.0, 108.0, 'INR', 1000000, 'SHARES', 100000000, 'INR',
                'doc-1', 'TEST', '0000000000000000000000000000000000000000000000000000000000000000', 'v1', CURRENT_TIMESTAMP, 'loc', 'observed'
            )
        """)

        # Seed daily radar signal
        con.execute("""
            INSERT INTO security_radar_signal_daily (
                signal_id, listing_id, trade_date, exchange, volume_multiple, turnover_multiple,
                avg_turnover_20d_inr, delivery_percentage, delivery_chg_pp, session_return_pct,
                drawdown_20d_pct, close_range_position, is_volume_dislocation, is_delivery_surge,
                is_extreme_sell_side, is_breakout, calculated_at, source_document_id
            ) VALUES (
                'sig-1', 'listing-nse-testemp', '2026-11-09', 'NSE', 3.5, 3.2,
                55000000, 45.0, 12.5, 8.0, -4.5, 0.85, TRUE, TRUE, FALSE, TRUE, CURRENT_TIMESTAMP, 'doc-1'
            )
        """)

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_and_record_session_events(self):
        events = self.engine.extract_and_record_session_events(date(2026, 11, 9))
        self.assertGreaterEqual(len(events), 1)

        # Check in DB
        con = self.repo._connection
        ev_types = [r[0] for r in con.execute("SELECT event_type FROM market_event_observation_ledger WHERE isin='INE000A01001'").fetchall()]
        self.assertIn("DUAL_SURGE", ev_types)
        self.assertIn("RANGE_BREAKOUT", ev_types)

    def test_track_forward_outcomes_pending_and_evaluated(self):
        events = self.engine.extract_and_record_session_events(date(2026, 11, 9))
        ev_id = events[0]["event_id"]

        # Initially without forward prices: all horizons PENDING
        outcomes_pending = self.engine.track_forward_outcomes(ev_id, horizons=(1, 5))
        self.assertEqual(len(outcomes_pending), 2)
        self.assertEqual(outcomes_pending[0]["status"], "PENDING")

        # Now insert 5 forward price sessions
        con = self.repo._connection
        for d in range(1, 6):
            trade_d = date(2026, 11, 9 + d)
            con.execute(f"""
                INSERT INTO normalized_observation_registry (
                    observation_id, observation_type, source_document_id, source_identifier, checksum_sha256,
                    parser_version, extraction_timestamp, extraction_locator
                ) VALUES (
                    'eod-fwd-{d}', 'eod_price', 'doc-1', 'TEST', '0000000000000000000000000000000000000000000000000000000000000000',
                    'v1', CURRENT_TIMESTAMP, 'loc'
                )
            """)
            con.execute(f"""
                INSERT INTO eod_price_observation_revision (
                    observation_id, observation_type, security_id, listing_id, exchange, trade_date,
                    open_raw, high_raw, low_raw, close_raw, price_unit, volume_raw, volume_unit, turnover_raw, turnover_unit,
                    source_document_id, source_identifier, checksum_sha256, parser_version, extraction_timestamp, extraction_locator, quality_status
                ) VALUES (
                    'eod-fwd-{d}', 'eod_price', 'sec-testemp', 'listing-nse-testemp', 'NSE', '{trade_d.isoformat()}',
                    109.0, {110.0 + d * 2}, 107.0, {110.0 + d}, 'INR', 500000, 'SHARES', 50000000, 'INR',
                    'doc-1', 'TEST', '0000000000000000000000000000000000000000000000000000000000000000', 'v1', CURRENT_TIMESTAMP, 'loc', 'observed'
                )
            """)

        outcomes_eval = self.engine.track_forward_outcomes(ev_id, horizons=(1, 5))
        self.assertEqual(outcomes_eval[0]["status"], "EVALUATED")
        self.assertEqual(outcomes_eval[1]["status"], "EVALUATED")
        self.assertGreater(outcomes_eval[1]["forward_return_pct"], 0)
        self.assertGreater(outcomes_eval[1]["mfe_pct"], 0)

    def test_append_journal_and_generate_report(self):
        self.engine.extract_and_record_session_events(date(2026, 11, 9))
        j_id = self.engine.append_journal_entry(
            entry_date=date(2026, 11, 9),
            title="Dual Surge Preceding Structural Expansion",
            observation="Tested equity displayed volume 3.5x accompanied by +12.5pp delivery surge.",
            evidence={"symbol": "TESTEMP", "vol_mult": 3.5, "deliv_chg": 12.5},
            pattern_type="RECURRING",
            hypothesis="Delivery expansion confirms real capital settlement rather than intraday churning.",
            counter_evidence="Small cap liquidity pockets can show localized delivery spikes without subsequent follow-through.",
            confidence_level="EMERGING",
            next_test="Measure 20-day MFE across all dual-surge events above 1 Cr/day turnover.",
        )
        self.assertTrue(j_id.startswith("jnl-2026-11-09-"))

        rep = self.engine.generate_empirical_intelligence_report(date(2026, 11, 9))
        self.assertEqual(rep["trade_date"], "2026-11-09")
        self.assertGreaterEqual(rep["total_events_recorded"], 1)
        self.assertEqual(len(rep["journal_entries"]), 1)
        self.assertIn("HAMSA Phase II Empirical Market Intelligence Report", rep["markdown_report"])


if __name__ == "__main__":
    unittest.main()