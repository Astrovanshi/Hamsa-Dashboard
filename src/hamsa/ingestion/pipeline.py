"""Synthetic file-to-DuckDB ingestion vertical slice.

Source identity and publication metadata are explicit inputs. Production
ingestion time is system-generated; deterministic replay time is opt-in. The
module performs no network access and invents no source data or policy.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence
from datetime import timezone

from hamsa.domain.financials import (
    AsReportedStatus,
    FinancialObservationRevision,
    PublicationPrecision,
    QualityStatus,
)
from hamsa.domain.market_data import EodBar
from hamsa.domain.security import Exchange, ListingCandidate
from hamsa.ingestion.eod_validation import validate_eod_bars
from hamsa.ingestion.raw_archive import archive_approved_source, archive_user_authorized_source
from hamsa.ingestion.security_master import build_security_master
from hamsa.storage.as_reported import as_reported_snapshot
from hamsa.storage.duckdb_repository import DuckDBRepository
from hamsa.domain.trading_calendar import AvailabilityMode, Calendar


@dataclass(frozen=True, slots=True)
class SyntheticFileSpec:
    path: Path
    dataset: str
    source_identifier: str
    source_document_date: date
    publication_date: date
    published_at: datetime | None
    source_as_of_date: date | None
    parser_version: str
    original_filename: str | None = None
    provider: str = "synthetic-fixture"
    license_reference: str = "synthetic-data-license-v1"
    license_status: str = "approved"
    retention_authorized: bool = False
    parser_options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        if self.published_at is not None and (self.published_at.tzinfo is None or self.published_at.utcoffset() is None):
            raise ValueError("published_at must be timezone-aware")
        if not self.dataset or not self.source_identifier or not self.parser_version:
            raise ValueError("dataset, source_identifier, and parser_version are required")


@dataclass(frozen=True, slots=True)
class FileIngestionResult:
    source_identifier: str
    checksum_sha256: str
    accepted: int = 0
    rejected: int = 0
    quarantined: int = 0
    duplicates: int = 0
    revised: int = 0
    error: str | None = None
    # Appended to preserve the positional shape of the earlier report API.
    out_of_scope: int = 0


@dataclass(slots=True)
class IngestionReport:
    accepted: int = 0
    rejected: int = 0
    quarantined: int = 0
    duplicates: int = 0
    revised: int = 0
    files: list[FileIngestionResult] = field(default_factory=list)
    out_of_scope: int = 0

    def add(self, result: FileIngestionResult) -> None:
        self.files.append(result)
        for key in ("accepted", "rejected", "quarantined", "duplicates", "revised", "out_of_scope"):
            setattr(self, key, getattr(self, key) + getattr(result, key))

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "quarantined": self.quarantined,
            "duplicates": self.duplicates,
            "revised": self.revised,
            "out_of_scope": self.out_of_scope,
            "files": [
                {
                    "source_identifier": file.source_identifier,
                    "checksum_sha256": file.checksum_sha256,
                    "accepted": file.accepted,
                    "rejected": file.rejected,
                    "quarantined": file.quarantined,
                    "duplicates": file.duplicates,
                    "revised": file.revised,
                    "out_of_scope": file.out_of_scope,
                    "error": file.error,
                }
                for file in self.files
            ],
        }


class SyntheticIngestionPipeline:
    PROVIDER = "synthetic-fixture"
    LICENSE_REFERENCE = "synthetic-data-license-v1"

    def __init__(
        self,
        repository: DuckDBRepository,
        *,
        archive_root: Path,
        metric_units: Mapping[str, str],
        identity_map: Mapping[str, tuple[str, str]] | None = None,
        parser_version: str,
        replay_mode: bool = False,
        replay_clock: Callable[[], datetime] | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        if not metric_units:
            raise ValueError("metric_units must be explicitly configured")
        if identity_map is not None and len(identity_map) == 0:
            raise ValueError("identity_map must contain explicitly reviewed synthetic mappings when provided")
        if not parser_version:
            raise ValueError("parser_version is required")
        if replay_mode != (replay_clock is not None):
            raise ValueError("a deterministic replay_clock is allowed only with replay_mode=True")
        if fault_hook is not None and not replay_mode:
            raise ValueError("fault injection is allowed only with replay_mode=True")
        self.repository = repository
        self.archive_root = archive_root
        self.metric_units = dict(metric_units)
        normalized_identity_map: dict[str, tuple[str, str]] = {}
        security_isins: dict[str, set[str]] = {}
        for isin, ids in (identity_map or {}).items():
            normalized_isin = isin.strip().upper()
            if len(ids) != 2 or not all(str(value).strip() for value in ids):
                raise ValueError(f"identity mapping for {normalized_isin!r} must contain issuer and security IDs")
            normalized_identity_map[normalized_isin] = (str(ids[0]).strip(), str(ids[1]).strip())
            security_isins.setdefault(str(ids[1]).strip(), set()).add(normalized_isin)
        self.identity_map = normalized_identity_map
        self.identity_map_conflicts = {
            isin for security_isin_set in security_isins.values() if len(security_isin_set) > 1
            for isin in security_isin_set
        }
        self.parser_version = parser_version
        self.replay_mode = replay_mode
        self.replay_clock = replay_clock
        self.fault_hook = fault_hook

    @dataclass(frozen=True, slots=True)
    class Times:
        actual: datetime
        replay: datetime | None

    @dataclass(frozen=True, slots=True)
    class ProcessingContext:
        times: "SyntheticIngestionPipeline.Times"
        processing_revision_id: str
        attempt_number: int
        supersedes_processing_revision_id: str | None

    def _new_times(self, *, replay_timestamp: datetime | None = None) -> "SyntheticIngestionPipeline.Times":
        actual = datetime.now(timezone.utc)
        replay = replay_timestamp
        if replay is None and self.replay_clock is not None:
            replay = self.replay_clock()
        if replay is not None and (not self.replay_mode or replay.tzinfo is None or replay.utcoffset() is None):
            raise ValueError("replay timestamp requires replay_mode and an aware replay clock")
        return self.Times(actual=actual, replay=replay)

    @property
    def _con(self):
        # Internal adapter access keeps SQL writes within the storage boundary.
        return self.repository._connection

    @staticmethod
    def _stable_id(prefix: str, *parts: object) -> str:
        payload = "|".join(str(part) for part in parts)
        return f"{prefix}-{sha256(payload.encode('utf-8')).hexdigest()[:32]}"

    @staticmethod
    def _date(value: str, field_name: str) -> date:
        try:
            return date.fromisoformat(value.strip())
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"invalid {field_name}: {value!r}") from exc

    @staticmethod
    def _decimal(value: str, field_name: str) -> Decimal | None:
        if value is None or not value.strip():
            return None
        try:
            return Decimal(value.strip())
        except (InvalidOperation, AttributeError) as exc:
            raise ValueError(f"invalid decimal {field_name}: {value!r}") from exc

    def _read_csv(self, path: Path, required: set[str]) -> tuple[list[dict[str, str]], list[int]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError("missing or duplicate CSV header")
            missing = required - set(reader.fieldnames)
            if missing:
                raise ValueError(f"missing required CSV columns: {', '.join(sorted(missing))}")
            rows: list[dict[str, str]] = []
            lines: list[int] = []
            for row in reader:
                if None in row:
                    raise ValueError(f"extra CSV fields at line {reader.line_num}")
                rows.append({key: value or "" for key, value in row.items()})
                lines.append(reader.line_num)
            return rows, lines

    def _manifest_path(self, spec: SyntheticFileSpec, checksum: str) -> Path:
        manifest_id = self._stable_id("manifest", spec.provider, spec.dataset, spec.source_identifier, checksum)
        directory = self.archive_root / "_manifests"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{manifest_id}.json"

    def _write_manifest(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temp_path, path)

    def _archive_source(self, spec: SyntheticFileSpec, times: "SyntheticIngestionPipeline.Times"):
        if spec.license_status == "approved":
            archived = archive_approved_source(spec.path, archive_root=self.archive_root, license_status="approved")
        else:
            archived = archive_user_authorized_source(spec.path, archive_root=self.archive_root,
                license_status=spec.license_status, retention_authorized=spec.retention_authorized)
        checksum = archived.sha256_hex
        manifest_path = self._manifest_path(spec, checksum)
        archive_path = str(archived.archive_path.resolve())
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            processed = list(manifest.get("processed_parser_versions", []))
        else:
            processed = []
            manifest = {
                "provider": spec.provider,
                "license_reference": spec.license_reference,
                "license_status": spec.license_status,
                "parser_options": dict(spec.parser_options),
                "dataset": spec.dataset,
                "source_identifier": spec.source_identifier,
                "source_document_date": spec.source_document_date.isoformat(),
                "publication_date": spec.publication_date.isoformat(),
                "published_at": spec.published_at.isoformat() if spec.published_at else None,
                "source_as_of_date": spec.source_as_of_date.isoformat() if spec.source_as_of_date else None,
                "original_filename": spec.original_filename or spec.path.name,
                "checksum_sha256": checksum,
                "archive_path": archive_path,
                "actual_archived_at": times.actual.isoformat(),
                "replay_timestamp": times.replay.isoformat() if times.replay else None,
                "processed_parser_versions": [],
                "parser_replay_timestamps": {},
                "parser_options_by_version": {},
            }
        options_by_version = dict(manifest.get("parser_options_by_version", {}))
        serialized_options = json.loads(json.dumps(dict(spec.parser_options), sort_keys=True))
        prior_options = options_by_version.get(spec.parser_version)
        if prior_options is not None and prior_options != serialized_options:
            raise ValueError("parser options changed without a parser-version change; use a new parser version")
        options_by_version[spec.parser_version] = serialized_options
        manifest["last_attempted_parser_version"] = spec.parser_version
        manifest["processed_parser_versions"] = processed
        manifest["parser_options_by_version"] = options_by_version
        replay_times = dict(manifest.get("parser_replay_timestamps", {}))
        if spec.parser_version not in replay_times:
            replay_times[spec.parser_version] = times.replay.isoformat() if times.replay else None
        manifest["parser_replay_timestamps"] = replay_times
        self._write_manifest(manifest_path, manifest)
        if self.fault_hook is not None:
            self.fault_hook("after_archive_before_database")
        return checksum, archive_path, manifest_path

    def _register_source(self, spec: SyntheticFileSpec, times: "SyntheticIngestionPipeline.Times", checksum: str, archive_path: str) -> tuple[str, str, int, str | None, bool]:
        source_file_id = f"raw-{checksum}"
        with self.repository._transaction():
            existing_file = self._con.execute(
                "SELECT source_file_id, archive_path FROM raw_source_file WHERE checksum_sha256=?", [checksum]
            ).fetchone()
            if existing_file is None:
                self._con.execute(
                    """INSERT INTO raw_source_file
                       (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,
                        captured_at,source_as_of_date,license_review_reference,license_status,metadata_json)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    [source_file_id, spec.provider, spec.dataset, spec.original_filename or spec.path.name, checksum, archive_path,
                     times.actual, spec.source_as_of_date, spec.license_reference, spec.license_status,
                     json.dumps({"synthetic": spec.provider == "synthetic-fixture", "parser_options": dict(spec.parser_options), "parser_version": spec.parser_version,
                                 "license_status": spec.license_status,
                                 "replay_timestamp": times.replay.isoformat() if times.replay else None})],
                )
            else:
                source_file_id, archive_path = existing_file

            existing_doc = self._con.execute(
                """SELECT source_document_id,revision_number FROM source_document_revision
                   WHERE provider=? AND dataset=? AND source_identifier=? AND checksum_sha256=?""",
                [spec.provider, spec.dataset, spec.source_identifier, checksum],
            ).fetchone()
            latest = self._con.execute(
                """SELECT source_document_id,revision_number FROM source_document_revision
                   WHERE provider=? AND dataset=? AND source_identifier=? ORDER BY revision_number DESC LIMIT 1""",
                [spec.provider, spec.dataset, spec.source_identifier],
            ).fetchone()
            duplicate = existing_doc is not None
            if duplicate:
                source_document_id, revision_number = existing_doc
                supersedes_document_id = None
            else:
                revision_number = (latest[1] + 1) if latest else 1
                supersedes_document_id = latest[0] if latest else None
                source_document_id = self._stable_id(
                    "doc", spec.provider, spec.dataset, spec.source_identifier, checksum
                )
                self._con.execute(
                    """INSERT INTO source_document_revision
                       (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,
                        revision_number,source_document_date,publication_date,published_at,ingestion_timestamp,
                        parser_version,extraction_timestamp,extraction_locator,supersedes_source_document_id,replay_timestamp)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [source_document_id, spec.provider, spec.dataset, spec.source_identifier, source_file_id,
                     checksum, revision_number, spec.source_document_date, spec.publication_date,
                     spec.published_at, times.actual, spec.parser_version,
                     times.actual, "$", supersedes_document_id, times.replay],
                )
            self._con.execute(
                """INSERT INTO source_document_sighting
                   (provider,dataset,source_identifier,checksum_sha256,source_file_id,first_seen_at,source_document_id)
                   VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                [spec.provider, spec.dataset, spec.source_identifier, checksum, source_file_id,
                 times.actual, source_document_id],
            )
        return source_file_id, source_document_id, revision_number, supersedes_document_id, duplicate

    def _new_processing_context(self, doc_id: str, spec: SyntheticFileSpec, times: "SyntheticIngestionPipeline.Times"):
        latest = self._con.execute(
            """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
               WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""",
            [doc_id],
        ).fetchone()
        attempt = latest[1] + 1 if latest else 1
        revision_id = self._stable_id("proc", doc_id, spec.parser_version, attempt)
        return self.ProcessingContext(times, revision_id, attempt, latest[0] if latest else None)

    def _record_processing(
        self, doc_id: str, spec: SyntheticFileSpec, context: "SyntheticIngestionPipeline.ProcessingContext",
        *, status: str, accepted: int = 0, rejected: int = 0, quarantined: int = 0, error: str | None = None,
    ) -> None:
        self._con.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,completed_at,
                replay_timestamp,status,accepted_count,rejected_count,quarantined_count,error_summary,supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [context.processing_revision_id, doc_id, spec.parser_version, context.attempt_number,
             context.times.actual, None if status == "started" else datetime.now(timezone.utc), context.times.replay, status,
             accepted, rejected, quarantined, error, context.supersedes_processing_revision_id],
        )

    def _finish_processing(self, context: "SyntheticIngestionPipeline.ProcessingContext", result: FileIngestionResult) -> None:
        self._con.execute(
            """UPDATE source_document_processing_revision SET completed_at=?,status='succeeded',
               accepted_count=?,rejected_count=?,quarantined_count=?,error_summary=NULL
               WHERE processing_revision_id=? AND status='started'""",
            [datetime.now(timezone.utc), result.accepted, result.rejected, result.quarantined,
             context.processing_revision_id],
        )

    def _mark_manifest_processed(self, path: Path, parser_version: str) -> None:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        completed = set(manifest.get("processed_parser_versions", []))
        completed.add(parser_version)
        manifest["processed_parser_versions"] = sorted(completed)
        manifest["last_status"] = "succeeded"
        self._write_manifest(path, manifest)

    def recover_archived_sources(self) -> IngestionReport:
        """Retry archived source/parser pairs missing a committed successful run."""
        report = IngestionReport()
        manifest_root = self.archive_root / "_manifests"
        if not manifest_root.exists():
            return report
        for manifest_path in sorted(manifest_root.glob("*.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            parser_version = self.parser_version
            archived_path = Path(manifest["archive_path"])
            expected_path = (self.archive_root / manifest["checksum_sha256"][:2] / manifest["checksum_sha256"]).resolve()
            if archived_path.resolve() != expected_path or not archived_path.is_file():
                raise ValueError(f"archive manifest path is missing or inconsistent: {manifest_path}")
            if sha256(archived_path.read_bytes()).hexdigest() != manifest["checksum_sha256"]:
                raise ValueError(f"archived source checksum does not match its manifest: {manifest_path}")
            successful = self._con.execute(
                """SELECT 1 FROM source_document_processing_revision p
                   JOIN source_document_revision d USING(source_document_id)
                   WHERE d.dataset=? AND d.source_identifier=? AND d.checksum_sha256=?
                     AND p.parser_version=? AND p.status='succeeded' LIMIT 1""",
                [manifest["dataset"], manifest["source_identifier"], manifest["checksum_sha256"], parser_version],
            ).fetchone()
            if successful:
                self._mark_manifest_processed(manifest_path, parser_version)
                continue
            if parser_version in manifest.get("processed_parser_versions", []):
                continue
            published_at = datetime.fromisoformat(manifest["published_at"]) if manifest.get("published_at") else None
            spec = SyntheticFileSpec(
                path=archived_path,
                dataset=manifest["dataset"],
                source_identifier=manifest["source_identifier"],
                source_document_date=date.fromisoformat(manifest["source_document_date"]),
                publication_date=date.fromisoformat(manifest["publication_date"]),
                published_at=published_at,
                source_as_of_date=date.fromisoformat(manifest["source_as_of_date"]) if manifest.get("source_as_of_date") else None,
                parser_version=parser_version,
                original_filename=manifest.get("original_filename"),
                provider=manifest.get("provider", "synthetic-fixture"),
                license_reference=manifest.get("license_reference", "synthetic-data-license-v1"),
                license_status=manifest.get("license_status", "approved"),
                retention_authorized=manifest.get("license_status") == "pending",
                parser_options=manifest.get("parser_options", {}),
            )
            replay_value = manifest.get("parser_replay_timestamps", {}).get(parser_version)
            replay_at = datetime.fromisoformat(replay_value) if replay_value else None
            report.add(self.ingest_file(spec, replay_timestamp=replay_at if self.replay_mode else None))
        return report

    def _quarantine(self, doc_id: str, locator: str, code: str, detail: str, timestamp: datetime) -> None:
        quarantine_id = self._stable_id("q", doc_id, locator, code, detail)
        self._con.execute(
            """INSERT INTO observation_quarantine
               (quarantine_id,source_document_id,source_locator,reason_code,detail,quarantined_at,resolved_at,resolution_reference)
               VALUES (?,?,?,?,?,?,NULL,NULL) ON CONFLICT DO NOTHING""",
            [quarantine_id, doc_id, locator, code, detail, timestamp],
        )

    def _persist_security_master(
        self, spec: SyntheticFileSpec, source_file_id: str, doc_id: str, rows: list[dict[str, str]], line_numbers: list[int],
        context: "SyntheticIngestionPipeline.ProcessingContext",
    ) -> tuple[int, int, int]:
        candidates: list[ListingCandidate] = []
        quarantined = 0
        for row, line in zip(rows, line_numbers):
            try:
                candidates.append(ListingCandidate(
                    exchange=Exchange(row["exchange"].strip().upper()),
                    exchange_instrument_id=row["instrument_id"].strip(),
                    symbol=row["symbol"].strip(),
                    isin=row["isin"].strip() or None,
                    effective_from=self._date(row["effective_from"], "effective_from"),
                    effective_to=self._date(row["effective_to"], "effective_to") if row["effective_to"].strip() else None,
                    source_file_id=source_file_id,
                    source_document_id=doc_id,
                    checksum_sha256=self._con.execute("SELECT checksum_sha256 FROM raw_source_file WHERE source_file_id=?", [source_file_id]).fetchone()[0],
                    parser_version=spec.parser_version,
                    extraction_timestamp=context.times.actual,
                    extraction_locator=row.get("_source_locator", f"csv:line:{line}"),
                    series=row.get("series") or None,
                    company_name=row.get("company_name") or None,
                ))
            except (ValueError, KeyError) as exc:
                self._quarantine(doc_id, f"csv:line:{line}", "invalid_security_master_row", str(exc), context.times.actual)
                quarantined += 1
        result = build_security_master(candidates)
        for issue in result.issues:
            matching_line = next((line for row, line in zip(rows, line_numbers)
                                  if row.get("instrument_id", "").strip() == issue.candidate.exchange_instrument_id
                                  and row.get("isin", "").strip().upper() == (issue.candidate.isin or "").strip().upper()), 0)
            self._quarantine(doc_id, f"csv:line:{matching_line}", "ambiguous_or_invalid_identity", issue.reason, context.times.actual)
            quarantined += 1

        accepted = revised = 0
        for listing in result.listings:
            if listing.company_isin in self.identity_map_conflicts:
                self._quarantine(doc_id, f"isin:{listing.company_isin}", "conflicting_identity_mapping",
                                 "multiple ISINs were assigned to one security ID; histories remain separate", context.times.actual)
                quarantined += 1
                continue
            mapped_identity = self.identity_map.get(listing.company_isin)
            if mapped_identity is None:
                self._quarantine(doc_id, f"isin:{listing.company_isin}", "unreviewed_identity_mapping", "no reviewed issuer/security mapping supplied", context.times.actual)
                quarantined += 1
                continue
            entity_id, security_id = mapped_identity
            self._con.execute("INSERT INTO issuer_entity VALUES (?,?) ON CONFLICT DO NOTHING", [entity_id, context.times.actual])
            self._con.execute(
                "INSERT INTO equity_security VALUES (?,?,?,?) ON CONFLICT DO NOTHING",
                [security_id, entity_id, listing.series, context.times.actual],
            )
            self._con.execute(
                "INSERT INTO exchange_listing VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                [listing.listing_id, security_id, listing.exchange.value, listing.exchange_instrument_id, context.times.actual],
            )
            candidate = next(c for c in candidates if c.exchange.value == listing.exchange.value
                             and c.exchange_instrument_id == listing.exchange_instrument_id
                             and c.symbol.strip() == listing.symbol
                             and c.effective_from == listing.effective_from
                             and c.isin and c.isin.strip().upper() == listing.company_isin)
            identifier_exists = self._con.execute(
                "SELECT identifier_revision_id FROM security_identifier_revision WHERE security_id=? AND identifier_value=? ORDER BY effective_from DESC LIMIT 1",
                [security_id, listing.company_isin],
            ).fetchone()
            if identifier_exists is None:
                identifier_id = self._stable_id("identifier", security_id, listing.company_isin, candidate.effective_from)
                self._con.execute(
                    """INSERT INTO security_identifier_revision
                       (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,effective_to,
                        source_document_id,mapping_review_status,reviewed_by,reviewed_at,supersedes_identifier_revision_id,
                        parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                       VALUES (?,?, 'ISIN', ?,?,?,?,'pending',NULL,NULL,NULL,?,?,?,?)""",
                    [identifier_id, security_id, listing.company_isin, candidate.effective_from,
                     candidate.effective_to, doc_id, spec.parser_version,
                     context.times.actual, candidate.extraction_locator,
                     context.processing_revision_id],
                )
                # Automated approval: system/provider acts as reviewer.
                # Recorded as a machine decision, not a human review.
                review_id = self._stable_id("idrev", identifier_id, "approved", doc_id)
                self._con.execute(
                    """INSERT INTO security_identifier_revision_review
                       (review_id,identifier_revision_id,review_status,recorded_at,
                        reviewed_by,reviewer_actor_type,reviewed_at,evidence_source_document_id,evidence_locator,
                        rationale,supersedes_review_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,NULL)""",
                    [review_id, identifier_id, "approved", context.times.actual,
                     spec.provider, "provider", context.times.actual,
                     doc_id, candidate.extraction_locator,
                     f"Automated ingestion approval by {spec.provider}"],
                )
            prior_listing_revision = self._con.execute(
                "SELECT listing_revision_id FROM exchange_listing_revision WHERE listing_id=? ORDER BY effective_from DESC,listing_revision_id DESC LIMIT 1",
                [listing.listing_id],
            ).fetchone()
            revision_id = self._stable_id("listingrev", listing.listing_id, doc_id, spec.parser_version, listing.symbol, candidate.effective_from)
            self._con.execute(
                """INSERT INTO exchange_listing_revision
                   (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id,
                    supersedes_listing_revision_id,parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                   VALUES (?,?,?,?,'active',?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                [revision_id, listing.listing_id, listing.symbol, listing.series, candidate.effective_from,
                 candidate.effective_to, doc_id, prior_listing_revision[0] if prior_listing_revision else None,
                 spec.parser_version, context.times.actual, candidate.extraction_locator,
                 context.processing_revision_id],
            )
            accepted += int(prior_listing_revision is None)
            revised += int(prior_listing_revision is not None)
        return accepted, quarantined, revised

    def _listing_for_eod(self, exchange: str, instrument_id: str, symbol: str, trade_date: date):
        return self._con.execute(
            """SELECT l.listing_id,l.security_id,lr.symbol FROM exchange_listing l
               JOIN exchange_listing_revision lr USING(listing_id)
               WHERE l.exchange=? AND l.exchange_instrument_id=? AND lr.symbol=? AND lr.status='active'
                 AND lr.effective_from<=? AND (lr.effective_to IS NULL OR lr.effective_to>=?)
                 AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision child
                                 WHERE child.supersedes_listing_revision_id=lr.listing_revision_id)""",
            [exchange, instrument_id, symbol, trade_date, trade_date],
        ).fetchall()

    def _registry_row(self, observation_id: str, observation_type: str, doc_id: str, spec: SyntheticFileSpec,
                      locator: str, context: "SyntheticIngestionPipeline.ProcessingContext") -> None:
        source = self._con.execute(
            "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?", [doc_id]
        ).fetchone()
        self._con.execute(
            """INSERT INTO normalized_observation_registry
               (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                parser_version,extraction_timestamp,extraction_locator,formula_version,extraction_revision_id)
               VALUES (?,?,?,?,?,?,?, ?,NULL,?)""",
            [observation_id, observation_type, doc_id, source[0], source[1], spec.parser_version,
             context.times.actual, locator, context.processing_revision_id],
        )

    def _persist_eod(self, spec: SyntheticFileSpec, doc_id: str, rows: list[dict[str, str]], lines: list[int],
                     context: "SyntheticIngestionPipeline.ProcessingContext"):
        bars: list[EodBar] = []
        info: dict[str, tuple[str, str]] = {}
        bars_by_key: dict[tuple[str, date], EodBar] = {}
        invalid_duplicate_keys: set[tuple[str, date]] = set()
        quarantine = 0
        rejected = 0
        source_file_id = self._con.execute(
            "SELECT source_file_id FROM source_document_revision WHERE source_document_id=?", [doc_id]
        ).fetchone()[0]
        for row, line in zip(rows, lines):
            locator = row.get("_source_locator", f"csv:line:{line}")
            try:
                if row.get("_parse_error"):
                    raise ValueError(row["_parse_error"])
                trade_date = self._date(row["trade_date"], "trade_date")
                exchange = row["exchange"].strip().upper()
                declared_units = (row["price_unit"].strip(), row["volume_unit"].strip(), row["turnover_unit"].strip())
                if declared_units != ("INR_PER_SHARE", "SHARES", "INR"):
                    self._quarantine(doc_id, locator, "invalid_or_unreviewed_eod_units", repr(declared_units), context.times.actual)
                    quarantine += 1
                    continue
                matches = self._listing_for_eod(exchange, row["instrument_id"].strip(), row["symbol"].strip(), trade_date)
                if len(matches) != 1:
                    self._quarantine(doc_id, locator, "unresolved_listing", f"expected one listing match, found {len(matches)}", context.times.actual)
                    quarantine += 1
                    continue
                listing_id, security_id, _symbol = matches[0]
                bar = EodBar(
                    listing_id=listing_id, exchange=exchange, trade_date=trade_date,
                    open=self._decimal(row["open"], "open"), high=self._decimal(row["high"], "high"),
                    low=self._decimal(row["low"], "low"), close=self._decimal(row["close"], "close"),
                    volume=int(row["volume"]) if row["volume"].strip() else None,
                    turnover=self._decimal(row["turnover"], "turnover"), source_file_id=source_file_id,
                )
                numeric_prices = (bar.open, bar.high, bar.low, bar.close)
                if (any(value is not None and value < 0 for value in numeric_prices)
                        or bar.high is not None and bar.low is not None and bar.high < bar.low
                        or bar.volume is not None and bar.volume < 0
                        or bar.turnover is not None and bar.turnover < 0):
                    rejected += 1
                    continue
                natural_key = (bar.listing_id, bar.trade_date)
                if natural_key in invalid_duplicate_keys:
                    self._quarantine(doc_id, locator, "conflicting_duplicate_eod", "listing/date was already quarantined for conflicting duplicate rows", context.times.actual)
                    quarantine += 1
                    continue
                prior_bar = bars_by_key.get(natural_key)
                if prior_bar is not None:
                    current_values = (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.turnover)
                    prior_values = (prior_bar.open, prior_bar.high, prior_bar.low, prior_bar.close, prior_bar.volume, prior_bar.turnover)
                    if current_values == prior_values and natural_key not in invalid_duplicate_keys:
                        rejected += 1
                    else:
                        self._quarantine(doc_id, info[bar.listing_id][1], "conflicting_duplicate_eod", "multiple differing rows share listing and trade date", context.times.actual)
                        self._quarantine(doc_id, locator, "conflicting_duplicate_eod", "multiple differing rows share listing and trade date", context.times.actual)
                        quarantine += 2
                        invalid_duplicate_keys.add(natural_key)
                        bars = [existing for existing in bars if (existing.listing_id, existing.trade_date) != natural_key]
                        bars_by_key.pop(natural_key, None)
                        info.pop(bar.listing_id, None)
                    continue
                bars.append(bar)
                bars_by_key[natural_key] = bar
                info[listing_id] = (security_id, locator)
            except (ValueError, KeyError) as exc:
                self._quarantine(doc_id, locator, "invalid_eod_row", str(exc), context.times.actual)
                quarantine += 1
        expected = spec.source_as_of_date
        if expected is None:
            return 0, rejected + len(rows), quarantine, 0
        bars = [bar for bar in bars if (bar.listing_id, bar.trade_date) not in invalid_duplicate_keys]
        validated = validate_eod_bars(bars, expected_trade_date=expected,
                                       known_listing_ids=set(info), source_file_id=source_file_id)
        rejected += len(validated.issues)
        revised = 0
        for bar in validated.accepted:
            security_id, locator = info[bar.listing_id]
            obs_id = self._stable_id("eod", doc_id, spec.parser_version, locator)
            self._registry_row(obs_id, "eod_price", doc_id, spec, locator, context)
            parent_doc = self._con.execute(
                "SELECT supersedes_source_document_id FROM source_document_revision WHERE source_document_id=?", [doc_id]
            ).fetchone()[0]
            prior = self._con.execute(
                """SELECT current.observation_id FROM eod_price_observation_revision current
                   WHERE current.listing_id=? AND current.trade_date=?
                     AND (current.source_document_id=? OR (current.source_document_id=? AND current.parser_version<>?))
                     AND NOT EXISTS (SELECT 1 FROM eod_price_observation_revision child
                                     WHERE child.supersedes_observation_id=current.observation_id)
                   ORDER BY current.extraction_timestamp DESC LIMIT 1""",
                [bar.listing_id, bar.trade_date, parent_doc, doc_id, spec.parser_version],
            ).fetchone()
            self._con.execute(
                """INSERT INTO eod_price_observation_revision
                   (observation_id,observation_type,security_id,listing_id,exchange,trade_date,open_raw,high_raw,low_raw,close_raw,
                    price_unit,volume_raw,volume_unit,turnover_raw,turnover_unit,source_document_id,source_identifier,
                    checksum_sha256,parser_version,extraction_timestamp,extraction_locator,quality_status,quality_reason,supersedes_observation_id)
                   VALUES (?,'eod_price',?,?,?,?,?,?,?,?,'INR_PER_SHARE',?,'SHARES',?,'INR',?,?,?,?,?,?,?,NULL,?)""",
                [obs_id, security_id, bar.listing_id, bar.exchange, bar.trade_date, bar.open, bar.high, bar.low, bar.close,
                 bar.volume, bar.turnover, doc_id, self._con.execute("SELECT source_identifier FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone()[0],
                 self._con.execute("SELECT checksum_sha256 FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone()[0],
                 spec.parser_version, context.times.actual, locator,
                 "missing" if bar.close is None else "observed", prior[0] if prior else None],
            )
            revised += int(prior is not None)
        return len(validated.accepted) - revised, rejected, quarantine, revised

    def _persist_delivery(self, spec: SyntheticFileSpec, doc_id: str, rows: list[dict[str, str]], lines: list[int],
                          context: "SyntheticIngestionPipeline.ProcessingContext"):
        accepted = rejected = quarantined = revised = 0
        seen_in_batch: set[tuple[str, date]] = set()
        source = self._con.execute("SELECT source_file_id,source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?", [doc_id]).fetchone()
        for row, line in zip(rows, lines):
            locator = row.get("_source_locator", f"csv:line:{line}")
            try:
                if row.get("_parse_error"):
                    raise ValueError(row["_parse_error"])
                day = self._date(row["trade_date"], "trade_date")
                if spec.source_as_of_date is not None and day != spec.source_as_of_date:
                    raise ValueError("delivery trade date differs from source_as_of_date")
                exchange = row["exchange"].strip().upper()
                if row.get("instrument_id", "").strip():
                    matches = self._listing_for_eod(exchange, row["instrument_id"].strip(), row["symbol"].strip(), day)
                else:
                    matches = self._con.execute(
                        """SELECT l.listing_id,l.security_id,lr.symbol FROM exchange_listing l
                           JOIN exchange_listing_revision lr USING(listing_id)
                           WHERE l.exchange=? AND lr.symbol=? AND coalesce(lr.series,'')=coalesce(?,'')
                             AND lr.status='active' AND lr.effective_from<=?
                             AND (lr.effective_to IS NULL OR lr.effective_to>=?)
                             AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision child
                                             WHERE child.supersedes_listing_revision_id=lr.listing_revision_id)""",
                        [exchange, row["symbol"].strip(), row.get("series", ""), day, day],
                    ).fetchall()
                if len(matches) != 1:
                    self._quarantine(doc_id, locator, "unresolved_delivery_listing", f"expected one effective listing, found {len(matches)}", context.times.actual)
                    quarantined += 1
                    continue
                listing_id, security_id, _ = matches[0]
                batch_key = (listing_id, day)
                if batch_key in seen_in_batch:
                    rejected += 1
                    continue
                seen_in_batch.add(batch_key)
                quantity_text = row.get("delivery_quantity", "").strip()
                traded_text = row.get("volume", "").strip()
                delivery_quantity = int(quantity_text) if quantity_text else None
                traded_quantity = int(traded_text) if traded_text else None
                delivery_percentage = self._decimal(row.get("delivery_percentage", ""), "delivery_percentage")
                if delivery_quantity is not None and delivery_quantity < 0 or traded_quantity is not None and traded_quantity < 0:
                    raise ValueError("delivery and traded quantities cannot be negative")
                if delivery_percentage is not None and not Decimal(0) <= delivery_percentage <= Decimal(100):
                    raise ValueError("delivery percentage is outside 0..100")
                obs_id = self._stable_id("delivery", doc_id, spec.parser_version, locator)
                self._registry_row(obs_id, "delivery", doc_id, spec, locator, context)
                prior = self._con.execute(
                    """SELECT current.observation_id FROM delivery_observation_revision current
                       WHERE current.listing_id=? AND current.trade_date=?
                         AND current.source_document_id IN (?,(SELECT supersedes_source_document_id FROM source_document_revision WHERE source_document_id=?))
                         AND NOT EXISTS (SELECT 1 FROM delivery_observation_revision child WHERE child.supersedes_observation_id=current.observation_id)
                       ORDER BY current.extraction_timestamp DESC LIMIT 1""",
                    [listing_id, day, doc_id, doc_id],
                ).fetchone()
                self._con.execute(
                    """INSERT INTO delivery_observation_revision
                       (observation_id,observation_type,security_id,listing_id,exchange,trade_date,delivery_quantity_raw,
                        traded_quantity_raw,delivery_percentage_raw,source_document_id,parser_version,extraction_timestamp,
                        extraction_locator,quality_status,supersedes_observation_id)
                       VALUES (?,'delivery',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    [obs_id, security_id, listing_id, exchange, day, delivery_quantity, traded_quantity,
                     delivery_percentage, doc_id, spec.parser_version, context.times.actual, locator,
                     "observed" if delivery_quantity is not None or delivery_percentage is not None else "missing",
                     prior[0] if prior else None],
                )
                accepted += int(prior is None)
                revised += int(prior is not None)
            except (ValueError, KeyError, OverflowError) as exc:
                self._quarantine(doc_id, locator, "invalid_delivery_row", str(exc), context.times.actual)
                quarantined += 1
        return accepted, rejected, quarantined, revised

    def _read_provider_rows(self, spec: SyntheticFileSpec):
        """Return normalized rows while retaining ``spec.path`` as the raw source."""
        if spec.dataset == "nse_udiff_eod":
            from hamsa.providers.official_eod import parse_nse_udiff
            allowlist = {str(item).upper() for item in spec.parser_options.get("series_allowlist", [])}
            if not allowlist:
                raise ValueError("NSE UDiFF ingestion requires an explicit series_allowlist")
            isin_values = spec.parser_options.get("isin_allowlist")
            isin_allowlist = {str(item).upper() for item in isin_values} if isin_values else None
            return (*parse_nse_udiff(spec.path, allowed_series=allowlist, isin_allowlist=isin_allowlist), "eod")
        if spec.dataset == "nse_delivery":
            from hamsa.providers.official_eod import parse_nse_delivery
            symbols = spec.parser_options.get("symbols_allowlist")
            symbol_allowlist = {str(item).upper() for item in symbols} if symbols else None
            rows, lines, excluded = parse_nse_delivery(spec.path, symbols_allowlist=symbol_allowlist)
            return rows, lines, excluded, "delivery"
        if spec.dataset == "bse_stock_prices_eod":
            from hamsa.providers.official_eod import parse_bse_stock_prices
            mapping = spec.parser_options.get("listing_mapping")
            rows, lines = parse_bse_stock_prices(spec.path, listing_mapping=mapping)
            return rows, lines, 0, "eod"
        if spec.dataset.startswith("security_master"):
            required = {"exchange", "instrument_id", "symbol", "isin", "effective_from", "effective_to"}
        elif spec.dataset.startswith("eod"):
            required = {"trade_date", "exchange", "instrument_id", "symbol", "open", "high", "low", "close", "volume", "turnover", "price_unit", "volume_unit", "turnover_unit"}
        elif spec.dataset.startswith(("quarterly_results", "financial_results")):
            required = {"isin", "metric", "value", "unit", "period_start", "period_end", "reporting_scope"}
        elif spec.dataset.startswith("corporate_filings"):
            required = {"filing_id", "isin", "action_type", "ex_date", "record_date", "effective_date", "terms_complete", "terms_json"}
        else:
            raise ValueError(f"no parser registered for dataset {spec.dataset!r}")
        rows, lines = self._read_csv(spec.path, required)
        kind = "eod" if spec.dataset.startswith("eod") else "financial" if spec.dataset.startswith(("quarterly_results", "financial_results")) else "filing"
        return rows, lines, 0, kind

    def _ensure_metrics(self) -> None:
        descriptions = {
            "revenue": "Revenue",
            "pat": "Profit after tax",
            "roce": "Return on capital employed",
            "operating_margin": "Operating margin",
            "cfo": "Cash flow from operations",
            "fcf": "Free cash flow",
            "capex": "Capital expenditure",
            "cwip": "Capital work in progress",
            "gross_block": "Gross block",
            "market_cap": "Market capitalisation",
            "net_profit": "Net profit",
            "cash_flow": "Cash flow",
        }
        for metric, canonical_unit in self.metric_units.items():
            unit = self._con.execute("SELECT dimension FROM canonical_unit WHERE unit_code=?", [canonical_unit]).fetchone()
            if unit is None:
                raise ValueError(f"canonical unit is not registered: {canonical_unit}")
            self._con.execute(
                "INSERT INTO financial_metric_definition VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                [metric, canonical_unit, unit[0], descriptions.get(metric, metric), "synthetic-metric-v1"],
            )

    def _persist_financials(self, spec: SyntheticFileSpec, doc_id: str, rows: list[dict[str, str]], lines: list[int],
                            context: "SyntheticIngestionPipeline.ProcessingContext"):
        parent_doc = self._con.execute(
            "SELECT supersedes_source_document_id FROM source_document_revision WHERE source_document_id=?", [doc_id]
        ).fetchone()[0]
        accepted = quarantined = rejected = revised = 0
        self._ensure_metrics()
        for row, line in zip(rows, lines):
            locator = f"csv:line:{line}"
            try:
                metric = row["metric"].strip()
                unit = row["unit"].strip()
                if metric not in self.metric_units:
                    self._quarantine(doc_id, locator, "unconfigured_metric", metric, context.times.actual)
                    quarantined += 1
                    continue
                canonical_unit = self.metric_units[metric]
                raw_value = self._decimal(row["value"], "value")
                conversion_rule_id = None
                canonical_value = raw_value
                if unit != canonical_unit:
                    rules = self._con.execute(
                        """SELECT conversion_rule_id,multiplier,additive_offset
                           FROM unit_conversion_rule_revision
                           WHERE source_unit=? AND canonical_unit=? AND review_status='approved'""",
                        [unit, canonical_unit],
                    ).fetchall()
                    if len(rules) != 1:
                        self._quarantine(doc_id, locator, "invalid_or_unreviewed_unit", f"{unit!r} cannot be converted to {canonical_unit!r}", context.times.actual)
                        quarantined += 1
                        continue
                    conversion_rule_id, multiplier, offset = rules[0]
                    if raw_value is not None:
                        canonical_value = raw_value * Decimal(str(multiplier)) + Decimal(str(offset))
                period_start = self._date(row["period_start"], "period_start")
                period_end = self._date(row["period_end"], "period_end")
                if period_start > period_end:
                    raise ValueError("period_start follows period_end")
                # The canonical issuer identity is resolved from an approved ISIN mapping.
                mapping = self._con.execute(
                    """SELECT e.issuer_entity_id FROM security_identifier_revision i
                       JOIN security_identifier_revision_review r
                         ON r.identifier_revision_id=i.identifier_revision_id
                        AND r.review_status='approved'
                        AND NOT EXISTS (
                          SELECT 1 FROM security_identifier_revision_review s
                          WHERE s.supersedes_review_id=r.review_id
                        )
                       JOIN equity_security e USING(security_id)
                       WHERE i.identifier_value=?
                         AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
                    [row["isin"].strip().upper(), period_end, period_end],
                ).fetchall()
                if len(mapping) != 1:
                    self._quarantine(doc_id, locator, "unresolved_financial_subject", f"expected one approved ISIN mapping, found {len(mapping)}", context.times.actual)
                    quarantined += 1
                    continue
                subject_id = mapping[0][0]
                # Re-query with the resolved entity: the prior lookup deliberately
                # occurs only after successful identity resolution.
                existing = self._con.execute(
                    """SELECT current.observation_id,current.revision_number,current.parser_version,current.source_document_id
                       FROM financial_observation_revision current
                       WHERE current.subject_entity_id=? AND current.metric=? AND current.period_start=?
                         AND current.period_end=? AND current.reporting_scope=?
                         AND (current.source_document_id=? OR (current.source_document_id=? AND current.parser_version<>?))
                         AND NOT EXISTS (SELECT 1 FROM financial_observation_revision child
                                         WHERE child.supersedes_observation_id=current.observation_id)
                       ORDER BY current.revision_number DESC LIMIT 1""",
                    [subject_id, metric, period_start, period_end,
                     row.get("reporting_scope", "consolidated").strip() or "consolidated",
                     parent_doc, doc_id, spec.parser_version],
                ).fetchone()
                observation_id = self._stable_id("fin", doc_id, spec.parser_version, locator)
                quality = QualityStatus.MISSING if raw_value is None else QualityStatus.OBSERVED
                obs = FinancialObservationRevision(
                    observation_id=observation_id, subject_id=subject_id, metric=metric,
                    raw_value=raw_value, raw_unit=unit, canonical_value=canonical_value,
                    canonical_unit=canonical_unit, period_start=period_start, period_end=period_end,
                    source_document_date=spec.source_document_date, publication_date=spec.publication_date,
                    publication_precision=PublicationPrecision.TIMESTAMP if spec.published_at else PublicationPrecision.DATE_ONLY,
                    published_at=spec.published_at, ingestion_timestamp=context.times.actual,
                    revision_number=(existing[1] + 1) if existing else 1, source_document_id=doc_id,
                    as_reported_status=(AsReportedStatus.RECAST if existing and (existing[2] == spec.parser_version or existing[3] == doc_id)
                                        else AsReportedStatus.RESTATEMENT if existing else AsReportedStatus.ORIGINAL),
                    quality_status=quality, quality_reason=None if raw_value is not None else "source value is blank",
                    reporting_scope=row.get("reporting_scope", "consolidated").strip() or "consolidated",
                    source_locator=locator, parser_version=spec.parser_version,
                    extraction_timestamp=context.times.actual,
                    supersedes_observation_id=existing[0] if existing else None,
                    replay_timestamp=context.times.replay,
                    conversion_rule_id=conversion_rule_id,
                )
                self.repository.append_financial_observation(obs, extraction_revision_id=context.processing_revision_id)
                accepted += int(existing is None)
                revised += int(existing is not None)
            except (ValueError, KeyError, InvalidOperation) as exc:
                self._quarantine(doc_id, locator, "invalid_financial_row", str(exc), context.times.actual)
                rejected += 1
        return accepted, rejected, quarantined, revised

    def _persist_corporate_filings(self, spec: SyntheticFileSpec, doc_id: str, rows: list[dict[str, str]], lines: list[int],
                                    context: "SyntheticIngestionPipeline.ProcessingContext"):
        accepted = quarantined = revised = 0
        valid_actions = {"split", "bonus", "rights", "merger", "demerger", "symbol_change", "isin_change", "suspension", "delisting", "relisting"}
        for row, line in zip(rows, lines):
            locator = f"csv:line:{line}"
            try:
                action_type = row["action_type"].strip().lower()
                if action_type not in valid_actions:
                    raise ValueError(f"unsupported corporate action type: {action_type}")
                terms = json.loads(row["terms_json"] or "{}")
                complete = row["terms_complete"].strip().lower() == "true"
                mapping = self._con.execute(
                    """SELECT i.security_id FROM security_identifier_revision i
                       JOIN security_identifier_revision_review r
                         ON r.identifier_revision_id=i.identifier_revision_id
                        AND r.review_status='approved'
                        AND NOT EXISTS (
                          SELECT 1 FROM security_identifier_revision_review s
                          WHERE s.supersedes_review_id=r.review_id
                        )
                       WHERE i.identifier_value=?""",
                    [row["isin"].strip().upper()],
                ).fetchall()
                if len(mapping) != 1:
                    self._quarantine(doc_id, locator, "unresolved_corporate_action_security", f"expected one approved ISIN mapping, found {len(mapping)}", context.times.actual)
                    quarantined += 1
                    continue
                action_id = row["filing_id"].strip()
                prior = self._con.execute(
                    "SELECT event_revision_id,revision_number FROM corporate_action_event_revision WHERE event_id=? ORDER BY revision_number DESC LIMIT 1",
                    [action_id],
                ).fetchone()
                observation_id = self._stable_id("action", action_id, doc_id, spec.parser_version, locator)
                self._registry_row(observation_id, "corporate_action", doc_id, spec, locator, context)
                self._con.execute(
                    """INSERT INTO corporate_action_event_revision
                       (event_revision_id,observation_type,event_id,revision_number,action_type,affected_security_id,
                        resulting_security_id,source_document_id,publication_date,published_at,source_document_date,
                        ex_date,record_date,effective_date,terms_complete,terms_json,supersedes_event_revision_id)
                       VALUES (?,'corporate_action',?,?,?, ?,NULL,?,?,?,?,?,?,?,?,?,?)""",
                    [observation_id, action_id, prior[1] + 1 if prior else 1, action_type, mapping[0][0], doc_id,
                     spec.publication_date, spec.published_at, spec.source_document_date,
                     self._date(row["ex_date"], "ex_date") if row.get("ex_date", "").strip() else None,
                     self._date(row["record_date"], "record_date") if row.get("record_date", "").strip() else None,
                     self._date(row["effective_date"], "effective_date") if row.get("effective_date", "").strip() else None,
                     complete, json.dumps(terms, sort_keys=True), prior[0] if prior else None],
                )
                accepted += int(prior is None)
                revised += int(prior is not None)
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                self._quarantine(doc_id, locator, "invalid_corporate_filing", str(exc), context.times.actual)
                quarantined += 1
        return accepted, 0, quarantined, revised

    def ingest_file(self, spec: SyntheticFileSpec, *, replay_timestamp: datetime | None = None) -> FileIngestionResult:
        if spec.parser_version != self.parser_version:
            checksum = sha256(spec.path.read_bytes()).hexdigest()
            return FileIngestionResult(spec.source_identifier, checksum, rejected=1, error="file parser version does not match configured parser")
        if replay_timestamp is not None and not self.replay_mode:
            raise ValueError("replay_timestamp override requires replay_mode=True")
        times = self._new_times(replay_timestamp=replay_timestamp)
        checksum, archive_path, manifest_path = self._archive_source(spec, times)
        source_file_id, doc_id, _revision, _parent, _source_duplicate = self._register_source(spec, times, checksum, archive_path)
        context = self._new_processing_context(doc_id, spec, times)
        checksum = self._con.execute("SELECT checksum_sha256 FROM raw_source_file WHERE source_file_id=?", [source_file_id]).fetchone()[0]
        try:
            dataset = spec.dataset
            rows, lines, parser_excluded, data_kind = self._read_provider_rows(spec)
        except (UnicodeDecodeError, csv.Error, OSError, ValueError) as exc:
            with self.repository._transaction():
                self._record_processing(doc_id, spec, context, status="failed", rejected=1, error=str(exc))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["last_status"] = "failed"
            manifest["last_error"] = str(exc)
            self._write_manifest(manifest_path, manifest)
            return FileIngestionResult(spec.source_identifier, checksum, rejected=1, error=str(exc))

        prior_success = self._con.execute(
            """SELECT 1 FROM source_document_processing_revision WHERE source_document_id=?
               AND parser_version=? AND status='succeeded' LIMIT 1""",
            [doc_id, spec.parser_version],
        ).fetchone()
        if prior_success:
            self._mark_manifest_processed(manifest_path, spec.parser_version)
            return FileIngestionResult(spec.source_identifier, checksum, duplicates=max(1, len(rows)))

        try:
            with self.repository._transaction():
                self._record_processing(doc_id, spec, context, status="started")
                if dataset.startswith("security_master"):
                    accepted, quarantined, revised = self._persist_security_master(spec, source_file_id, doc_id, rows, lines, context)
                    result = FileIngestionResult(spec.source_identifier, checksum, accepted=accepted, quarantined=quarantined, revised=revised)
                elif data_kind == "eod":
                    if dataset in {"nse_udiff_eod", "bse_stock_prices_eod"}:
                        mapping_rows = []
                        if dataset == "bse_stock_prices_eod":
                            map_value = spec.parser_options.get("listing_mapping")
                            if isinstance(map_value, Mapping):
                                map_row = dict(map_value)
                            elif isinstance(map_value, Sequence) and map_value and isinstance(map_value[0], Mapping):
                                map_row = dict(map_value[0])
                            else:
                                map_row = {}
                            mapping_is_usable = bool(rows) and all(row.get("_mapping_valid") for row in rows)
                            if mapping_is_usable and str(map_row.get("isin", "")).upper() in self.identity_map:
                                mapping_rows.append({"exchange":"BSE", "instrument_id":str(map_row["instrument_id"]),
                                    "symbol":str(map_row["symbol"]), "isin":str(map_row["isin"]),
                                    "effective_from":str(map_row["effective_from"]), "effective_to":"", "series":"EQ",
                                    "company_name":str(map_row.get("company_name", "")),
                                    "_source_locator":f"mapping:{map_row['evidence_reference']}"})
                        else:
                            for row in rows:
                                if row.get("isin", "").upper() in self.identity_map:
                                    mapping_rows.append({"exchange":"NSE", "instrument_id":row["instrument_id"],
                                        "symbol":row["symbol"], "isin":row["isin"], "effective_from":row["trade_date"],
                                        "effective_to":"", "series":row["series"],
                                        "_source_locator":row.get("_source_locator", "")})
                        if mapping_rows:
                            self._persist_security_master(spec, source_file_id, doc_id, mapping_rows,
                                                          list(range(1, len(mapping_rows)+1)), context)
                    accepted, rejected, quarantined, revised = self._persist_eod(spec, doc_id, rows, lines, context)
                    delivery = [row for row in rows if "delivery_quantity" in row or "delivery_percentage" in row]
                    if delivery:
                        da, dr, dq, drev = self._persist_delivery(spec, doc_id, delivery, list(range(1,len(delivery)+1)), context)
                        accepted += da; rejected += dr; quarantined += dq; revised += drev
                    result = FileIngestionResult(spec.source_identifier, checksum, accepted, rejected, quarantined,
                                                 0, revised, out_of_scope=parser_excluded)
                elif data_kind == "delivery":
                    accepted, rejected, quarantined, revised = self._persist_delivery(spec, doc_id, rows, lines, context)
                    result = FileIngestionResult(spec.source_identifier, checksum, accepted, rejected, quarantined,
                                                 0, revised, out_of_scope=parser_excluded)
                elif data_kind == "financial":
                    accepted, rejected, quarantined, revised = self._persist_financials(spec, doc_id, rows, lines, context)
                    result = FileIngestionResult(spec.source_identifier, checksum, accepted, rejected, quarantined, 0, revised)
                else:
                    accepted, rejected, quarantined, revised = self._persist_corporate_filings(spec, doc_id, rows, lines, context)
                    result = FileIngestionResult(spec.source_identifier, checksum, accepted, rejected, quarantined, 0, revised)
                if self.fault_hook is not None:
                    self.fault_hook("after_normalized_writes_before_commit")
                self._finish_processing(context, result)
        except Exception as exc:
            message = f"transaction rolled back: {type(exc).__name__}: {exc}"
            try:
                with self.repository._transaction():
                    self._record_processing(doc_id, spec, context, status="failed",
                                            rejected=max(1, len(rows)), error=message)
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["last_status"] = "failed"
                manifest["last_error"] = message
                self._write_manifest(manifest_path, manifest)
            except Exception as processing_error:
                message += f"; failed to record processing outcome: {type(processing_error).__name__}: {processing_error}"
            return FileIngestionResult(spec.source_identifier, checksum, rejected=max(1, len(rows)), error=message)
        if self.fault_hook is not None:
            self.fault_hook("after_database_commit_before_manifest")
        self._mark_manifest_processed(manifest_path, spec.parser_version)
        return result

    def ingest_files(self, specs: Iterable[SyntheticFileSpec]) -> IngestionReport:
        report = IngestionReport()
        for spec in specs:
            report.add(self.ingest_file(spec))
        return report

    def financial_snapshot(self, *, as_of_session: date, mode: AvailabilityMode, calendar: Calendar,
                           parser_version: str | None = None):
        rows = self._con.execute(
            """SELECT observation_id,subject_entity_id,metric,raw_value,raw_unit,canonical_value,canonical_unit,
                      period_start,period_end,source_document_date,publication_date,publication_precision,
                      CAST(published_at AS VARCHAR),CAST(ingestion_timestamp AS VARCHAR),revision_number,
                      source_document_id,as_reported_status,quality_status,quality_reason,reporting_scope,
                      extraction_locator,parser_version,CAST(extraction_timestamp AS VARCHAR),supersedes_observation_id
               FROM financial_observation_revision ORDER BY observation_id"""
        ).fetchall()
        observations: list[FinancialObservationRevision] = []
        for row in rows:
            (observation_id, subject_id, metric, raw_value, raw_unit, canonical_value, canonical_unit,
             period_start, period_end, source_date, pub_date, precision, published_at, ingested_at, revision,
             document_id, as_status, quality, quality_reason, scope, locator, row_parser_version, extracted_at, supersedes) = row
            parse_ts = lambda value: datetime.fromisoformat(value.replace(" ", "T", 1)) if value else None
            observations.append(FinancialObservationRevision(
                observation_id=observation_id, subject_id=subject_id, metric=metric,
                raw_value=Decimal(str(raw_value)) if raw_value is not None else None, raw_unit=raw_unit,
                canonical_value=Decimal(str(canonical_value)) if canonical_value is not None else None,
                canonical_unit=canonical_unit, period_start=period_start, period_end=period_end,
                source_document_date=source_date, publication_date=pub_date,
                publication_precision=PublicationPrecision(precision), published_at=parse_ts(published_at),
                ingestion_timestamp=parse_ts(ingested_at), revision_number=revision,
                source_document_id=document_id, as_reported_status=AsReportedStatus(as_status),
                quality_status=QualityStatus(quality), quality_reason=quality_reason,
                reporting_scope=scope, source_locator=locator, parser_version=row_parser_version,
                extraction_timestamp=parse_ts(extracted_at), supersedes_observation_id=supersedes,
            ))
        return as_reported_snapshot(observations, as_of_session=as_of_session, mode=mode,
                                    calendar=calendar, parser_version=parser_version)
