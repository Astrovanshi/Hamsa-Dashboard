"""Local, user-supplied official-source archival and source-document registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

from hamsa.ingestion.raw_archive import archive_user_authorized_source
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    source_file_id: str
    source_document_id: str
    checksum_sha256: str
    archive_path: str
    revision_number: int
    duplicate: bool


def register_local_exchange_source(
    repository: DuckDBRepository,
    source_path: Path,
    *,
    archive_root: Path,
    exchange: str,
    dataset: str,
    source_identifier: str,
    source_document_date: date,
    publication_date: date,
    parser_version: str,
    published_at: datetime | None = None,
    source_as_of_date: date | None = None,
    retention_authorized: bool = False,
    source_metadata: Mapping[str, object] | None = None,
    source_locator: str | None = None,
) -> RegisteredSource:
    """Archive a manually obtained official file and register immutable revisions.

    This performs no network access and makes no claim that exchange terms
    permit broader use. The caller must explicitly authorize local retention.
    Actual capture and ingestion timestamps are generated here.
    """
    if exchange not in ("NSE", "BSE"):
        raise RepositoryIntegrityError("exchange must be NSE or BSE")
    if not dataset.strip() or not source_identifier.strip() or not parser_version.strip():
        raise RepositoryIntegrityError("dataset, source identifier, and parser version are required")
    if source_locator is not None and not source_locator.strip():
        raise RepositoryIntegrityError("source_locator cannot be blank")
    if published_at is not None and (published_at.tzinfo is None or published_at.utcoffset() is None):
        raise RepositoryIntegrityError("published_at must be timezone-aware")
    if not retention_authorized:
        raise RepositoryIntegrityError("local source retention requires explicit user authorization")
    archived = archive_user_authorized_source(
        source_path, archive_root=archive_root, license_status="pending", retention_authorized=True,
    )
    now = datetime.now(timezone.utc)
    source_file_id = "raw-" + archived.sha256_hex
    source_identifier = source_identifier.strip()
    with repository._transaction():
        file_row = repository._connection.execute(
            "SELECT source_file_id,archive_path FROM raw_source_file WHERE checksum_sha256=?",
            [archived.sha256_hex],
        ).fetchone()
        if file_row is None:
            metadata = {
                "acquisition_method": "manual_local_file",
                "source_identifier": source_identifier,
                **dict(source_metadata or {}),
            }
            if source_locator:
                metadata["source_locator"] = source_locator
            repository._connection.execute(
                """INSERT INTO raw_source_file
                   (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
                    source_as_of_date,license_review_reference,license_status,metadata_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [source_file_id, exchange, dataset, source_path.name, archived.sha256_hex,
                 str(archived.archive_path), now, source_as_of_date,
                 "user-authorized-local-retention;terms-unreviewed", "pending",
                 json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)],
            )
        else:
            source_file_id, archive_path = file_row
            if Path(archive_path).read_bytes() != archived.archive_path.read_bytes():
                raise RepositoryIntegrityError("existing raw archive bytes do not match registered source checksum")

        existing = repository._connection.execute(
            """SELECT source_document_id,revision_number FROM source_document_revision
               WHERE provider=? AND dataset=? AND source_identifier=? AND checksum_sha256=?""",
            [exchange, dataset, source_identifier, archived.sha256_hex],
        ).fetchone()
        latest = repository._connection.execute(
            """SELECT source_document_id,revision_number FROM source_document_revision
               WHERE provider=? AND dataset=? AND source_identifier=? ORDER BY revision_number DESC LIMIT 1""",
            [exchange, dataset, source_identifier],
        ).fetchone()
        duplicate = existing is not None
        if duplicate:
            doc_id, revision_number = existing
            existing_metadata = repository._connection.execute(
                """SELECT source_document_date,publication_date,CAST(published_at AS VARCHAR),source_file_id
                   FROM source_document_revision WHERE source_document_id=?""", [doc_id]
            ).fetchone()
            if existing_metadata != (source_document_date, publication_date,
                                     str(published_at) if published_at else None, source_file_id):
                raise RepositoryIntegrityError(
                    "same source bytes and identifier were supplied with conflicting document dates or timestamp"
                )
            raw_metadata = repository._connection.execute(
                "SELECT metadata_json FROM raw_source_file WHERE source_file_id=?", [source_file_id]
            ).fetchone()[0]
            stored_locator = json.loads(raw_metadata or "{}").get("source_locator")
            if source_locator and stored_locator and source_locator != stored_locator:
                raise RepositoryIntegrityError("same source document was supplied with a conflicting source locator")
        else:
            revision_number = latest[1] + 1 if latest else 1
            parent_id = latest[0] if latest else None
            doc_id = "doc-" + sha256(
                f"{exchange}|{dataset}|{source_identifier}|{archived.sha256_hex}".encode()
            ).hexdigest()[:32]
            repository._connection.execute(
                """INSERT INTO source_document_revision
                   (source_document_id,provider,dataset,source_identifier,source_file_id,checksum_sha256,
                    revision_number,source_document_date,publication_date,published_at,ingestion_timestamp,
                    parser_version,extraction_timestamp,extraction_locator,supersedes_source_document_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [doc_id, exchange, dataset, source_identifier, source_file_id, archived.sha256_hex,
                 revision_number, source_document_date, publication_date, published_at, now,
                 parser_version, now, "$", parent_id],
            )
        repository._connection.execute(
            """INSERT INTO source_document_sighting
               (provider,dataset,source_identifier,checksum_sha256,source_file_id,first_seen_at,source_document_id)
               VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
            [exchange, dataset, source_identifier, archived.sha256_hex, source_file_id, now, doc_id],
        )
    return RegisteredSource(source_file_id, doc_id, archived.sha256_hex,
                            str(archived.archive_path), revision_number, duplicate)


