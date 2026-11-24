"""Local parsing and fail-closed qualification intake for official exchange masters.

Parsers preserve raw fields. They never infer platform or ordinary-equity class
from a symbol, name, series, market capitalization, or an undocumented code.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from typing import Iterable
from zipfile import BadZipFile, ZipFile

from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError
from hamsa.domain.security import is_valid_isin
from hamsa.domain.trading_calendar import MARKET_TIMEZONE
from hamsa.ingestion.source_registry import register_local_exchange_source, RegisteredSource


@dataclass(frozen=True, slots=True)
class RawMasterRow:
    exchange: str
    exchange_instrument_id: str
    isin: str | None
    symbol: str | None
    series: str | None
    raw_listing_status: str | None
    source_fields: dict[str, str]
    extraction_locator: str


@dataclass(frozen=True, slots=True)
class MasterIntakeReport:
    snapshots_recorded: int
    duplicates: int
    quarantined: int
    source_snapshot_date: date
    accepted_records: int = 0
    unresolved_records: int = 0
    conflicting_records: int = 0
    deleted_records: int = 0
    out_of_scope_records: int = 0
    rejected_records: int = 0
    suspended_records: int = 0
    not_permitted_records: int = 0
    exchange_exclusive_records: int = 0
    test_instrument_records: int = 0


@dataclass(frozen=True, slots=True)
class NseMasterIngestion:
    source: RegisteredSource
    report: MasterIntakeReport
    parser_version: str
    processing_revision_id: str | None


NSE_EPOCH = datetime(1980, 1, 1)


def decode_nse_master_time(raw_value: str | None) -> datetime | None:
    """Decode NSE master seconds from 1980-01-01 as a naive source clock value.

    The NSE specification does not declare a timezone for these values, so no
    timezone is attached. Zero/blank sentinels and malformed values stay NULL.
    """
    if raw_value is None or not raw_value.strip() or raw_value.strip() == "0":
        return None
    try:
        seconds = int(raw_value)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    try:
        return NSE_EPOCH + timedelta(seconds=seconds)
    except OverflowError:
        return None


def nse_snapshot_date_from_filename(source_path: Path) -> date:
    """Parse NSE's documented DDMMYYYY file-name date as a claimed snapshot date."""
    match = re.search(r"NSE_CM_security_(\d{2})(\d{2})(\d{4})", source_path.name, re.IGNORECASE)
    if not match:
        raise RepositoryIntegrityError("NSE CM MII filename does not contain the documented DDMMYYYY date")
    day, month, year = map(int, match.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise RepositoryIntegrityError("NSE CM MII filename contains an invalid DDMMYYYY date") from exc


def _read_csv(content: bytes, *, locator_prefix: str) -> tuple[list[dict[str, str]], list[int]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise RepositoryIntegrityError("exchange master is not valid UTF-8/UTF-8-SIG") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    if not reader.fieldnames:
        raise RepositoryIntegrityError("exchange master has no header")
    headers = [header.strip() for header in reader.fieldnames]
    if len(headers) != len(set(headers)):
        raise RepositoryIntegrityError("exchange master has duplicate column names")
    result, line_numbers = [], []
    for row in reader:
        if None in row:
            raise RepositoryIntegrityError(f"exchange master has extra fields at row line {reader.line_num}")
        result.append({(key or "").strip(): (value or "").strip() for key, value in row.items()})
        line_numbers.append(reader.line_num)
    return result, line_numbers


def parse_nse_mii_master(path: Path) -> tuple[RawMasterRow, ...]:
    raw_bytes = path.read_bytes()
    if path.suffix.lower() == ".gz":
        try:
            raw_bytes = gzip.decompress(raw_bytes)
        except OSError as exc:
            raise RepositoryIntegrityError("malformed NSE MII security master gzip") from exc
    rows, lines = _read_csv(raw_bytes, locator_prefix="csv")
    required = {"FinInstrmId", "ISIN", "TckrSymb", "SctySrs", "FinInstrmNm"}
    if not rows or not required.issubset(rows[0]):
        raise RepositoryIntegrityError(f"NSE MII master fields missing: {', '.join(sorted(required-set(rows[0] if rows else [])))}")
    output = []
    for row, line in zip(rows, lines):
        output.append(RawMasterRow(
            "NSE", row["FinInstrmId"], row["ISIN"] or None, row["TckrSymb"] or None,
            row["SctySrs"] or None, row.get("SctyStsNrmlMkt") or None, row,
            f"csv:line:{line}",
        ))
    return tuple(output)


def parse_bse_published_scrip_master(path: Path) -> tuple[RawMasterRow, ...]:
    """Parse only the published BSE standardized CSV field names when present.

    BSE's current SCRIP.ZIP has not been inspected in HAMSA. This strict parser
    is a compatibility path for a file matching the published 2022 format; it
    is not evidence that the current master uses that layout.
    """
    try:
        if path.suffix.lower() == ".zip":
            with ZipFile(path) as archive:
                members = [name for name in archive.namelist() if name.lower().endswith((".csv", ".txt"))]
                if len(members) != 1:
                    raise RepositoryIntegrityError(f"expected one BSE master CSV/TXT member, found {len(members)}")
                content = archive.read(members[0])
                prefix = f"zip:{members[0]}"
        else:
            content = path.read_bytes()
            prefix = "csv"
    except BadZipFile as exc:
        raise RepositoryIntegrityError("malformed BSE SCRIP.ZIP archive") from exc
    rows, lines = _read_csv(content, locator_prefix=prefix)
    required = {"Scrip Code", "ISIN CODE", "Instrument Code", "Scrip Name", "Security Type Flag",
                "Instrument status flag", "Instrument Type"}
    if not rows or not required.issubset(rows[0]):
        raise RepositoryIntegrityError(
            "BSE master does not match the published standardized format; inspect current file specification before parsing"
        )
    return tuple(RawMasterRow(
        "BSE", row["Scrip Code"], row["ISIN CODE"] or None, row["Instrument Code"] or None,
        None, row.get("Instrument status flag") or None, row,
        f"{prefix}:line:{line}",
    ) for row, line in zip(rows, lines))


def intake_master_snapshot(
    repository: DuckDBRepository,
    *, source_document_id: str,
    source_snapshot_date: date,
    parser_version: str,
    rows: Iterable[RawMasterRow],
) -> MasterIntakeReport:
    """Persist raw rows against existing approved identity, quarantine others.

    Snapshot date is stored as an observed source date only. It never creates or
    changes an effective listing interval and every classification review is
    left pending for a human reviewer.
    """
    materialized = tuple(rows)
    exchange_values = {row.exchange for row in materialized}
    if not materialized or len(exchange_values) != 1:
        raise RepositoryIntegrityError("master intake requires rows from exactly one exchange")
    exchange = next(iter(exchange_values))
    source = repository._connection.execute(
        "SELECT provider FROM source_document_revision WHERE source_document_id=?", [source_document_id]
    ).fetchone()
    if source is None or not str(source[0]).upper().startswith(exchange):
        raise RepositoryIntegrityError("master source document provider does not match row exchange")
    listing_by_instrument: dict[str, list[tuple[str, str]]] = {}
    for listing_id, security_id, instrument_id in repository._connection.execute(
        "SELECT listing_id,security_id,exchange_instrument_id FROM exchange_listing WHERE exchange=?", [exchange]
    ).fetchall():
        listing_by_instrument.setdefault(str(instrument_id), []).append((listing_id, security_id))
    approved_by_isin: dict[str, set[str]] = {}
    for identifier, security_id in repository._connection.execute(
        """SELECT i.identifier_value,i.security_id
           FROM security_identifier_revision i
           JOIN security_identifier_revision_review r
             ON r.identifier_revision_id=i.identifier_revision_id
            AND r.review_status='approved'
            AND NOT EXISTS (
              SELECT 1 FROM security_identifier_revision_review s
              WHERE s.supersedes_review_id=r.review_id
            )
           WHERE i.identifier_type='ISIN'
             AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
        [source_snapshot_date, source_snapshot_date],
    ).fetchall():
        approved_by_isin.setdefault(str(identifier).upper(), set()).add(str(security_id))
    prior_quarantine = {
        str(qid): (str(reason), str(detail))
        for qid, reason, detail in repository._connection.execute(
            "SELECT quarantine_id,reason_code,detail FROM observation_quarantine WHERE source_document_id=?",
            [source_document_id],
        ).fetchall()
    }
    snapshots = duplicates = quarantined = unresolved = conflicts = deleted = out_of_scope = rejected = 0
    suspended = not_permitted = exchange_exclusive = test_instruments = 0
    quarantine_inserts: list[tuple[str, str, str, str, str]] = []
    key_fingerprints: dict[str, set[tuple[str | None, str | None, str | None]]] = {}
    key_occurrences: dict[str, int] = {}
    for row in materialized:
        key = row.exchange_instrument_id.strip()
        key_fingerprints.setdefault(key, set()).add(
            ((row.isin or "").strip().upper() or None, (row.symbol or "").strip() or None,
             (row.series or "").strip() or None)
        )
        key_occurrences[key] = key_occurrences.get(key, 0) + 1
    seen_keys: set[str] = set()
    for row in materialized:
        locator = row.extraction_locator
        isin = row.isin.strip().upper() if row.isin else None
        source_symbol = (row.symbol or "").strip()
        listing_candidates = listing_by_instrument.get(row.exchange_instrument_id, [])
        reason = None
        listing_id = security_id = None
        if not row.exchange_instrument_id.strip() or not source_symbol:
            reason = "malformed_required_identity_fields"
        elif len(key_fingerprints.get(row.exchange_instrument_id.strip(), set())) > 1:
            reason = "conflicting_duplicate_exchange_instrument_id"
        elif row.exchange_instrument_id.strip() in seen_keys:
            duplicates += 1
            continue
        else:
            if key_occurrences.get(row.exchange_instrument_id.strip(), 0) > 1:
                seen_keys.add(row.exchange_instrument_id.strip())
            if row.source_fields.get("DelFlg", "").strip().upper() == "Y":
                reason = "source_deleted_flag"
            elif source_symbol.upper().endswith("NSETEST"):
                # NSE's master specification identifies the NSETEST suffix as a
                # dummy/test security marker.
                reason = "documented_test_instrument"
            elif row.source_fields.get("PrtdToTrad", "").strip() == "2":
                # NSE's published legacy security-master specification defines
                # value 2 as a BSE-listed exclusive instrument. Keep it out of
                # NSE listing admission pending a current MII-specific mapping.
                reason = "exchange_exclusive_bse_listing"
            elif row.source_fields.get("SctyStsNrmlMkt", "").strip() == "3":
                reason = "source_suspended_normal_market"
            elif row.source_fields.get("ElgbltyNrmlMkt", "").strip() == "0":
                # In NSE's CM MII master, PrtdToTrad=0 denotes a security
                # directly listed on NSE (as opposed to the "Permitted to Trade"
                # category PrtdToTrad=1/2), whereas ElgbltyNrmlMkt=0 marks an
                # instrument not eligible to trade in the normal market.
                reason = "source_not_permitted_to_trade"
            elif not isin or not is_valid_isin(isin):
                reason = "missing_or_invalid_isin_identity"
            elif len(listing_candidates) != 1:
                reason = "missing_or_ambiguous_exchange_instrument_mapping"
            else:
                listing_id, security_id = listing_candidates[0]
        if reason is None and isin:
            isin_rows = approved_by_isin.get(isin, set())
            if len(isin_rows) != 1 or next(iter(isin_rows), None) != security_id:
                reason = "missing_conflicting_or_mismatched_approved_isin_mapping"
                unresolved += 1

        if reason:
            qid = "master-q-" + hashlib.sha256(
                f"{source_document_id}|{parser_version}|{locator}|{reason}".encode()
            ).hexdigest()[:32]
            detail = json.dumps({"exchange": exchange, "instrument_id": row.exchange_instrument_id,
                                 "isin": row.isin, "parser_version": parser_version,
                                 "fields": row.source_fields}, ensure_ascii=False, sort_keys=True)
            prior = prior_quarantine.get(qid)
            if prior is not None:
                if prior != (reason, detail):
                    raise RepositoryIntegrityError("quarantine revision ID collides with different extracted content")
                duplicates += 1
                continue
            if reason == "conflicting_duplicate_exchange_instrument_id":
                conflicts += 1
            elif reason == "source_deleted_flag":
                deleted += 1
            elif reason == "documented_test_instrument":
                out_of_scope += 1
                test_instruments += 1
            elif reason == "exchange_exclusive_bse_listing":
                out_of_scope += 1
                exchange_exclusive += 1
            elif reason == "source_suspended_normal_market":
                out_of_scope += 1
                suspended += 1
            elif reason == "source_not_permitted_to_trade":
                out_of_scope += 1
                not_permitted += 1
            elif reason in ("missing_or_invalid_isin_identity", "missing_or_ambiguous_exchange_instrument_mapping",
                            "missing_conflicting_or_mismatched_approved_isin_mapping"):
                unresolved += 1
            elif reason == "malformed_required_identity_fields":
                rejected += 1
            quarantine_inserts.append((qid, source_document_id, locator, reason, detail))
            quarantined += 1
            continue
        sid = "class-" + hashlib.sha256(
            f"{source_document_id}|{listing_id}|{locator}|{parser_version}".encode()
        ).hexdigest()[:32]
        exists = repository._connection.execute(
            "SELECT 1 FROM listing_classification_snapshot WHERE listing_id=? AND source_document_id=? AND extraction_locator=?",
            [listing_id, source_document_id, locator],
        ).fetchone()
        if exists:
            duplicates += 1
            continue
        repository.append_listing_classification_snapshot({
            "listing_classification_snapshot_id": sid,
            "listing_id": listing_id,
            "exchange": exchange,
            "source_document_id": source_document_id,
            "source_snapshot_date": source_snapshot_date,
            "raw_exchange_instrument_id": row.exchange_instrument_id,
            "raw_isin": row.isin,
            "raw_symbol": row.symbol,
            "raw_series": row.series,
            "raw_listing_status": row.raw_listing_status,
            "source_fields_json": row.source_fields,
            "parser_version": parser_version,
            "extraction_locator": locator,
        })
        snapshots += 1
    if quarantine_inserts:
        repository._connection.executemany(
            """INSERT INTO observation_quarantine
               (quarantine_id,source_document_id,source_locator,reason_code,detail,quarantined_at)
               VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)""",
            quarantine_inserts,
        )
    return MasterIntakeReport(snapshots, duplicates, quarantined, source_snapshot_date,
                              snapshots, unresolved, conflicts, deleted, out_of_scope, rejected,
                              suspended, not_permitted, exchange_exclusive, test_instruments)


def ingest_nse_mii_file(
    repository: DuckDBRepository,
    source_path: Path,
    *,
    archive_root: Path,
    source_snapshot_date: date,
    parser_version: str,
    retention_authorized: bool,
) -> NseMasterIngestion:
    """Archive and append one user-supplied NSE CM-MII file and its row review facts.

    The filename/source date is not used as publication time. Since no reliable
    publication timestamp accompanies these local files, the capture date is
    recorded as a conservative date-only availability bound. No effective
    listing intervals are created from the master snapshot.
    """
    if not parser_version.strip():
        raise RepositoryIntegrityError("parser_version is required")
    if source_path.name.lower().endswith(".csv.gz"):
        source_identifier = source_path.name[:-7]
    else:
        source_identifier = source_path.stem
    source_identifier = re.sub(r"\s+\(\d+\)$", "", source_identifier)
    captured_date = datetime.now(MARKET_TIMEZONE).date()
    registered = register_local_exchange_source(
        repository, source_path, archive_root=archive_root, exchange="NSE", dataset="CM-MII-security",
        source_identifier=source_identifier, source_document_date=source_snapshot_date,
        publication_date=captured_date, published_at=None, parser_version=parser_version,
        source_as_of_date=source_snapshot_date, retention_authorized=retention_authorized,
        source_metadata={
            "source_origin": "user-supplied; official origin not independently authenticated",
            "source_snapshot_date_basis": "filename-date-convention; publication-not-verified",
            "publication_date_basis": "actual-local-capture-date-conservative-date-only-bound",
            "format": "NSE CM MII security CSV gzip",
        },
    )
    previous_success = repository._connection.execute(
        """SELECT processing_revision_id,accepted_count,quarantined_count
           FROM source_document_processing_revision
           WHERE source_document_id=? AND parser_version=? AND status='succeeded'
           ORDER BY attempt_number DESC LIMIT 1""",
        [registered.source_document_id, parser_version],
    ).fetchone()
    if previous_success is not None:
        rows = parse_nse_mii_master(source_path)
        total_rows = len(rows)
        return NseMasterIngestion(
            registered,
            MasterIntakeReport(0, total_rows, 0, source_snapshot_date,
                               0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            parser_version, previous_success[0],
        )

    prior = repository._connection.execute(
        """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
           WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""",
        [registered.source_document_id],
    ).fetchone()
    attempt = prior[1] + 1 if prior else 1
    now = datetime.now().astimezone()
    processing_id = "proc-" + hashlib.sha256(
        f"{registered.source_document_id}|{parser_version}|{attempt}".encode()
    ).hexdigest()[:32]
    with repository._transaction():
        repository._connection.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,status,
                accepted_count,rejected_count,quarantined_count,supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,'started',0,0,0,?)""",
            [processing_id, registered.source_document_id, parser_version, attempt, now,
             prior[0] if prior else None],
        )
    try:
        rows = parse_nse_mii_master(source_path)
        with repository._transaction():
            report = intake_master_snapshot(
                repository, source_document_id=registered.source_document_id,
                source_snapshot_date=source_snapshot_date, parser_version=parser_version, rows=rows,
            )
            repository._connection.execute(
                """UPDATE source_document_processing_revision SET completed_at=?,status='succeeded',
                   accepted_count=?,rejected_count=?,quarantined_count=? WHERE processing_revision_id=?""",
                [datetime.now().astimezone(), report.accepted_records, report.rejected_records,
                 report.quarantined, processing_id],
            )
    except Exception as exc:
        with repository._transaction():
            repository._connection.execute(
                """UPDATE source_document_processing_revision SET completed_at=?,status='failed',error_summary=?
                   WHERE processing_revision_id=?""",
                [datetime.now().astimezone(), str(exc)[:2000], processing_id],
            )
        raise
    return NseMasterIngestion(registered, report, parser_version, processing_id)
