"""Local-file NSE/BSE calendar import using the existing schema v3 table."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import re

from hamsa.domain.trading_calendar import Calendar
from hamsa.ingestion.source_registry import register_local_exchange_source
from hamsa.storage.duckdb_repository import DuckDBRepository, RepositoryIntegrityError


@dataclass(frozen=True, slots=True)
class CalendarRow:
    exchange: str
    session_date: date
    is_trading_session: bool
    session_type: str


@dataclass(frozen=True, slots=True)
class CalendarImportReport:
    exchange: str
    calendar_version: str
    source_document_id: str
    checksum_sha256: str
    accepted: int
    duplicates: int


@dataclass(frozen=True, slots=True)
class CalendarImportSpec:
    exchange: str
    calendar_version: str
    source_identifier: str
    source_document_date: date
    publication_date: date
    parser_version: str
    published_at: datetime | None = None
    source_as_of_date: date | None = None
    retention_authorized: bool = False

    def __post_init__(self) -> None:
        if self.exchange not in ("NSE", "BSE"):
            raise ValueError("exchange must be NSE or BSE")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,127}", self.calendar_version):
            raise ValueError("calendar_version must be an explicit immutable identifier (3-128 safe characters)")
        if not self.source_identifier.strip() or not self.parser_version.strip():
            raise ValueError("source_identifier and parser_version are required")
        if self.published_at is not None:
            if self.published_at.tzinfo is None or self.published_at.utcoffset() is None:
                raise ValueError("published_at must be timezone-aware")
            from hamsa.domain.trading_calendar import MARKET_TIMEZONE
            if self.published_at.astimezone(MARKET_TIMEZONE).date() != self.publication_date:
                raise ValueError("published_at local date must match publication_date")


def parse_calendar_csv(path: Path, *, expected_exchange: str) -> tuple[CalendarRow, ...]:
    """Parse an explicit calendar CSV. Every included date is supplied in-file.

    Required header: exchange,session_date,is_trading_session,session_type.
    Closed dates, including weekends within the supplied coverage, must be
    explicit `holiday,false` rows; no weekday or holiday inference is done.
    """
    if expected_exchange not in ("NSE", "BSE"):
        raise RepositoryIntegrityError("calendar venue must be NSE or BSE")
    required = {"exchange", "session_date", "is_trading_session", "session_type"}
    rows: list[CalendarRow] = []
    seen: set[date] = set()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            headers = [str(name).strip() for name in (reader.fieldnames or [])]
            if not headers or len(headers) != len(set(headers)):
                raise RepositoryIntegrityError("calendar CSV has a missing or duplicate header")
            if not required.issubset(headers):
                raise RepositoryIntegrityError(f"calendar CSV missing columns: {', '.join(sorted(required - set(headers)))}")
            for row in reader:
                if None in row:
                    raise RepositoryIntegrityError(f"calendar CSV has extra fields at line {reader.line_num}")
                fields = {(key or "").strip(): (value or "").strip() for key, value in row.items()}
                venue = fields["exchange"].upper()
                if venue != expected_exchange:
                    raise RepositoryIntegrityError(
                        f"calendar file venue {venue!r} does not match requested {expected_exchange}"
                    )
                try:
                    day = date.fromisoformat(fields["session_date"])
                except ValueError as exc:
                    raise RepositoryIntegrityError(f"invalid ISO session date at line {reader.line_num}") from exc
                if day in seen:
                    raise RepositoryIntegrityError(f"duplicate session date in calendar file: {day}")
                seen.add(day)
                is_open = fields["is_trading_session"].lower()
                if is_open not in {"true", "false"}:
                    raise RepositoryIntegrityError(f"invalid trading flag at line {reader.line_num}")
                session_type = fields["session_type"].lower()
                if session_type not in {"regular", "special", "holiday"}:
                    raise RepositoryIntegrityError(f"invalid session type at line {reader.line_num}")
                trading = is_open == "true"
                if (session_type == "holiday") == trading:
                    raise RepositoryIntegrityError("holiday rows must be closed; regular/special rows must be open")
                rows.append(CalendarRow(venue, day, trading, session_type))
    except csv.Error as exc:
        raise RepositoryIntegrityError(f"malformed calendar CSV: {exc}") from exc
    if not rows:
        raise RepositoryIntegrityError("calendar file contains no records")
    rows.sort(key=lambda row: row.session_date)
    if rows[-1].session_date.toordinal() - rows[0].session_date.toordinal() + 1 != len(rows):
        raise RepositoryIntegrityError("calendar file has missing dates within its declared row coverage")
    return tuple(rows)


def import_exchange_calendar(
    repository: DuckDBRepository,
    source_path: Path,
    *,
    archive_root: Path,
    spec: CalendarImportSpec,
) -> CalendarImportReport:
    """Archive then import one immutable explicitly-versioned calendar file.

    Archival/source registration occurs before parsing. Session writes are
    atomic. Replaying identical bytes/version is idempotent; any changed rows,
    bytes, or source document under an existing version fail without overwrite.
    """
    if not spec.retention_authorized:
        raise RepositoryIntegrityError("local calendar archival requires explicit retention_authorized=True")
    registered = register_local_exchange_source(
        repository, source_path, archive_root=archive_root,
        exchange=spec.exchange, dataset="exchange_trading_calendar",
        source_identifier=spec.source_identifier,
        source_document_date=spec.source_document_date,
        publication_date=spec.publication_date,
        published_at=spec.published_at, source_as_of_date=spec.source_as_of_date,
        parser_version=spec.parser_version, retention_authorized=True,
    )
    rows = parse_calendar_csv(source_path, expected_exchange=spec.exchange)
    existing = repository._connection.execute(
        """SELECT session_date,is_trading_session,session_type,source_document_id
           FROM exchange_trading_session WHERE exchange=? AND calendar_version=? ORDER BY session_date""",
        [spec.exchange, spec.calendar_version],
    ).fetchall()
    proposed = [(row.session_date, row.is_trading_session, row.session_type, registered.source_document_id)
                for row in rows]
    if existing:
        if existing != proposed:
            raise RepositoryIntegrityError(
                "calendar version already exists with different rows or provenance; choose a new version"
            )
        return CalendarImportReport(spec.exchange, spec.calendar_version, registered.source_document_id,
                                    registered.checksum_sha256, 0, len(rows))

    with repository._transaction():
        for row in rows:
            repository._connection.execute(
                """INSERT INTO exchange_trading_session
                   (exchange,session_date,is_trading_session,session_type,calendar_version,source_document_id)
                   VALUES (?,?,?,?,?,?)""",
                [row.exchange, row.session_date, row.is_trading_session, row.session_type,
                 spec.calendar_version, registered.source_document_id],
            )
    return CalendarImportReport(spec.exchange, spec.calendar_version, registered.source_document_id,
                                registered.checksum_sha256, len(rows), 0)


class RepositoryExchangeCalendar(Calendar):
    """A calendar selector explicitly bound to one exchange and v3 version."""

    def __init__(self, repository: DuckDBRepository, *, exchange: str, version: str):
        if exchange not in ("NSE", "BSE") or not version:
            raise RepositoryIntegrityError("calendar selector requires exchange and explicit version")
        provenance = repository._connection.execute(
            """SELECT count(*),count(DISTINCT s.source_document_id),min(d.provider),max(d.provider)
               FROM exchange_trading_session s
               JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.calendar_version=?""",
            [exchange, version],
        ).fetchone()
        if provenance[0] == 0 or provenance[1] != 1 or not str(provenance[2]).upper().startswith(exchange):
            raise RepositoryIntegrityError("calendar version is missing or has unverified/mixed source provenance")
        self.repository = repository
        self.exchange = exchange
        self.version = version

    def _row(self, session: date):
        return self.repository._connection.execute(
            """SELECT is_trading_session,source_document_id FROM exchange_trading_session
               WHERE exchange=? AND session_date=? AND calendar_version=?""",
            [self.exchange, session, self.version],
        ).fetchone()

    def is_trading_session(self, session: date) -> bool:
        row = self._row(session)
        return bool(row[0]) if row is not None else False

    def next_trading_session(self, after: date) -> date:
        rows = self.repository._connection.execute(
            """SELECT session_date,is_trading_session FROM exchange_trading_session
               WHERE exchange=? AND calendar_version=? AND session_date>? ORDER BY session_date""",
            [self.exchange, self.version, after],
        ).fetchall()
        if not rows:
            raise RepositoryIntegrityError("no later explicit calendar dates; calendar coverage is missing")
        expected = after.toordinal() + 1
        for session_date, is_open in rows:
            if session_date.toordinal() != expected:
                raise RepositoryIntegrityError("calendar has a missing date; refusing to infer a later session")
            if is_open:
                return session_date
            expected += 1
        raise RepositoryIntegrityError("calendar has no later explicit trading session")