def register_local_crosscheck_file(
    repository: DuckDBRepository,
    source_path: Path,
    *,
    archive_root: Path,
    dataset: str,
    source_identifier: str,
    retention_authorized: bool,
    source_origin: str = "unverified_user_supplied",
) -> RegisteredSource:
    """Archive a cross-check file without inventing publication metadata.

    This records immutable bytes and capture provenance in `raw_source_file`.
    It intentionally does not create a source-document revision because no
    document date or publication date is available to support one.
    """
    if not dataset.strip() or not source_identifier.strip():
        raise RepositoryIntegrityError("cross-check dataset and source identifier are required")
    if not retention_authorized:
        raise RepositoryIntegrityError("local source retention requires explicit user authorization")
    archived = archive_user_authorized_source(
        source_path, archive_root=archive_root, license_status="pending", retention_authorized=True,
    )
    now = datetime.now(timezone.utc)
    source_file_id = "raw-" + archived.sha256_hex
    metadata = {
        "acquisition_method": "manual_local_file",
        "source_identifier": source_identifier.strip(),
        "source_origin": source_origin,
        "original_path_at_capture": str(source_path),
    }
    with repository._transaction():
        existing = repository._connection.execute(
            "SELECT source_file_id,archive_path FROM raw_source_file WHERE checksum_sha256=?",
            [archived.sha256_hex],
        ).fetchone()
        if existing is None:
            repository._connection.execute(
                """INSERT INTO raw_source_file
                   (source_file_id,provider,dataset,original_filename,checksum_sha256,archive_path,captured_at,
                    source_as_of_date,license_review_reference,license_status,metadata_json)
                   VALUES (?,'user-supplied',?,?,?,?,?,NULL,?,'pending',?)""",
                [source_file_id, dataset.strip(), source_path.name, archived.sha256_hex,
                 str(archived.archive_path), now,
                 "source-origin-and-terms-unverified", json.dumps(metadata, sort_keys=True,
                                                                   separators=(",", ":"), ensure_ascii=False)],
            )
            duplicate = False
        else:
            source_file_id, archive_path = existing
            if Path(archive_path).read_bytes() != archived.archive_path.read_bytes():
                raise RepositoryIntegrityError("existing raw archive bytes do not match registered source checksum")
            duplicate = True
    return RegisteredSource(source_file_id, "", archived.sha256_hex, str(archived.archive_path), 1, duplicate)
