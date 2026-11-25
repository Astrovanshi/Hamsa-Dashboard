"""Append-only SQLite store for human-authored Hamsa 11 reviews."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable
from uuid import uuid4

from hamsa.domain.filters import FILTERS, FilterKey, ReviewStatus, EvidenceReference


class DossierReviewRepository:
    """Human review ledger; source references are checked against DuckDB."""

    def __init__(self, database_path: str | Path, *, schema_path: str | Path,
                 analytics_repository=None) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.analytics_repository = analytics_repository
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(Path(schema_path).read_text(encoding="utf-8"))

    def _require_entity(self, entity_id: str) -> None:
        if self.analytics_repository is None or self.analytics_repository._connection.execute(
            "SELECT 1 FROM issuer_entity WHERE entity_id=?", [entity_id]
        ).fetchone() is None:
            raise ValueError("issuer entity is not registered in the analytical database")

    def current_reviews(self, entity_id: str) -> dict[str, sqlite3.Row]:
        rows = self.connection.execute(
            """SELECT r.* FROM filter_review r WHERE r.entity_id=? AND NOT EXISTS
               (SELECT 1 FROM filter_review n WHERE n.supersedes_review_id=r.review_id)
               ORDER BY r.reviewed_at,r.review_id""", (entity_id,)
        ).fetchall()
        by_filter: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_filter.setdefault(row["filter_key"], []).append(row)
        if any(len(items) > 1 for items in by_filter.values()):
            raise ValueError("review history contains branching current records; manual repair required")
        return {key: items[0] for key, items in by_filter.items()}

    def history(self, entity_id: str, filter_key: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM filter_review WHERE entity_id=?"
        params: list[str] = [entity_id]
        if filter_key:
            sql += " AND filter_key=?"
            params.append(filter_key)
        return self.connection.execute(sql + " ORDER BY reviewed_at,review_id", params).fetchall()

    def append_review(self, *, entity_id: str, filter_key: str, status: str, reviewer: str,
                      rationale: str, evidence: Iterable[EvidenceReference] = ()) -> str:
        allowed = {item.key.value for item in FILTERS}
        if filter_key not in allowed:
            raise ValueError("unknown Hamsa 11 filter key")
        if status not in {item.value for item in ReviewStatus}:
            raise ValueError("status must be Pass, Unproven, or Fail")
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("reviewer and rationale are required")
        self._require_entity(entity_id)
        reviewed_at = datetime.now(timezone.utc)
        evidence = tuple(evidence)
        if status in (ReviewStatus.PASS.value, ReviewStatus.FAIL.value) and not evidence:
            raise ValueError("Pass and Fail assessments require at least one verified source citation")
        for item in evidence:
            if not all((item.source_document_id, item.source_identifier, item.locator, item.note)):
                raise ValueError("evidence requires source, source identifier, locator, and note")
            if len(item.checksum_sha256) != 64:
                raise ValueError("evidence source checksum must be SHA-256")
            if self.analytics_repository is None:
                raise ValueError("cannot validate evidence without the analytical repository")
            source = self.analytics_repository._connection.execute(
                "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
                [item.source_document_id],
            ).fetchone()
            if source != (item.source_identifier, item.checksum_sha256):
                raise ValueError("evidence does not match the referenced analytical source document")
        current = self.current_reviews(entity_id).get(filter_key)
        review_id = "review-" + uuid4().hex
        try:
            with self.connection:
                self.connection.execute(
                    """INSERT INTO filter_review
                       (review_id,entity_id,filter_key,status,reviewer,reviewed_at,rationale,supersedes_review_id)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (review_id, entity_id, filter_key, status, reviewer.strip(), reviewed_at.isoformat(),
                     rationale.strip(), current["review_id"] if current else None),
                )
                for item in evidence:
                    self.connection.execute(
                        """INSERT INTO filter_review_evidence
                           (review_id,source_document_id,source_identifier,checksum_sha256,locator,note)
                           VALUES (?,?,?,?,?,?)""",
                        (review_id, item.source_document_id, item.source_identifier, item.checksum_sha256,
                         item.locator, item.note),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"review append failed: {exc}") from exc
        return review_id

    def evidence_for(self, review_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM filter_review_evidence WHERE review_id=? ORDER BY source_document_id,locator",
            (review_id,),
        ).fetchall()

    @staticmethod
    def _latest_leaf(connection: sqlite3.Connection, table: str, id_column: str,
                     supersedes_column: str, entity_id: str) -> sqlite3.Row | None:
        if table not in {"research_watchlist_revision", "company_research_note_revision"}:
            raise ValueError("unsupported append-only ledger table")
        rows = connection.execute(
            f"""SELECT * FROM {table} r WHERE entity_id=? AND NOT EXISTS
                (SELECT 1 FROM {table} n WHERE n.{supersedes_column}=r.{id_column})
                ORDER BY recorded_at DESC,{id_column} DESC""", (entity_id,)
        ).fetchall()
        if len(rows) > 1:
            raise ValueError(f"{table} has multiple current leaves; manual review required")
        return rows[0] if rows else None

    def append_watchlist_event(self, *, entity_id: str, status: str, reviewer: str,
                               rationale: str, recorded_at: datetime | None = None) -> str:
        allowed = {"watch", "research_priority", "cooling", "rejected"}
        if status not in allowed or not reviewer.strip() or not rationale.strip():
            raise ValueError("watchlist event needs a valid status, reviewer, and rationale")
        self._require_entity(entity_id)
        recorded_at = recorded_at or datetime.now(timezone.utc)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        current = self._latest_leaf(self.connection, "research_watchlist_revision", "revision_id",
                                    "supersedes_revision_id", entity_id)
        revision_id = "watch-" + uuid4().hex
        with self.connection:
            self.connection.execute(
                """INSERT INTO research_watchlist_revision
                   (revision_id,entity_id,status,reviewer,recorded_at,rationale,supersedes_revision_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (revision_id, entity_id, status, reviewer.strip(), recorded_at.isoformat(), rationale.strip(),
                 current["revision_id"] if current else None),
            )
        return revision_id

    def append_company_research_note(self, *, entity_id: str, business_thesis: str,
            thesis_killers: str, reviewer: str, next_review_date: str | None = None,
            evidence: Iterable[EvidenceReference] = (), recorded_at: datetime | None = None) -> str:
        if not reviewer.strip() or not business_thesis.strip() or not thesis_killers.strip():
            raise ValueError("research note requires thesis, thesis killers, and reviewer")
        self._require_entity(entity_id)
        if next_review_date:
            from datetime import date
            date.fromisoformat(next_review_date)
        recorded_at = recorded_at or datetime.now(timezone.utc)
        if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        evidence = tuple(evidence)
        if not evidence:
            raise ValueError("business thesis and thesis killers must retain at least one source citation")
        for item in evidence:
            if self.analytics_repository is None:
                raise ValueError("cannot validate evidence without the analytical repository")
            source = self.analytics_repository._connection.execute(
                "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
                [item.source_document_id],
            ).fetchone()
            if source != (item.source_identifier, item.checksum_sha256) or not item.locator.strip() or not item.note.strip():
                raise ValueError("research note evidence does not match a source document")
        current = self._latest_leaf(self.connection, "company_research_note_revision", "note_revision_id",
                                    "supersedes_note_revision_id", entity_id)
        note_id = "note-" + uuid4().hex
        with self.connection:
            self.connection.execute(
                """INSERT INTO company_research_note_revision
                   (note_revision_id,entity_id,business_thesis,thesis_killers,next_review_date,reviewer,
                    recorded_at,supersedes_note_revision_id) VALUES (?,?,?,?,?,?,?,?)""",
                (note_id, entity_id, business_thesis.strip(), thesis_killers.strip(), next_review_date,
                 reviewer.strip(), recorded_at.isoformat(), current["note_revision_id"] if current else None),
            )
            for item in evidence:
                self.connection.execute(
                    """INSERT INTO company_research_note_evidence
                       (note_revision_id,source_document_id,source_identifier,checksum_sha256,locator,note)
                       VALUES (?,?,?,?,?,?)""",
                    (note_id, item.source_document_id, item.source_identifier, item.checksum_sha256,
                     item.locator, item.note),
                )
        return note_id

    def watchlist(self) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT r.* FROM research_watchlist_revision r WHERE NOT EXISTS
               (SELECT 1 FROM research_watchlist_revision n WHERE n.supersedes_revision_id=r.revision_id)
               ORDER BY r.recorded_at DESC,r.revision_id"""
        ).fetchall()

    def latest_company_note(self, entity_id: str) -> sqlite3.Row | None:
        return self._latest_leaf(self.connection, "company_research_note_revision", "note_revision_id",
                                 "supersedes_note_revision_id", entity_id)

    def latest_company_research_note(self, entity_id: str) -> sqlite3.Row | None:
        return self.latest_company_note(entity_id)

    def research_note_evidence(self, note_revision_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM company_research_note_evidence WHERE note_revision_id=? ORDER BY source_document_id,locator",
            (note_revision_id,),
        ).fetchall()

    def company_research_note_evidence(self, note_revision_id: str) -> list[sqlite3.Row]:
        return self.research_note_evidence(note_revision_id)

    def append_business_classification_review(self, *, entity_id: str, business_class: str,
            valid_from: str, valid_to: str | None, reviewer: str, rationale: str,
            source_document_id: str, locator: str, review_status: str = "approved",
            reviewed_at: datetime | None = None) -> str:
        from datetime import date
        if business_class not in ("financial", "industrial") or review_status not in ("approved", "rejected"):
            raise ValueError("business class must be financial/industrial and status approved/rejected")
        self._require_entity(entity_id)
        start = date.fromisoformat(valid_from)
        end = date.fromisoformat(valid_to) if valid_to else None
        if end and end < start:
            raise ValueError("business-class applicability interval is invalid")
        if not reviewer.strip() or not rationale.strip() or not locator.strip():
            raise ValueError("classification review requires reviewer, rationale, and source locator")
        if self.analytics_repository is None:
            raise ValueError("cannot approve a classification without analytical source validation")
        source = self.analytics_repository._connection.execute(
            "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
            [source_document_id],
        ).fetchone()
        if source is None:
            raise ValueError("classification evidence source is not registered")
        decision_time = reviewed_at.astimezone(timezone.utc) if reviewed_at is not None else datetime.now(timezone.utc)
        current_rows = self.connection.execute(
            """SELECT r.* FROM issuer_business_classification_review_revision r
               WHERE r.entity_id=? AND NOT EXISTS (SELECT 1 FROM issuer_business_classification_review_revision n
                 WHERE n.supersedes_review_revision_id=r.review_revision_id)
               ORDER BY r.recorded_at,r.review_revision_id""", (entity_id,)
        ).fetchall()
        parent = None
        for row in current_rows:
            if row["review_status"] != "approved":
                continue
            other_start = date.fromisoformat(row["valid_from"])
            other_end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
            if start <= (other_end or date.max) and other_start <= (end or date.max):
                if (start, end) == (other_start, other_end):
                    parent = row
                else:
                    raise ValueError("approved issuer business-class intervals overlap; resolve with an evidence-backed interval review")
        revision_id = "business-class-" + uuid4().hex
        now = decision_time if reviewed_at is not None else datetime.now(timezone.utc)
        with self.connection:
            self.connection.execute(
                """INSERT INTO issuer_business_classification_review_revision
                   (review_revision_id,entity_id,business_class,valid_from,valid_to,review_status,reviewer,
                    reviewed_at,recorded_at,rationale,evidence_source_document_id,evidence_source_identifier,
                    evidence_checksum_sha256,evidence_locator,supersedes_review_revision_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (revision_id,entity_id,business_class,start.isoformat(),end.isoformat() if end else None,
                 review_status,reviewer.strip(),decision_time.isoformat(),now.isoformat(),rationale.strip(),
                 source_document_id,source[0],source[1],locator.strip(),
                 parent["review_revision_id"] if parent else None),
            )
        return revision_id

    def business_class_as_of(self, *, entity_id: str, session_date: date, cutoff: datetime,
                             exchange: str, availability_mode: str, calendar_version: str) -> str:
        if self.analytics_repository is None or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            return "unclassified"
        rows = self.connection.execute(
            """SELECT r.* FROM issuer_business_classification_review_revision r
               WHERE r.entity_id=? AND r.review_status='approved' AND r.valid_from<=?
                 AND (r.valid_to IS NULL OR r.valid_to>=?) AND r.reviewed_at<=? AND r.recorded_at<=?
                 AND NOT EXISTS (SELECT 1 FROM issuer_business_classification_review_revision n
                   WHERE n.supersedes_review_revision_id=r.review_revision_id AND n.recorded_at<=?)""",
            (entity_id,session_date.isoformat(),session_date.isoformat(),cutoff.isoformat(),cutoff.isoformat(),cutoff.isoformat()),
        ).fetchall()
        eligible = []
        for row in rows:
            if self.analytics_repository._source_available(row["evidence_source_document_id"],
                exchange=exchange,screen_date=session_date,cutoff=cutoff,
                availability_mode=availability_mode,calendar_version=calendar_version):
                eligible.append(row["business_class"])
        return eligible[0] if len(eligible) == 1 else "unclassified"

    ENGINE_EVIDENCE_KEYS: tuple[str, ...] = (
        "commissioning",
        "demand",
        "customer_evidence",
        "documented_expansion",
        "forced_selling",
        "absorption_capacity",
    )

    def append_engine_evidence_review(
        self,
        *,
        entity_id: str,
        evidence_key: str,
        review_status: str,
        valid_from: str,
        valid_to: str | None = None,
        reviewer: str,
        rationale: str,
        source_document_id: str | None = None,
        locator: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> str:
        """Append a human-authored, source-cited qualitative engine evidence review."""
        from datetime import date

        if evidence_key not in self.ENGINE_EVIDENCE_KEYS:
            raise ValueError(f"unsupported engine evidence key: {evidence_key}")
        if review_status not in ("approved", "rejected", "unproven"):
            raise ValueError("engine evidence review_status must be approved, rejected, or unproven")
        self._require_entity(entity_id)
        start = date.fromisoformat(valid_from)
        end = date.fromisoformat(valid_to) if valid_to else None
        if end and end < start:
            raise ValueError("engine evidence applicability interval is invalid")
        if not reviewer.strip() or not rationale.strip():
            raise ValueError("engine evidence review requires reviewer and rationale")
        source_identifier = source_checksum = clean_locator = None
        if review_status in ("approved", "rejected"):
            if not source_document_id or not locator or not locator.strip():
                raise ValueError("approved/rejected engine evidence review requires source_document_id and locator")
            if self.analytics_repository is None:
                raise ValueError("cannot validate engine evidence source without analytical repository")
            source = self.analytics_repository._connection.execute(
                "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
                [source_document_id],
            ).fetchone()
            if source is None:
                raise ValueError("engine evidence source document is not registered")
            source_identifier, source_checksum = source[0], source[1]
            clean_locator = locator.strip()
        elif source_document_id:
            if self.analytics_repository is None:
                raise ValueError("cannot validate engine evidence source without analytical repository")
            source = self.analytics_repository._connection.execute(
                "SELECT source_identifier,checksum_sha256 FROM source_document_revision WHERE source_document_id=?",
                [source_document_id],
            ).fetchone()
            if source is None:
                raise ValueError("engine evidence source document is not registered")
            source_identifier, source_checksum = source[0], source[1]
            clean_locator = (locator or "").strip() or None
        else:
            source_document_id = None

        current_rows = self.connection.execute(
            """SELECT r.* FROM engine_evidence_review_revision r
               WHERE r.entity_id=? AND r.evidence_key=?
                 AND NOT EXISTS (
                   SELECT 1 FROM engine_evidence_review_revision n
                   WHERE n.supersedes_review_revision_id=r.review_revision_id
                 )
               ORDER BY r.recorded_at,r.review_revision_id""",
            (entity_id, evidence_key),
        ).fetchall()
        parent = None
        for row in current_rows:
            other_start = date.fromisoformat(row["valid_from"])
            other_end = date.fromisoformat(row["valid_to"]) if row["valid_to"] else None
            if start <= (other_end or date.max) and other_start <= (end or date.max):
                if (start, end) == (other_start, other_end):
                    parent = row
                elif row["review_status"] != "unproven" and review_status != "unproven":
                    raise ValueError(
                        "engine evidence intervals overlap for the same key; supersede the exact interval or separate ranges"
                    )
        revision_id = "engev-" + uuid4().hex
        now = reviewed_at.astimezone(timezone.utc) if reviewed_at is not None else datetime.now(timezone.utc)
        with self.connection:
            self.connection.execute(
                """INSERT INTO engine_evidence_review_revision
                   (review_revision_id,entity_id,evidence_key,review_status,valid_from,valid_to,
                    reviewer,reviewed_at,recorded_at,rationale,evidence_source_document_id,
                    evidence_source_identifier,evidence_checksum_sha256,evidence_locator,
                    supersedes_review_revision_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    revision_id, entity_id, evidence_key, review_status,
                    start.isoformat(), end.isoformat() if end else None,
                    reviewer.strip(), now.isoformat(), now.isoformat(), rationale.strip(),
                    source_document_id, source_identifier, source_checksum, clean_locator,
                    parent["review_revision_id"] if parent else None,
                ),
            )
        return revision_id

    def current_engine_evidence_reviews(self, entity_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT r.* FROM engine_evidence_review_revision r
               WHERE r.entity_id=?
                 AND NOT EXISTS (
                   SELECT 1 FROM engine_evidence_review_revision n
                   WHERE n.supersedes_review_revision_id=r.review_revision_id
                 )
               ORDER BY r.evidence_key,r.valid_from,r.recorded_at""",
            (entity_id,),
        ).fetchall()

    def engine_evidence_as_of(
        self,
        *,
        entity_id: str,
        session_date,
        cutoff: datetime,
        exchange: str,
        availability_mode: str,
        calendar_version: str,
    ) -> tuple[dict[str, bool | None], dict[str, tuple[str, ...]]]:
        """Return point-in-time human-reviewed qualitative engine evidence gates and source citations."""
        if self.analytics_repository is None or cutoff.tzinfo is None or cutoff.utcoffset() is None:
            return {}, {}
        rows = self.connection.execute(
            """SELECT r.* FROM engine_evidence_review_revision r
               WHERE r.entity_id=? AND r.valid_from<=?
                 AND (r.valid_to IS NULL OR r.valid_to>=?)
                 AND r.reviewed_at<=? AND r.recorded_at<=?
                 AND NOT EXISTS (
                   SELECT 1 FROM engine_evidence_review_revision n
                   WHERE n.supersedes_review_revision_id=r.review_revision_id AND n.recorded_at<=?
                 )
               ORDER BY r.evidence_key,r.recorded_at,r.review_revision_id""",
            (
                entity_id, session_date.isoformat(), session_date.isoformat(),
                cutoff.isoformat(), cutoff.isoformat(), cutoff.isoformat(),
            ),
        ).fetchall()
        by_key: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            doc_id = row["evidence_source_document_id"]
            if doc_id and not self.analytics_repository._source_available(
                doc_id, exchange=exchange, screen_date=session_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            ):
                continue
            by_key.setdefault(row["evidence_key"], []).append(row)
        evidence_map: dict[str, bool | None] = {}
        sources_map: dict[str, tuple[str, ...]] = {}
        for key, candidates in by_key.items():
            if len(candidates) != 1:
                evidence_map[key] = None
                continue
            row = candidates[0]
            if row["review_status"] == "approved" and row["evidence_source_document_id"]:
                evidence_map[key] = True
                sources_map[key] = (str(row["evidence_source_document_id"]),)
            elif row["review_status"] == "rejected" and row["evidence_source_document_id"]:
                evidence_map[key] = False
                sources_map[key] = (str(row["evidence_source_document_id"]),)
            else:
                evidence_map[key] = None
        return evidence_map, sources_map

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "DossierReviewRepository":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
