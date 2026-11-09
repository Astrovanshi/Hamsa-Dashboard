from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hamsa.domain.financials import QualityStatus
from hamsa.domain.source import SourceDocumentRevision, is_exact_duplicate
from hamsa.ingestion.quality import (
    StalenessWindow,
    apply_staleness,
    convert_unit,
    quality_for_value,
)
from hamsa.ingestion.raw_archive import archive_approved_source


IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def source_doc(source_id, checksum, revision=1, dataset="filings"):
    return SourceDocumentRevision(
        source_document_id=f"doc-{source_id}-{revision}",
        provider="exchange",
        dataset=dataset,
        source_identifier=source_id,
        source_file_id=f"file-{revision}",
        checksum_sha256=checksum,
        revision_number=revision,
        source_document_date=date(2024, 1, 1),
        publication_date=date(2024, 1, 2),
        published_at=datetime(2024, 1, 2, 12, tzinfo=IST),
        ingestion_timestamp=datetime(2024, 1, 2, 13, tzinfo=IST),
        parser_version="parser-2.1",
        extraction_timestamp=datetime(2024, 1, 2, 13, 1, tzinfo=IST),
        extraction_locator="page:4/table:2/row:7",
        supersedes_source_document_id=f"doc-{source_id}-{revision - 1}" if revision > 1 else None,
    )


class FilingRevisionTests(unittest.TestCase):
    def test_exact_source_duplicate_is_idempotent_but_changed_checksum_is_revision(self):
        original = source_doc("filing-17", "a" * 64)
        duplicate = source_doc("filing-17", "a" * 64)
        correction = source_doc("filing-17", "b" * 64, revision=2)
        different_dataset = source_doc("filing-17", "a" * 64, dataset="announcements")
        self.assertTrue(is_exact_duplicate(original, duplicate))
        self.assertFalse(is_exact_duplicate(original, correction))
        self.assertFalse(is_exact_duplicate(original, different_dataset))

    def test_document_record_carries_checksum_parser_and_extraction_location(self):
        document = source_doc("filing-18", "c" * 64)
        self.assertEqual(len(document.checksum_sha256), 64)
        self.assertEqual(document.parser_version, "parser-2.1")
        self.assertEqual(document.extraction_locator, "page:4/table:2/row:7")
        self.assertIsNotNone(document.extraction_timestamp)


class RawArchiveTests(unittest.TestCase):
    def test_archive_is_content_addressed_and_idempotent(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.csv"
            source.write_bytes(b"synthetic,eod\n1,2\n")
            first = archive_approved_source(source, archive_root=root / "raw", license_status="approved")
            second = archive_approved_source(source, archive_root=root / "raw", license_status="approved")
            self.assertEqual(first.sha256_hex, second.sha256_hex)
            self.assertEqual(first.archive_path, second.archive_path)
            self.assertEqual(first.archive_path.read_bytes(), source.read_bytes())
            self.assertEqual(source.read_bytes(), b"synthetic,eod\n1,2\n")

    def test_unapproved_retention_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.csv"
            source.write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "not approved"):
                archive_approved_source(source, archive_root=root / "raw", license_status="pending")
            self.assertFalse((root / "raw").exists())


class QualityAndUnitTests(unittest.TestCase):
    def test_null_is_missing_and_never_becomes_zero(self):
        self.assertEqual(quality_for_value(None), QualityStatus.MISSING)
        self.assertIsNone(None)
        self.assertEqual(quality_for_value(Decimal("0")), QualityStatus.OBSERVED)

    def test_stale_and_invalid_are_distinct_from_missing(self):
        window = StalenessWindow("revenue", "company_filing", 365)
        self.assertEqual(apply_staleness(
            QualityStatus.OBSERVED,
            observation_date=date(2023, 1, 1), as_of_date=date(2024, 1, 5), window=window,
        ), QualityStatus.STALE)
        self.assertEqual(apply_staleness(
            QualityStatus.MISSING,
            observation_date=date(2023, 1, 1), as_of_date=date(2024, 1, 5), window=window,
        ), QualityStatus.MISSING)
        self.assertEqual(apply_staleness(
            QualityStatus.OBSERVED,
            observation_date=date(2024, 1, 6), as_of_date=date(2024, 1, 5), window=window,
        ), QualityStatus.INVALID)

    def test_documented_compatible_unit_conversion_preserves_expected_value(self):
        converted = convert_unit(
            Decimal("12.5"), raw_unit="INR crore", canonical_unit="INR",
            multiplier=Decimal("10000000"), additive_offset=Decimal("0"),
            rule_documented=True, units_compatible=True,
        )
        self.assertEqual(converted, Decimal("125000000.0"))

    def test_incompatible_or_undocumented_unit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "undocumented or incompatible"):
            convert_unit(
                Decimal("7"), raw_unit="unknown", canonical_unit="INR",
                multiplier=Decimal("1"), rule_documented=False, units_compatible=False,
            )


if __name__ == "__main__":
    unittest.main()
