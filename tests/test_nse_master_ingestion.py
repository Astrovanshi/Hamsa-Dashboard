from __future__ import annotations

import csv
import gzip
from datetime import date, datetime
import hashlib
from pathlib import Path
import tempfile
import unittest

from hamsa.domain.security import is_valid_isin
from hamsa.ingestion.exchange_master import (
    RawMasterRow,
    decode_nse_master_time,
    ingest_nse_mii_file,
    intake_master_snapshot,
    nse_snapshot_date_from_filename,
    parse_nse_mii_master,
)
from hamsa.storage.duckdb_repository import DuckDBRepository


ROOT = Path(__file__).resolve().parents[1]


class NseMasterIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = DuckDBRepository(self.root / "test.duckdb")

    def tearDown(self):
        self.repo.close()
        self.temp.cleanup()

    @staticmethod
    def _write_mii(path: Path, records: list[dict[str, str]]) -> bytes:
        fields = ["FinInstrmId", "TckrSymb", "SctySrs", "FinInstrmNm", "ISIN",
                  "DelFlg", "SctyStsNrmlMkt", "ElgbltyNrmlMkt", "PrtdToTrad", "ListgDt", "UpdDt"]
        text = []
        import io
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
        content = gzip.compress(out.getvalue().encode("utf-8"), mtime=0)
        path.write_bytes(content)
        return content

    @staticmethod
    def _row(locator: str, instrument_id: str, symbol: str, isin: str | None,
             *, deleted: str = "N") -> RawMasterRow:
        fields = {
            "FinInstrmId": instrument_id, "TckrSymb": symbol, "SctySrs": "EQ",
            "FinInstrmNm": symbol, "ISIN": isin or "", "DelFlg": deleted,
        }
        return RawMasterRow("NSE", instrument_id, isin, symbol, "EQ", None, fields, locator)

    def test_nse_clock_epoch_and_filename_date_are_separate(self):
        self.assertEqual(decode_nse_master_time("1478723487"), datetime(2026, 11, 9, 20, 31, 27))
        self.assertIsNone(decode_nse_master_time("0"))
        self.assertIsNone(decode_nse_master_time("bad"))
        self.assertEqual(nse_snapshot_date_from_filename(Path("NSE_CM_security_09112026 (2).csv.gz")), date(2026, 11, 9))
        self.assertTrue(is_valid_isin("INE062A01020"))

    def test_unresolved_deleted_test_conflicting_and_malformed_rows_are_retained(self):
        path = self.root / "NSE_CM_security_09112026.csv.gz"
        self._write_mii(path, [{
            "FinInstrmId": "100", "TckrSymb": "UNMAPPED", "SctySrs": "EQ", "FinInstrmNm": "UNMAPPED",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "1", "ElgbltyNrmlMkt": "1",
            "PrtdToTrad": "1", "ListgDt": "478483200", "UpdDt": "1478723487",
        }, {
            "FinInstrmId": "101", "TckrSymb": "DELETED", "SctySrs": "EQ", "FinInstrmNm": "DELETED",
            "ISIN": "INE062A01020", "DelFlg": "Y", "SctyStsNrmlMkt": "3", "ElgbltyNrmlMkt": "0",
            "PrtdToTrad": "0", "ListgDt": "478483200", "UpdDt": "1478723487",
        }, {
            "FinInstrmId": "102", "TckrSymb": "011NSETEST", "SctySrs": "EQ", "FinInstrmNm": "011NSETEST",
            "ISIN": "DUMMYSAN005", "DelFlg": "N", "SctyStsNrmlMkt": "1", "ElgbltyNrmlMkt": "0",
            "PrtdToTrad": "0", "ListgDt": "0", "UpdDt": "1478723487",
        }])
        source = __import__("hamsa.ingestion.source_registry", fromlist=["register_local_exchange_source"]).register_local_exchange_source(
            self.repo, path, archive_root=self.root / "archive", exchange="NSE", dataset="CM-MII-security",
            source_identifier="NSE_CM_security_09112026", source_document_date=date(2026, 11, 9),
            publication_date=date(2026, 11, 11), parser_version="test-parser-v1", retention_authorized=True,
        )
        rows = (
            self._row("csv:line:2", "10", "UNMAPPED", "INE062A01020"),
            self._row("csv:line:3", "11", "INVALID", "DUMMYSAN005"),
            self._row("csv:line:4", "12", "DELETED", "INE062A01020", deleted="Y"),
            self._row("csv:line:5", "13", "ABCNSETEST", "INE062A01020"),
            self._row("csv:line:6", "14", "CONFLICT_A", "INE062A01020"),
            self._row("csv:line:7", "14", "CONFLICT_B", "INE009A01021"),
            self._row("csv:line:8", "", "", "INE062A01020"),
        )
        report = intake_master_snapshot(self.repo, source_document_id=source.source_document_id,
                                        source_snapshot_date=date(2026, 11, 9), parser_version="test-parser-v1", rows=rows)
        self.assertEqual(report.accepted_records, 0)
        self.assertEqual(report.unresolved_records, 2)
        self.assertEqual(report.deleted_records, 1)
        self.assertEqual(report.out_of_scope_records, 1)
        self.assertEqual(report.conflicting_records, 2)
        self.assertEqual(report.rejected_records, 1)
        self.assertEqual(report.quarantined, 7)
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM exchange_listing_revision").fetchone()[0], 0)
        reasons = {row[0] for row in self.repo._connection.execute(
            "SELECT DISTINCT reason_code FROM observation_quarantine").fetchall()}
        self.assertEqual(reasons, {
            "missing_or_ambiguous_exchange_instrument_mapping", "missing_or_invalid_isin_identity",
            "source_deleted_flag", "documented_test_instrument", "conflicting_duplicate_exchange_instrument_id",
            "malformed_required_identity_fields",
        })

    def test_documented_nontrading_and_exchange_exclusive_flags_are_quarantined(self):
        source_path = self.root / "NSE_CM_security_09112026.csv.gz"
        self._write_mii(source_path, [{
            "FinInstrmId": "1", "TckrSymb": "BSEONLY", "SctySrs": "EQ", "FinInstrmNm": "BSEONLY",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "1", "ElgbltyNrmlMkt": "0",
            "PrtdToTrad": "2", "ListgDt": "478483200", "UpdDt": "1478723487",
        }, {
            "FinInstrmId": "2", "TckrSymb": "SUSPENDED", "SctySrs": "EQ", "FinInstrmNm": "SUSPENDED",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "3", "ElgbltyNrmlMkt": "0",
            "PrtdToTrad": "1", "ListgDt": "478483200", "UpdDt": "1478723487",
        }, {
            "FinInstrmId": "3", "TckrSymb": "NO_TRADE", "SctySrs": "EQ", "FinInstrmNm": "NO_TRADE",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "1", "ElgbltyNrmlMkt": "0",
            "PrtdToTrad": "0", "ListgDt": "478483200", "UpdDt": "1478723487",
        }])
        from hamsa.ingestion.source_registry import register_local_exchange_source
        source = register_local_exchange_source(
            self.repo, source_path, archive_root=self.root / "archive", exchange="NSE", dataset="CM-MII-security",
            source_identifier="NSE_CM_security_09112026", source_document_date=date(2026, 11, 9),
            publication_date=date(2026, 11, 11), parser_version="test-parser-v1", retention_authorized=True,
        )
        rows = parse_nse_mii_master(source_path)
        report = intake_master_snapshot(self.repo, source_document_id=source.source_document_id,
                                        source_snapshot_date=date(2026, 11, 9), parser_version="test-parser-v1", rows=rows)
        self.assertEqual(report.out_of_scope_records, 3)
        self.assertEqual(report.exchange_exclusive_records, 1)
        self.assertEqual(report.suspended_records, 1)
        self.assertEqual(report.not_permitted_records, 1)
        self.assertEqual(report.unresolved_records, 0)
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM observation_quarantine").fetchone()[0], 3)

    def test_archive_first_idempotency_revisions_and_parser_history(self):
        path1 = self.root / "NSE_CM_security_09112026 (1).csv.gz"
        path2 = self.root / "NSE_CM_security_09112026 (2).csv.gz"
        bytes1 = self._write_mii(path1, [{
            "FinInstrmId": "100", "TckrSymb": "SBIN", "SctySrs": "EQ", "FinInstrmNm": "STATE BANK",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "6", "ElgbltyNrmlMkt": "1",
            "PrtdToTrad": "1", "ListgDt": "478483200", "UpdDt": "1478723487",
        }])
        first = ingest_nse_mii_file(self.repo, path1, archive_root=self.root / "archive",
                                    source_snapshot_date=date(2026, 11, 9), parser_version="nse-v1",
                                    retention_authorized=True)
        self.assertEqual(Path(first.source.archive_path).read_bytes(), bytes1)
        self.assertEqual(first.source.revision_number, 1)
        self.assertEqual(first.report.unresolved_records, 1)
        metadata = self.repo._connection.execute(
            "SELECT metadata_json FROM raw_source_file WHERE source_file_id=?", [first.source.source_file_id]
        ).fetchone()[0]
        self.assertIn("user-supplied; official origin not independently authenticated", metadata)
        retry = ingest_nse_mii_file(self.repo, path1, archive_root=self.root / "archive",
                                    source_snapshot_date=date(2026, 11, 9), parser_version="nse-v1",
                                    retention_authorized=True)
        self.assertEqual(retry.report.duplicates, 1)
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM observation_quarantine").fetchone()[0], 1)
        reparsed = ingest_nse_mii_file(self.repo, path1, archive_root=self.root / "archive",
                                       source_snapshot_date=date(2026, 11, 9), parser_version="nse-v2",
                                       retention_authorized=True)
        self.assertEqual(reparsed.source.source_document_id, first.source.source_document_id)
        self.assertEqual(reparsed.source.revision_number, first.source.revision_number)
        self.assertEqual(self.repo._connection.execute(
            "SELECT count(*) FROM observation_quarantine").fetchone()[0], 2)
        self._write_mii(path2, [{
            "FinInstrmId": "100", "TckrSymb": "SBIN", "SctySrs": "EQ", "FinInstrmNm": "STATE BANK",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "6", "ElgbltyNrmlMkt": "1",
            "PrtdToTrad": "1", "ListgDt": "478483200", "UpdDt": "1478723488",
        }])
        changed = ingest_nse_mii_file(self.repo, path2, archive_root=self.root / "archive",
                                      source_snapshot_date=date(2026, 11, 9), parser_version="nse-v1",
                                      retention_authorized=True)
        self.assertEqual(changed.source.revision_number, 2)
        names = self.repo._connection.execute(
            "SELECT original_filename FROM raw_source_file ORDER BY original_filename").fetchall()
        self.assertEqual({row[0] for row in names}, {path1.name, path2.name})
        docs = self.repo._connection.execute(
            "SELECT revision_number,source_document_date,publication_date,published_at FROM source_document_revision ORDER BY revision_number"
        ).fetchall()
        self.assertEqual(docs, [(1, date(2026, 11, 9), docs[0][2], None), (2, date(2026, 11, 9), docs[1][2], None)])
        parser_revisions = self.repo._connection.execute(
            """SELECT d.revision_number,p.parser_version,p.status
               FROM source_document_processing_revision p JOIN source_document_revision d USING(source_document_id)
               ORDER BY d.revision_number,p.parser_version"""
        ).fetchall()
        self.assertEqual(parser_revisions, [
            (1, "nse-v1", "succeeded"), (1, "nse-v2", "succeeded"), (2, "nse-v1", "succeeded")
        ])

    def test_malformed_file_is_archived_and_failed_processing_is_recorded(self):
        path = self.root / "NSE_CM_security_09112026.csv.gz"
        path.write_bytes(b"not-gzip")
        with self.assertRaises(Exception):
            ingest_nse_mii_file(self.repo, path, archive_root=self.root / "archive",
                                source_snapshot_date=date(2026, 11, 9), parser_version="nse-v1",
                                retention_authorized=True)
        archived = self.repo._connection.execute("SELECT archive_path,checksum_sha256 FROM raw_source_file").fetchone()
        self.assertEqual(Path(archived[0]).read_bytes(), b"not-gzip")
        self.assertEqual(hashlib.sha256(Path(archived[0]).read_bytes()).hexdigest(), archived[1])
        self.assertEqual(self.repo._connection.execute(
            "SELECT status,accepted_count,quarantined_count FROM source_document_processing_revision"
        ).fetchone(), ("failed", 0, 0))
        self.assertEqual(self.repo._connection.execute("SELECT count(*) FROM observation_quarantine").fetchone()[0], 0)

    def test_parser_preserves_all_source_fields_and_extraction_line(self):
        path = self.root / "NSE_CM_security_09112026.csv.gz"
        self._write_mii(path, [{
            "FinInstrmId": "55", "TckrSymb": "ABC", "SctySrs": "EQ", "FinInstrmNm": "ABC LTD",
            "ISIN": "INE062A01020", "DelFlg": "N", "SctyStsNrmlMkt": "2", "ElgbltyNrmlMkt": "1",
            "PrtdToTrad": "1", "ListgDt": "478483200", "UpdDt": "1478723487",
        }])
        row = parse_nse_mii_master(path)[0]
        self.assertEqual(row.exchange_instrument_id, "55")
        self.assertEqual(row.isin, "INE062A01020")
        self.assertEqual(row.source_fields["UpdDt"], "1478723487")
        self.assertEqual(row.source_fields["ListgDt"], "478483200")
        self.assertEqual(row.extraction_locator, "csv:line:2")

    def test_nse_listed_prtdtotrad_zero_with_normal_market_eligibility_is_accepted_when_mapped(self):
        path = self.root / "NSE_CM_security_09112026.csv.gz"
        self._write_mii(path, [{
            "FinInstrmId": "3045", "TckrSymb": "SBIN", "SctySrs": "EQ",
            "FinInstrmNm": "STATE BANK OF INDIA", "ISIN": "INE062A01020",
            "DelFlg": "N", "SctyStsNrmlMkt": "6", "ElgbltyNrmlMkt": "1",
            "PrtdToTrad": "0", "ListgDt": "478483200", "UpdDt": "1478723487",
        }])
        from hamsa.ingestion.source_registry import register_local_exchange_source
        source = register_local_exchange_source(
            self.repo, path, archive_root=self.root / "archive", exchange="NSE",
            dataset="CM-MII-security", source_identifier="NSE_CM_security_09112026",
            source_document_date=date(2026, 11, 9), publication_date=date(2026, 11, 11),
            parser_version="test-parser-v1", retention_authorized=True,
        )
        res = self.repo.append_security_identity_candidate(
            issuer_entity_id="issuer-sbin", security_id="sec-sbin", listing_id="listing-nse-sbin",
            exchange="NSE", exchange_instrument_id="3045", isin="INE062A01020",
            legal_name="State Bank of India", identity_observed_from=date(1995, 3, 1),
            source_document_id=source.source_document_id, source_locator="csv:line:2",
        )
        self.repo.append_security_identifier_review(
            identifier_revision_id=res["identifier_revision_id"], review_status="approved",
            reviewer="analyst", reviewer_actor_type="human",
            evidence_source_document_id=source.source_document_id, evidence_locator="csv:line:2",
            rationale="Verified NSE MII SBIN identity",
        )
        rows = parse_nse_mii_master(path)
        report = intake_master_snapshot(
            self.repo, source_document_id=source.source_document_id,
            source_snapshot_date=date(2026, 11, 9), parser_version="test-parser-v1", rows=rows,
        )
        self.assertEqual(report.accepted_records, 1)
        self.assertEqual(report.not_permitted_records, 0)
        self.assertEqual(report.quarantined, 0)


if __name__ == "__main__":
    unittest.main()
