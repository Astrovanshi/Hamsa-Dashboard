"""Offline, bounded importer for raw TejHQ NSE/BSE EOD Parquet partitions.

The source is secondary and does not establish security identity or universe
eligibility. The importer requires reviewed HAMSA mappings and classification;
unresolved source rows are quarantined without a price observation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

import duckdb

from hamsa.ingestion.raw_archive import archive_user_authorized_source
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


_REQUIRED_COLUMNS = {
    "date", "symbol", "series", "isin", "open", "high", "low", "close", "volume", "turnover", "year", "month",
}
_IMMUTABLE_REVISION = re.compile(r"^[0-9a-fA-F]{7,40}$")
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")
_PARSER_VERSION = "tejhq-parquet-v1"
_COMPARATOR_VERSION = "eod-raw-ohlcv-turnover-v1"


@dataclass(frozen=True, slots=True)
class TejHQPartition:
    path: Path
    exchange: str
    dataset_id: str
    dataset_revision: str
    original_dataset_path: str
    source_document_date: date
    first_verified_public_date: date
    retrieval_date: date
    retrieved_at: datetime | None = None
    parser_version: str = _PARSER_VERSION
    provider: str = "TejHQ"

    def __post_init__(self) -> None:
        if self.exchange not in ("NSE", "BSE"):
            raise ValueError("exchange must be NSE or BSE")
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        if not self.dataset_id.strip() or not self.original_dataset_path.strip():
            raise ValueError("dataset_id and original_dataset_path are required")
        if self.first_verified_public_date > self.retrieval_date:
            raise ValueError("first verified public date cannot be later than local retrieval date")
        if not _IMMUTABLE_REVISION.fullmatch(self.dataset_revision):
            raise ValueError("dataset_revision must be an immutable Git commit identifier, not a branch or tag")
        normalized_path = self.original_dataset_path.replace("\\", "/").lower()
        if not normalized_path.startswith(f"{self.exchange.lower()}/"):
            raise ValueError("original_dataset_path must identify the matching raw exchange partition")
        if "/delivery/" in normalized_path or "adjust" in normalized_path:
            raise ValueError("only raw price partitions are supported; delivery and adjusted data are excluded")
        if not self.parser_version.strip():
            raise ValueError("parser_version is required")
        if self.provider != "TejHQ":
            raise ValueError("this adapter records only the TejHQ secondary dataset")
        if self.retrieved_at is not None and (self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None):
            raise ValueError("retrieved_at must be timezone-aware when supplied")


@dataclass(frozen=True, slots=True)
class TejHQRow:
    row_number: int
    trade_date: date
    symbol: str | None
    series: str | None
    isin: str | None
    open: Any
    high: Any
    low: Any
    close: Any
    volume: Any
    turnover: Any
    source_year: int
    source_month: int

    @property
    def locator(self) -> str:
        return f"parquet:file_row_number:{self.row_number}"


@dataclass(slots=True)
class TejHQIngestionReport:
    provider: str
    dataset_id: str
    dataset_revision: str
    source_identifier: str
    checksum_sha256: str
    schema_fingerprint: str
    parser_version: str
    accepted: int = 0
    rejected: int = 0
    quarantined: int = 0
    duplicates: int = 0
    revised: int = 0
    out_of_scope: int = 0
    reconciled: int = 0
    not_compared: int = 0
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider, "dataset_id": self.dataset_id,
            "dataset_revision": self.dataset_revision, "source_identifier": self.source_identifier,
            "checksum_sha256": self.checksum_sha256, "schema_fingerprint": self.schema_fingerprint,
            "parser_version": self.parser_version, "accepted": self.accepted, "rejected": self.rejected,
            "quarantined": self.quarantined, "duplicates": self.duplicates, "revised": self.revised,
            "out_of_scope": self.out_of_scope, "reconciled": self.reconciled,
            "not_compared": self.not_compared, "error": self.error,
        }


class TejHQParquetImporter:
    """Read local Parquet files with DuckDB and append vetted EOD observations."""

    def __init__(self, repository: DuckDBRepository, *, archive_root: Path,
                 test_mode: bool = False, fault_hook=None):
        if fault_hook is not None and not test_mode:
            raise ValueError("fault injection is restricted to explicit test_mode")
        self.repository = repository
        self.archive_root = archive_root
        self._connection = duckdb.connect(":memory:")
        self._test_mode = test_mode
        self._fault_hook = fault_hook

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "TejHQParquetImporter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    @staticmethod
    def _sql_path(path: Path) -> str:
        return str(path.resolve())

    def inspect_schema(self, partition: TejHQPartition) -> tuple[tuple[str, str], ...]:
        rows = self._connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, file_row_number=true)",
            [self._sql_path(partition.path)],
        ).fetchall()
        schema = tuple((str(row[0]), str(row[1]).upper()) for row in rows if row[0] != "file_row_number")
        columns = [name for name, _ in schema]
        if len(columns) != len(set(columns)):
            raise ValueError("Parquet schema contains duplicate column names")
        missing = _REQUIRED_COLUMNS.difference(columns)
        if missing:
            raise ValueError(f"TejHQ raw price schema missing columns: {', '.join(sorted(missing))}")
        types = dict(schema)
        if types["date"] != "DATE":
            raise ValueError("TejHQ date column must be a Parquet DATE")
        for name in ("symbol", "series", "isin"):
            if types[name] != "VARCHAR":
                raise ValueError(f"TejHQ {name} column must be VARCHAR")
        for name in ("open", "high", "low", "close", "volume", "turnover"):
            if types[name] not in {"DOUBLE", "FLOAT", "BIGINT", "INTEGER", "DECIMAL"}:
                raise ValueError(f"unsupported TejHQ {name} type: {types[name]}")
        if types["year"] not in {"INTEGER", "BIGINT", "SMALLINT"} or types["month"] not in {"TINYINT", "SMALLINT", "INTEGER", "BIGINT"}:
            raise ValueError("TejHQ year/month partition fields must be integral")
        return schema

    def read_rows(
        self,
        partition: TejHQPartition,
        *,
        trade_date: date,
        symbols: Sequence[str],
    ) -> tuple[tuple[tuple[str, str], ...], list[TejHQRow]]:
        if not symbols or len(symbols) > 10 or any(not value.strip() for value in symbols):
            raise ValueError("pilot requires 1 to 10 explicit symbols for one session")
        schema = self.inspect_schema(partition)
        placeholders = ",".join("?" for _ in symbols)
        raw_rows = self._connection.execute(
            f"""SELECT file_row_number,date,symbol,series,isin,open,high,low,close,volume,turnover,year,month
                FROM read_parquet(?,file_row_number=true)
                WHERE date=? AND upper(symbol) IN ({placeholders})
                ORDER BY file_row_number""",
            [self._sql_path(partition.path), trade_date, *(s.upper() for s in symbols)],
        ).fetchall()
        for row in raw_rows:
            if int(row[11]) != row[1].year or int(row[12]) != row[1].month:
                raise ValueError(f"Parquet year/month values disagree with date at row {row[0]}")
        path_text = partition.original_dataset_path.replace("\\", "/")
        match = re.search(r"(?:^|/)year=(\d{4})(?:/|$)", path_text)
        if match and int(match.group(1)) != trade_date.year:
            raise ValueError("dataset partition year disagrees with requested trade date")
        parsed = [TejHQRow(
            int(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10],
            int(row[11]), int(row[12]),
        ) for row in raw_rows]
        return schema, parsed

    @staticmethod
    def _id(prefix: str, *parts: object) -> str:
        return prefix + "-" + sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _schema_fingerprint(schema: Sequence[tuple[str, str]]) -> str:
        body = json.dumps(list(schema), separators=(",", ":"), ensure_ascii=False)
        return sha256(body.encode("utf-8")).hexdigest()

    @staticmethod
    def _file_checksum(path: Path) -> str:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _manifest_path(self, *, checksum: str, partition: TejHQPartition, trade_date: date,
                       symbols: Sequence[str]) -> Path:
        identity = "|".join((partition.provider, partition.dataset_id, partition.dataset_revision,
                             partition.original_dataset_path, checksum, partition.parser_version,
                             trade_date.isoformat(), ",".join(sorted(s.upper() for s in symbols))))
        manifest_id = sha256(identity.encode("utf-8")).hexdigest()
        return self.archive_root / "_manifests" / f"{manifest_id}.json"

    @staticmethod
    def _write_manifest(path: Path, manifest: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def _register_source(
        self, partition: TejHQPartition, checksum: str, archive_path: str,
        schema_fingerprint: str, captured_at: datetime, ingested_at: datetime,
    ) -> tuple[str, str, int, str | None, bool]:
        con = self.repository._connection
        original_path = partition.original_dataset_path.replace("\\", "/")
        # Bind the source identifier to an immutable upstream revision. This
        # makes identical bytes from distinct dataset commits traceable without
        # treating them as one undocumented mutable `main` source.
        source_identifier = f"{original_path}@{partition.dataset_revision}"
        provider, dataset = partition.provider, partition.dataset_id
        source_file_id = f"raw-{checksum}"
        metadata = {
            "source_kind": "secondary_normalized_dataset", "dataset_id": partition.dataset_id,
            "dataset_revision": partition.dataset_revision, "original_dataset_path": original_path,
            "retrieval_date": partition.retrieval_date.isoformat(),
            "retrieval_date_precision": "date_only" if partition.retrieved_at is None else "timestamp",
            "retrieved_at": partition.retrieved_at.isoformat() if partition.retrieved_at else None,
            "first_verified_public_date": partition.first_verified_public_date.isoformat(),
            "archive_captured_at": captured_at.isoformat(),
            "schema_fingerprint": schema_fingerprint, "parser_version": partition.parser_version,
            "exchange": partition.exchange,
        }
        with self.repository._transaction():
            existing_file = con.execute(
                "SELECT source_file_id,archive_path FROM raw_source_file WHERE checksum_sha256=?", [checksum]
            ).fetchone()
            if existing_file is None:
                con.execute(
                    """INSERT INTO raw_source_file
                       (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
                        source_as_of_date,license_review_reference,license_status,metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,'pending',?)""",
                    [source_file_id, provider, dataset, Path(original_path).name, checksum, archive_path, captured_at,
                     partition.source_document_date, "TejHQ-terms-not-reviewed; local retention user-authorized",
                     json.dumps(metadata, sort_keys=True)],
                )
            else:
                source_file_id, archive_path = existing_file
            if self._fault_hook is not None:
                self._fault_hook("after_raw_file_registration_before_source_document")
            same_bytes = con.execute(
                """SELECT source_document_id,revision_number FROM source_document_revision
                   WHERE provider=? AND dataset=? AND source_identifier=? AND checksum_sha256=?""",
                [provider, dataset, source_identifier, checksum],
            ).fetchone()
            latest = con.execute(
                """SELECT d.source_document_id,d.revision_number
                   FROM source_document_revision d
                   WHERE d.provider=? AND d.dataset=?
                     AND starts_with(d.source_identifier,?)
                   ORDER BY d.revision_number DESC LIMIT 1""",
                [provider, dataset, f"{original_path}@"],
            ).fetchone()
            duplicate_source = same_bytes is not None
            if duplicate_source:
                source_document_id, revision_number = same_bytes
                supersedes = None
            else:
                revision_number = latest[1] + 1 if latest else 1
                supersedes = latest[0] if latest else None
                source_document_id = self._id("doc", provider, dataset, source_identifier, checksum)
                con.execute(
                    """INSERT INTO source_document_revision
                       (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,
                        revision_number,source_document_date,publication_date,published_at,ingestion_timestamp,
                        parser_version,extraction_timestamp,extraction_locator,supersedes_source_document_id)
                       VALUES (?,?,?,?,?,?,?,?,?,NULL,?,?,?, ?,?)""",
                    [source_document_id, provider, dataset, source_identifier, source_file_id, checksum,
                     revision_number, partition.source_document_date, partition.first_verified_public_date,
                     ingested_at, partition.parser_version, ingested_at, "$", supersedes],
                )
            con.execute(
                """INSERT INTO source_document_sighting
                   (provider,dataset,source_identifier,checksum_sha256,source_file_id,first_seen_at,source_document_id)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                [provider, dataset, source_identifier, checksum, source_file_id, ingested_at, source_document_id],
            )
        return source_document_id, source_identifier, revision_number, supersedes, duplicate_source

    def _start_processing(self, source_document_id: str, parser_version: str, now: datetime) -> tuple[str, int, str | None]:
        con = self.repository._connection
        latest = con.execute(
            """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
               WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""", [source_document_id]
        ).fetchone()
        attempt = latest[1] + 1 if latest else 1
        process_id = self._id("proc", source_document_id, parser_version, attempt)
        con.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,completed_at,
                replay_timestamp,status,accepted_count,rejected_count,quarantined_count,error_summary,
                supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,NULL,NULL,'started',0,0,0,NULL,?)""",
            [process_id, source_document_id, parser_version, attempt, now, latest[0] if latest else None],
        )
        return process_id, attempt, latest[0] if latest else None

    def _effective_identity(self, isin: str, exchange: str, trade_date: date):
        con = self.repository._connection
        mappings = con.execute(
            """SELECT i.security_id,COALESCE(r.evidence_source_document_id, i.source_document_id)
               FROM security_identifier_revision i
               LEFT JOIN security_identifier_revision_review r
                 ON r.identifier_revision_id=i.identifier_revision_id
                AND r.recorded_at<=CURRENT_TIMESTAMP
                AND NOT EXISTS (
                  SELECT 1 FROM security_identifier_revision_review s
                  WHERE s.supersedes_review_id=r.review_id
                    AND s.recorded_at<=CURRENT_TIMESTAMP
                )
               WHERE i.identifier_type='ISIN' AND i.identifier_value=?
                 AND r.review_status='approved'
                 AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
            [isin, trade_date, trade_date],
        ).fetchall()
        if len(mappings) != 1:
            return None, "unresolved_isin_mapping"
        security_id = mappings[0][0]
        listings = con.execute(
            "SELECT listing_id FROM exchange_listing WHERE security_id=? AND exchange=?", [security_id, exchange]
        ).fetchall()
        if len(listings) != 1:
            return None, "unresolved_exchange_listing"
        listing_id = listings[0][0]
        listing_revisions = con.execute(
            """SELECT r.listing_revision_id,r.status FROM exchange_listing_revision r
               WHERE r.listing_id=? AND r.effective_from<=? AND (r.effective_to IS NULL OR r.effective_to>=?)""",
            [listing_id, trade_date, trade_date],
        ).fetchall()
        approved_status = []
        for revision_id, status in listing_revisions:
            reviews = con.execute(
                """SELECT review_status FROM exchange_listing_revision_review r
                   WHERE listing_revision_id=? AND reviewed_at<=CURRENT_TIMESTAMP
                     AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision_review n
                                     WHERE n.supersedes_review_id=r.listing_revision_review_id)""", [revision_id]
            ).fetchall()
            if len(reviews) == 1 and reviews[0][0] == "approved":
                approved_status.append(status)
        if len(approved_status) != 1:
            return None, "unresolved_effective_listing_status"
        if approved_status[0] in ("suspended", "delisted"):
            return None, "out_of_scope_inactive_listing"
        if approved_status[0] not in ("active", "relisted"):
            return None, "unresolved_effective_listing_status"

        dimensions: dict[str, list[str]] = {}
        for dimension in ("instrument", "platform"):
            cls = f"{dimension}_class"
            start, end = f"{dimension}_valid_from", f"{dimension}_valid_to"
            reviewed = f"{dimension}_reviewed_at"
            candidates = con.execute(
                f"""SELECT r.{cls} FROM listing_classification_review_revision r
                    WHERE r.listing_id=? AND r.{dimension}_review_status='approved'
                      AND r.{start}<=? AND (r.{end} IS NULL OR r.{end}>=?)
                      AND r.recorded_at<=CURRENT_TIMESTAMP AND r.{reviewed}<=CURRENT_TIMESTAMP
                      AND NOT EXISTS (SELECT 1 FROM listing_classification_review_revision n
                                      WHERE n.supersedes_review_revision_id=r.classification_review_revision_id)""",
                [listing_id, trade_date, trade_date],
            ).fetchall()
            dimensions[dimension] = [row[0] for row in candidates]
        if len(dimensions["instrument"]) != 1 or len(dimensions["platform"]) != 1:
            return None, "unresolved_listing_classification"
        instrument_class, platform_class = dimensions["instrument"][0], dimensions["platform"][0]
        if instrument_class == "unknown" or platform_class == "unknown":
            return None, "unresolved_listing_classification"
        if instrument_class != "ordinary_equity" or platform_class in ("sme", "other_platform"):
            return None, "out_of_scope_non_mainboard_ordinary_equity"
        if platform_class != "mainboard":
            return None, "unresolved_listing_classification"
        return (security_id, listing_id), None

    def _reconcile_secondary_observation(
        self,
        report: TejHQIngestionReport,
        *,
        exchange: str,
        listing_id: str,
        trade_date: date,
        secondary_observation_id: str,
    ) -> None:
        """Append only when a new official/secondary pair or source revision exists."""
        con = self.repository._connection
        official = con.execute(
            """SELECT o.observation_id FROM eod_price_observation_revision o
               JOIN source_document_revision d USING(source_document_id)
               WHERE o.listing_id=? AND o.trade_date=? AND d.provider=?
                 AND NOT EXISTS (SELECT 1 FROM eod_price_observation_revision c
                                 WHERE c.supersedes_observation_id=o.observation_id)
               ORDER BY o.extraction_timestamp DESC LIMIT 2""",
            [listing_id, trade_date, exchange],
        ).fetchall()
        stream_id = self.repository.eod_reconciliation_stream_id(exchange, listing_id, trade_date)
        active = con.execute(
            """SELECT reconciliation_id,official_observation_id,secondary_observation_id,match_status,comparator_version
               FROM eod_observation_reconciliation r
               WHERE comparison_stream_id=? AND NOT EXISTS (
                 SELECT 1 FROM eod_observation_reconciliation n
                 WHERE n.supersedes_reconciliation_id=r.reconciliation_id)""",
            [stream_id],
        ).fetchall()
        if len(active) > 1:
            raise RepositoryIntegrityError("comparison stream has multiple active reconciliation results")
        if len(official) > 1:
            report.not_compared += 1
            return

        official_id = official[0][0] if official else None
        if active and active[0][1:] == (official_id, secondary_observation_id,
                                        "matched" if official_id else "unmatched_secondary",
                                        _COMPARATOR_VERSION):
            return

        supersedes = active[0][0] if active else None
        if official_id:
            _, outcome = self.repository.append_eod_observation_reconciliation(
                reconciliation_id=self._id("rec", stream_id, secondary_observation_id, official_id, _COMPARATOR_VERSION),
                comparison_stream_id=stream_id, comparator_version=_COMPARATOR_VERSION,
                match_status="matched", official_observation_id=official_id,
                secondary_observation_id=secondary_observation_id,
                supersedes_reconciliation_id=supersedes,
            )
            report.reconciled += 1
            report.not_compared += int(outcome == "not_compared")
        else:
            self.repository.append_eod_observation_reconciliation(
                reconciliation_id=self._id("rec", stream_id, secondary_observation_id, "unmatched", _COMPARATOR_VERSION),
                comparison_stream_id=stream_id, comparator_version=_COMPARATOR_VERSION,
                match_status="unmatched_secondary", secondary_observation_id=secondary_observation_id,
                not_compared_reason_code="no_official_observation",
                supersedes_reconciliation_id=supersedes,
            )
            report.not_compared += 1

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal | None:
        if value is None:
            return None
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid numeric value for {field}") from exc
        if not number.is_finite():
            raise ValueError(f"non-finite numeric value for {field}")
        return number

    def _quarantine(self, source_document_id: str, row: TejHQRow, parser_version: str,
                    reason: str, detail: str, now: datetime) -> None:
        self.repository._connection.execute(
            """INSERT INTO observation_quarantine
               (quarantine_id,source_document_id,source_locator,reason_code,detail,quarantined_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT (quarantine_id) DO NOTHING""",
            [self._id("q", source_document_id, parser_version, row.locator, reason), source_document_id, row.locator, reason, detail[:1000], now],
        )

    def ingest_pilot(
        self,
        partition: TejHQPartition,
        *,
        trade_date: date,
        symbols: Sequence[str],
    ) -> TejHQIngestionReport:
        """Archive, extract and persist a deliberately small symbol/date pilot."""
        return self._ingest_pilot(partition, trade_date=trade_date, symbols=symbols)

    def _ingest_pilot(
        self,
        partition: TejHQPartition,
        *,
        trade_date: date,
        symbols: Sequence[str],
        recovery_capture_time: datetime | None = None,
    ) -> TejHQIngestionReport:
        checksum_before_archive = self._file_checksum(partition.path)
        capture_time = datetime.now(timezone.utc)
        manifest_path = self._manifest_path(
            checksum=checksum_before_archive, partition=partition, trade_date=trade_date, symbols=symbols
        )
        manifest: dict[str, object] = {
            "status": "archive_intent", "provider": partition.provider, "dataset_id": partition.dataset_id,
            "dataset_revision": partition.dataset_revision, "original_dataset_path": partition.original_dataset_path,
            "source_path": str(partition.path.resolve()),
            "archive_path": str((self.archive_root / checksum_before_archive[:2] / checksum_before_archive).resolve()),
            "checksum_sha256": checksum_before_archive, "exchange": partition.exchange,
            "source_document_date": partition.source_document_date.isoformat(),
            "first_verified_public_date": partition.first_verified_public_date.isoformat(),
            "retrieval_date": partition.retrieval_date.isoformat(),
            "retrieved_at": partition.retrieved_at.isoformat() if partition.retrieved_at else None,
            "archive_captured_at": capture_time.isoformat(),
            "parser_version": partition.parser_version, "trade_date": trade_date.isoformat(),
            "symbols": list(symbols),
        }
        self._write_manifest(manifest_path, manifest)
        archived = archive_user_authorized_source(
            partition.path, archive_root=self.archive_root, license_status="pending", retention_authorized=True
        )
        if archived.sha256_hex != checksum_before_archive:
            raise RepositoryIntegrityError("Parquet file changed between checksum and immutable archival")
        if recovery_capture_time is not None:
            if recovery_capture_time.tzinfo is None or recovery_capture_time.utcoffset() is None:
                raise ValueError("recovery archive capture time must be timezone-aware")
        captured_at = recovery_capture_time or datetime.fromisoformat(str(manifest["archive_captured_at"]))
        manifest["archive_captured_at"] = captured_at.isoformat()
        manifest["status"] = "archived_unprocessed"
        self._write_manifest(manifest_path, manifest)
        if self._fault_hook is not None:
            self._fault_hook("after_archive_before_database")
        schema, rows = self.read_rows(partition, trade_date=trade_date, symbols=symbols)
        fingerprint = self._schema_fingerprint(schema)
        now = datetime.now(timezone.utc)
        doc_id, source_identifier, _, _, _ = self._register_source(
            partition, archived.sha256_hex, str(archived.archive_path.resolve()), fingerprint, captured_at, now
        )
        if self._fault_hook is not None:
            self._fault_hook("after_source_registration_before_processing")
        report = TejHQIngestionReport(
            partition.provider, partition.dataset_id, partition.dataset_revision, source_identifier,
            archived.sha256_hex, fingerprint, partition.parser_version,
        )
        by_natural_key: dict[tuple[str, str, date], list[tuple[TejHQRow, tuple[str, str] | None, str | None, dict[str, Any] | None]]] = {}
        with self.repository._transaction():
            process_id, _, _ = self._start_processing(doc_id, partition.parser_version, now)
            con = self.repository._connection
            for row in rows:
                try:
                    if row.trade_date != trade_date:
                        raise ValueError("row date differs from requested pilot session")
                    isin = row.isin.strip().upper() if row.isin and row.isin.strip() else None
                    if isin is None or not _ISIN.fullmatch(isin):
                        self._quarantine(doc_id, row, partition.parser_version, "missing_or_invalid_isin", "ISIN is absent or malformed; symbol is not an identity key", now)
                        report.quarantined += 1
                        continue
                    mapping, reason = self._effective_identity(isin, partition.exchange, row.trade_date)
                    if mapping is None:
                        if reason and reason.startswith("out_of_scope"):
                            report.out_of_scope += 1
                        else:
                            self._quarantine(doc_id, row, partition.parser_version, reason or "unresolved_identity", "ISIN/listing/classification is not uniquely approved for this session", now)
                            report.quarantined += 1
                        continue
                    values = {
                        "open_raw": self._decimal(row.open, "open"), "high_raw": self._decimal(row.high, "high"),
                        "low_raw": self._decimal(row.low, "low"), "close_raw": self._decimal(row.close, "close"),
                        "volume_raw": self._decimal(row.volume, "volume"), "turnover_raw": self._decimal(row.turnover, "turnover"),
                    }
                    for field_name, value in values.items():
                        if value is not None and field_name in ("volume_raw", "turnover_raw") and value < 0:
                            raise ValueError(f"negative {field_name}")
                        if value is not None and field_name not in ("volume_raw", "turnover_raw") and value < 0:
                            raise ValueError(f"negative {field_name}")
                    if values["high_raw"] is not None and values["low_raw"] is not None and values["high_raw"] < values["low_raw"]:
                        raise ValueError("high is below low")
                    if values["close_raw"] is None:
                        quality = "missing"
                    else:
                        quality = "observed" if all(values.get(k) is not None for k in ("open_raw", "high_raw", "low_raw", "volume_raw", "turnover_raw")) else "missing"
                    values["quality_status"] = quality
                    values["isin"] = isin
                    values["symbol"] = row.symbol
                    values["series"] = row.series
                    by_natural_key.setdefault((mapping[1], isin, row.trade_date), []).append((row, mapping, None, values))
                except (ValueError, TypeError) as exc:
                    self._quarantine(doc_id, row, partition.parser_version, "invalid_parquet_row", str(exc), now)
                    report.rejected += 1

            for (listing_id, isin, session), candidates in by_natural_key.items():
                if len(candidates) > 1:
                    payloads = [candidate[3] for candidate in candidates]
                    comparable = [{key: value for key, value in payload.items() if key not in ("symbol", "series", "isin", "quality_status")} for payload in payloads]
                    if all(item == comparable[0] for item in comparable[1:]):
                        candidates = candidates[:1]
                        report.duplicates += len(payloads) - 1
                    else:
                        for row, _, _, _ in candidates:
                            self._quarantine(doc_id, row, partition.parser_version, "conflicting_duplicate_parquet_row", "multiple differing rows map to one listing/session", now)
                        report.quarantined += len(candidates)
                        continue
                row, mapping, _, values = candidates[0]
                security_id, _ = mapping
                locator = row.locator
                obs_id = self._id("eod", doc_id, partition.parser_version, locator)
                existing_observation = con.execute(
                    """SELECT r.source_document_id,r.parser_version,r.extraction_locator
                       FROM normalized_observation_registry r
                       JOIN eod_price_observation_revision o USING(observation_id)
                       WHERE r.observation_id=?""", [obs_id]
                ).fetchone()
                if existing_observation is not None:
                    if existing_observation != (doc_id, partition.parser_version, locator):
                        raise RepositoryIntegrityError("deterministic EOD observation ID collides with different provenance")
                    report.duplicates += 1
                    self._reconcile_secondary_observation(
                        report, exchange=partition.exchange, listing_id=listing_id,
                        trade_date=session, secondary_observation_id=obs_id,
                    )
                    continue
                parent = con.execute(
                    """SELECT o.observation_id FROM eod_price_observation_revision o
                       JOIN source_document_revision d USING(source_document_id)
                       WHERE o.listing_id=? AND o.trade_date=? AND d.provider=? AND d.dataset=?
                         AND NOT EXISTS (SELECT 1 FROM eod_price_observation_revision c
                                         WHERE c.supersedes_observation_id=o.observation_id)
                       ORDER BY o.extraction_timestamp DESC LIMIT 2""",
                    [listing_id, session, partition.provider, partition.dataset_id],
                ).fetchall()
                if len(parent) > 1:
                    self._quarantine(doc_id, row, partition.parser_version, "conflicting_prior_secondary_observations", "multiple active TejHQ revisions exist for listing/session", now)
                    report.quarantined += 1
                    continue
                extraction_id = process_id
                self.repository.append_eod_price_observation({
                    "observation_id": obs_id, "security_id": security_id, "listing_id": listing_id,
                    "exchange": partition.exchange, "trade_date": session, **{k: values[k] for k in (
                        "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "turnover_raw", "quality_status",
                    )}, "quality_reason": "source row contains missing comparable fields" if values["quality_status"] == "missing" else None,
                    "source_document_id": doc_id, "source_identifier": source_identifier,
                    "checksum_sha256": archived.sha256_hex, "parser_version": partition.parser_version,
                    "extraction_timestamp": now, "extraction_locator": locator,
                    "extraction_revision_id": extraction_id,
                    "supersedes_observation_id": parent[0][0] if parent else None,
                })
                report.revised += int(bool(parent))
                report.accepted += int(not parent)

                self._reconcile_secondary_observation(
                    report, exchange=partition.exchange, listing_id=listing_id,
                    trade_date=session, secondary_observation_id=obs_id,
                )

            con.execute(
                """UPDATE source_document_processing_revision SET completed_at=?,status='succeeded',
                   accepted_count=?,rejected_count=?,quarantined_count=? WHERE processing_revision_id=?""",
                [datetime.now(timezone.utc), report.accepted + report.revised, report.rejected,
                 report.quarantined, process_id],
            )
            if self._fault_hook is not None:
                self._fault_hook("before_database_commit")
        if self._fault_hook is not None:
            self._fault_hook("after_database_commit_before_return")
        manifest["status"] = "succeeded"
        self._write_manifest(manifest_path, manifest)
        return report

    def recover_archived_sources(self) -> list[TejHQIngestionReport]:
        """Discover sidecar manifests left before/after database persistence and retry them."""
        recovered: list[TejHQIngestionReport] = []
        manifest_root = self.archive_root / "_manifests"
        if not manifest_root.exists():
            return recovered
        for path in sorted(manifest_root.glob("*.json")):
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest.get("status") == "succeeded":
                continue
            archive_path = Path(str(manifest["archive_path"]))
            source_path = archive_path if archive_path.is_file() else Path(str(manifest["source_path"]))
            if not source_path.is_file():
                continue
            expected_checksum = str(manifest.get("checksum_sha256", "")).lower()
            if not re.fullmatch(r"[0-9a-f]{64}", expected_checksum):
                raise RepositoryIntegrityError(f"recovery manifest has an invalid SHA-256: {path}")
            if self._file_checksum(source_path) != expected_checksum:
                raise RepositoryIntegrityError(
                    f"recovery source bytes do not match the archived checksum in manifest: {path}"
                )
            retrieved_at = datetime.fromisoformat(str(manifest["retrieved_at"])) if manifest.get("retrieved_at") else None
            partition = TejHQPartition(
                path=source_path, exchange=str(manifest["exchange"]), dataset_id=str(manifest["dataset_id"]),
                dataset_revision=str(manifest["dataset_revision"]),
                original_dataset_path=str(manifest["original_dataset_path"]),
                source_document_date=date.fromisoformat(str(manifest["source_document_date"])),
                first_verified_public_date=date.fromisoformat(str(manifest["first_verified_public_date"])),
                retrieval_date=date.fromisoformat(str(manifest["retrieval_date"])), retrieved_at=retrieved_at,
                parser_version=str(manifest["parser_version"]), provider=str(manifest["provider"]),
            )
            recovered.append(self._ingest_pilot(
                partition, trade_date=date.fromisoformat(str(manifest["trade_date"])),
                symbols=tuple(str(value) for value in manifest["symbols"]),
                recovery_capture_time=datetime.fromisoformat(str(manifest["archive_captured_at"]))
                if manifest.get("archive_captured_at") else None,
            ))
        return recovered
