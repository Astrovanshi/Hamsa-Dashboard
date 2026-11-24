from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.ingestion.exchange_calendar import (
    CalendarImportSpec,
    RepositoryExchangeCalendar,
    import_exchange_calendar,
    parse_calendar_csv,
)
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


HEADERS = "exchange,session_date,is_trading_session,session_type\n"
ROWS_V1 = (
    "NSE,2026-11-08,true,special\n"
    "NSE,2026-11-09,true,regular\n"
    "NSE,2026-11-10,false,holiday\n"
    "NSE,2026-11-11,true,regular\n"
)


class ExchangeCalendarImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = DuckDBRepository()

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    def file(self, name: str, content: str) -> Path:
        path = self.root / name
        path.write_text(content, encoding="utf-8", newline="")
        return path

    def spec(self, exchange: str, version: str, *, source_identifier: str | None = None,
             publication_date: date = date(2026, 11, 8), published_at=None) -> CalendarImportSpec:
        return CalendarImportSpec(
            exchange=exchange, calendar_version=version,
            source_identifier=source_identifier or f"official://{exchange}/calendar/2026",
            source_document_date=date(2026, 11, 8), publication_date=publication_date,
            published_at=published_at, parser_version="calendar-csv-v1", retention_authorized=True,
        )

    def import_file(self, path: Path, exchange="NSE", version="nse-2026-r1", **spec_options):
        return import_exchange_calendar(
            self.repo, path, archive_root=self.root / "archive",
            spec=self.spec(exchange, version, **spec_options),
        )

    def test_schema_v3_and_imported_session_kinds_are_venue_specific(self):
        nse = self.file("nse.csv", HEADERS + ROWS_V1)
        report = self.import_file(nse)
        self.assertEqual(report.accepted, 4)
        self.assertEqual(self.repo._connection.execute(
            "SELECT current_version FROM schema_metadata WHERE schema_name='hamsa_analytics'"
        ).fetchone()[0], self.repo.SCHEMA_VERSION)
        self.assertEqual(self.repo._connection.execute(
            "SELECT session_type,is_trading_session FROM exchange_trading_session WHERE exchange='NSE' AND session_date=DATE '2026-11-08' AND calendar_version='nse-2026-r1'"
        ).fetchone(), ("special", True))
        self.assertEqual(self.repo._connection.execute(
            "SELECT session_type,is_trading_session FROM exchange_trading_session WHERE exchange='NSE' AND session_date=DATE '2026-11-10' AND calendar_version='nse-2026-r1'"
        ).fetchone(), ("holiday", False))

        bse_content = ROWS_V1.replace("NSE,", "BSE,")
        bse = self.file("bse.csv", HEADERS + bse_content)
        bse_report = self.import_file(bse, exchange="BSE", version="bse-2026-r1")
        self.assertEqual(bse_report.accepted, 4)
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM exchange_trading_session WHERE exchange='NSE' AND calendar_version='bse-2026-r1'"
        ).fetchone()[0], 0)

    def test_duplicate_import_is_idempotent_and_archive_checksum_is_preserved(self):
        path = self.file("nse.csv", HEADERS + ROWS_V1)
        first = self.import_file(path)
        retry = self.import_file(path)
        self.assertEqual(first.accepted, 4)
        self.assertEqual(retry.duplicates, 4)
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM exchange_trading_session WHERE exchange='NSE' AND calendar_version='nse-2026-r1'"
        ).fetchone()[0], 4)
        stored = self.repo._connection.execute(
            """SELECT r.checksum_sha256,r.archive_path,d.source_document_id
               FROM raw_source_file r JOIN source_document_revision d USING(source_file_id)
               WHERE d.source_document_id=?""", [first.source_document_id]
        ).fetchone()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), stored[0])
        archived = Path(stored[1])
        self.assertTrue(archived.is_file())
        self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(), stored[0])
        self.assertEqual(stored[2], first.source_document_id)

    def test_conflicting_same_version_is_rejected_without_overwrite(self):
        original = self.file("nse.csv", HEADERS + ROWS_V1)
        first = self.import_file(original)
        changed_content = ROWS_V1.replace("NSE,2026-11-10,false,holiday", "NSE,2026-11-10,true,special")
        changed = self.file("changed.csv", HEADERS + changed_content)
        with self.assertRaisesRegex(RepositoryIntegrityError, "choose a new version"):
            self.import_file(changed)
        rows = self.repo._connection.execute(
            "SELECT session_date,is_trading_session,session_type,source_document_id FROM exchange_trading_session WHERE exchange='NSE' AND calendar_version='nse-2026-r1' ORDER BY session_date"
        ).fetchall()
        self.assertEqual(rows[2], (date(2026, 11, 10), False, "holiday", first.source_document_id))

    def test_new_version_preserves_old_and_is_selected_explicitly(self):
        original = self.file("nse.csv", HEADERS + ROWS_V1)
        self.import_file(original)
        v2_rows = ROWS_V1.replace("NSE,2026-11-10,false,holiday", "NSE,2026-11-10,true,special")
        revised = self.file("nse-revised.csv", HEADERS + v2_rows)
        self.import_file(revised, version="nse-2026-r2")
        v1 = RepositoryExchangeCalendar(self.repo, exchange="NSE", version="nse-2026-r1")
        v2 = RepositoryExchangeCalendar(self.repo, exchange="NSE", version="nse-2026-r2")
        self.assertFalse(v1.is_trading_session(date(2026, 11, 10)))
        self.assertTrue(v2.is_trading_session(date(2026, 11, 10)))
        self.assertEqual(v1.next_trading_session(date(2026, 11, 9)), date(2026, 11, 11))
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM exchange_trading_session WHERE exchange='NSE' AND session_date=DATE '2026-11-10'"
        ).fetchone()[0], 2)

    def test_wrong_venue_invalid_rows_and_gaps_fail_closed(self):
        wrong = self.file("wrong.csv", HEADERS + ROWS_V1.replace("NSE,", "BSE,"))
        with self.assertRaisesRegex(RepositoryIntegrityError, "does not match requested"):
            self.import_file(wrong, exchange="NSE")
        malformed_rows = (
            "NSE,2026-11-08,true,regular\n"  # a special session must be explicitly classified
            "NSE,2026-11-09,false,regular\n"
        )
        malformed = self.file("malformed.csv", HEADERS + malformed_rows)
        with self.assertRaises(RepositoryIntegrityError):
            parse_calendar_csv(malformed, expected_exchange="NSE")
        gap = self.file("gap.csv", HEADERS + "NSE,2026-11-08,true,special\nNSE,2026-11-10,false,holiday\n")
        with self.assertRaisesRegex(RepositoryIntegrityError, "missing dates"):
            parse_calendar_csv(gap, expected_exchange="NSE")

    def test_missing_dates_and_unknown_versions_fail_closed(self):
        path = self.file("nse.csv", HEADERS + ROWS_V1)
        self.import_file(path)
        calendar = RepositoryExchangeCalendar(self.repo, exchange="NSE", version="nse-2026-r1")
        self.assertFalse(calendar.is_trading_session(date(2026, 11, 12)))
        with self.assertRaisesRegex(RepositoryIntegrityError, "no later explicit"):
            calendar.next_trading_session(date(2026, 11, 11))
        with self.assertRaisesRegex(RepositoryIntegrityError, "missing or has unverified"):
            RepositoryExchangeCalendar(self.repo, exchange="BSE", version="nse-2026-r1")

    def test_calendar_source_availability_respects_public_and_hamsa_known_cutoffs(self):
        path = self.file("nse.csv", HEADERS + ROWS_V1)
        report = self.import_file(
            path, publication_date=date(2026, 11, 8),
            published_at=datetime(2026, 11, 8, 16, 0, tzinfo=MARKET_TIMEZONE),
        )
        pre_close = datetime(2026, 11, 8, 15, 30, tzinfo=MARKET_TIMEZONE)
        next_session = datetime(2026, 11, 9, 15, 30, tzinfo=MARKET_TIMEZONE)
        self.assertFalse(self.repo._source_available(
            report.source_document_id, exchange="NSE", screen_date=date(2026, 11, 8), cutoff=pre_close,
            availability_mode="public_as_of", calendar_version="nse-2026-r1",
        ))
        self.assertTrue(self.repo._source_available(
            report.source_document_id, exchange="NSE", screen_date=date(2026, 11, 9), cutoff=next_session,
            availability_mode="public_as_of", calendar_version="nse-2026-r1",
        ))
        self.assertFalse(self.repo._source_available(
            report.source_document_id, exchange="NSE", screen_date=date(2026, 11, 9), cutoff=next_session,
            availability_mode="hamsa_known_as_of", calendar_version="nse-2026-r1",
        ))

    def test_archive_before_parse_failure_can_be_retried_without_partial_sessions(self):
        original = self.file(
            "official-calendar.csv",
            HEADERS + "NSE,2026-11-08,true,regular\nNSE,2026-11-09,false,regular\n",
        )
        spec = self.spec("NSE", "nse-2026-retry-r1")
        with self.assertRaises(RepositoryIntegrityError):
            import_exchange_calendar(
                self.repo, original, archive_root=self.root / "archive", spec=spec,
            )
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM exchange_trading_session").fetchone()[0], 0)
        archived_source_count = self.repo._connection.execute("SELECT count(*) FROM raw_source_file").fetchone()[0]
        self.assertEqual(archived_source_count, 1)

        self.file("official-calendar.csv", HEADERS + ROWS_V1)
        retry = import_exchange_calendar(
            self.repo, original, archive_root=self.root / "archive", spec=spec,
        )
        self.assertEqual(retry.accepted, 4)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM raw_source_file").fetchone()[0], 2)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM source_document_revision").fetchone()[0], 2)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM exchange_trading_session").fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main()
