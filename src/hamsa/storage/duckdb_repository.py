"""Application repository with append-only historical observation writes.

There is deliberately no public SQL connection, UPDATE, or DELETE method.
DuckDB file owners retain direct database access and can bypass this boundary;
see the architecture notes for that limitation.
"""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Iterable, Iterator, Mapping

import duckdb

from hamsa.domain.financials import FinancialObservationRevision


class RepositoryIntegrityError(ValueError):
    """An append violates a cross-table or revision-chain invariant."""


class DuckDBRepository:
    SCHEMA_NAME = "hamsa_analytics"
    SCHEMA_VERSION = 6
    BASELINE_MIGRATION = "0001_initial_analytics"
    V2_MIGRATION = "0002_ingestion_processing"
    V3_MIGRATION = "0003_listing_classification_and_eod_reconciliation"
    V4_MIGRATION = "0004_identifier_revision_review"
    V5_MIGRATION = "0005_identifier_review_actor_type"
    CURRENT_MIGRATION = "0006_preserve_traceable_legacy_rejections"
    # This is the checksum of the shipped v1 baseline, not of the current
    # schema file.  It must remain stable so an existing v1 database can be
    # verified and migrated rather than rejected after later DDL is added.
    BASELINE_SCHEMA_CHECKSUM = "2a00ecaa3505f024092b56a1453ac3ac207c113765efcb71f14568c20c67dbee"
    RECONCILIATION_COMPARATORS = {
        "eod-raw-ohlcv-turnover-v1": (
            "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "turnover_raw",
        ),
    }

    @staticmethod
    def eod_reconciliation_stream_id(exchange: str, listing_id: str, trade_date: date) -> str:
        """Return the stable stream key for one venue/listing/session role pair."""
        if exchange not in ("NSE", "BSE") or not listing_id:
            raise RepositoryIntegrityError("reconciliation stream requires an NSE/BSE exchange and listing")
        key = f"{exchange}|{listing_id}|{trade_date.isoformat()}|official|secondary"
        return "eodcmp-" + sha256(key.encode("utf-8")).hexdigest()

    def __init__(self, database_path: str | Path = ":memory:", *, schema_path: str | Path | None = None):
        self._database_path = str(database_path)
        self._schema_path = Path(schema_path) if schema_path else Path(__file__).resolve().parents[3] / "sql" / "duckdb_schema.sql"
        self._connection = duckdb.connect(self._database_path)
        self._transaction_depth = 0
        self._rollback_only = False
        try:
            self._initialize()
        except Exception:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        schema_bytes = self._schema_path.read_bytes()
        self._connection.execute(schema_bytes.decode("utf-8"))
        metadata = self._connection.execute(
            "SELECT current_version, current_migration FROM schema_metadata WHERE schema_name = ?",
            [self.SCHEMA_NAME],
        ).fetchone()
        if metadata is None:
            raise RepositoryIntegrityError("schema metadata row is missing after schema initialization")
        version, migration = metadata
        expected_migration = {
            1: self.BASELINE_MIGRATION,
            2: self.V2_MIGRATION,
            3: self.V3_MIGRATION,
            4: self.V4_MIGRATION,
            5: self.V5_MIGRATION,
            6: self.CURRENT_MIGRATION,
        }.get(version)
        if expected_migration is None or migration != expected_migration:
            raise RepositoryIntegrityError(
                f"unsupported schema metadata: version={version}, migration={migration}"
            )

        existing = self._connection.execute(
            "SELECT migration_checksum_sha256 FROM schema_migration WHERE migration_id = ?",
            [self.BASELINE_MIGRATION],
        ).fetchone()
        if existing is None:
            self._connection.execute(
                """INSERT INTO schema_migration
                   (migration_id, from_version, to_version, migration_checksum_sha256, applied_at, applied_by)
                   VALUES (?, 0, ?, ?, CURRENT_TIMESTAMP, ?)""",
                [self.BASELINE_MIGRATION, 1, self.BASELINE_SCHEMA_CHECKSUM, "hamsa-storage"],
            )
        elif existing[0] != self.BASELINE_SCHEMA_CHECKSUM:
            raise RepositoryIntegrityError(
                "baseline schema checksum differs from the supported v1 migration record"
            )

        self._apply_or_verify_migration(
            migration_id=self.V2_MIGRATION,
            from_version=1,
            to_version=2,
            current_version=version,
            current_migration=migration,
        )
        version, migration = self._connection.execute(
            "SELECT current_version,current_migration FROM schema_metadata WHERE schema_name=?",
            [self.SCHEMA_NAME],
        ).fetchone()
        self._apply_or_verify_migration(
            migration_id=self.V3_MIGRATION,
            from_version=2,
            to_version=3,
            current_version=version,
            current_migration=migration,
        )
        version, migration = self._connection.execute(
            "SELECT current_version,current_migration FROM schema_metadata WHERE schema_name=?",
            [self.SCHEMA_NAME],
        ).fetchone()
        self._apply_or_verify_migration(
            migration_id=self.V4_MIGRATION,
            from_version=3,
            to_version=4,
            current_version=version,
            current_migration=migration,
        )
        version, migration = self._connection.execute(
            "SELECT current_version,current_migration FROM schema_metadata WHERE schema_name=?",
            [self.SCHEMA_NAME],
        ).fetchone()
        self._apply_or_verify_migration(
            migration_id=self.V5_MIGRATION,
            from_version=4,
            to_version=5,
            current_version=version,
            current_migration=migration,
        )
        version, migration = self._connection.execute(
            "SELECT current_version,current_migration FROM schema_metadata WHERE schema_name=?",
            [self.SCHEMA_NAME],
        ).fetchone()
        self._apply_or_verify_migration(
            migration_id=self.CURRENT_MIGRATION,
            from_version=5,
            to_version=6,
            current_version=version,
            current_migration=migration,
        )

    def _apply_or_verify_migration(
        self,
        *,
        migration_id: str,
        from_version: int,
        to_version: int,
        current_version: int,
        current_migration: str,
    ) -> None:
        migration_path = self._schema_path.parent / "migrations" / f"{migration_id}.sql"
        migration_bytes = migration_path.read_bytes()
        migration_checksum = sha256(migration_bytes).hexdigest()
        recorded = self._connection.execute(
            "SELECT migration_checksum_sha256 FROM schema_migration WHERE migration_id=?",
            [migration_id],
        ).fetchone()
        if current_version == from_version:
            if recorded is not None:
                raise RepositoryIntegrityError(
                    f"schema has a {migration_id} migration row while metadata still reports v{from_version}"
                )
            with self._transaction():
                self._connection.execute(migration_bytes.decode("utf-8"))
                self._connection.execute(
                    """INSERT INTO schema_migration
                       (migration_id,from_version,to_version,migration_checksum_sha256,applied_at,applied_by)
                       VALUES (?,?,?,?,CURRENT_TIMESTAMP,'hamsa-storage')""",
                    [migration_id, from_version, to_version, migration_checksum],
                )
                self._connection.execute(
                    """UPDATE schema_metadata SET current_version=?,current_migration=?,updated_at=CURRENT_TIMESTAMP
                       WHERE schema_name=?""",
                    [to_version, migration_id, self.SCHEMA_NAME],
                )
        elif current_version == to_version:
            if current_migration != migration_id or recorded is None or recorded[0] != migration_checksum:
                raise RepositoryIntegrityError(
                    f"schema {migration_id} checksum is missing or differs; explicit migration required"
                )
        elif current_version > to_version:
            if recorded is None or recorded[0] != migration_checksum:
                raise RepositoryIntegrityError(
                    f"schema {migration_id} checksum is missing or differs; explicit migration required"
                )
        else:
            raise RepositoryIntegrityError(
                f"cannot apply {migration_id} from schema version {current_version}"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        outermost = self._transaction_depth == 0
        if outermost:
            self._connection.execute("BEGIN TRANSACTION")
            self._rollback_only = False
        self._transaction_depth += 1
        try:
            yield
        except Exception:
            self._transaction_depth -= 1
            self._rollback_only = True
            if outermost:
                self._connection.execute("ROLLBACK")
                self._rollback_only = False
            raise
        else:
            self._transaction_depth -= 1
            if outermost:
                if self._rollback_only:
                    self._connection.execute("ROLLBACK")
                    self._rollback_only = False
                    raise RepositoryIntegrityError("transaction is rollback-only after a nested write failure")
                self._connection.execute("COMMIT")

    @staticmethod
    def _same_instant(left, right_text: str | None) -> bool:
        if left is None or right_text is None:
            return left is None and right_text is None
        from datetime import datetime

        right = datetime.fromisoformat(right_text.replace(" ", "T", 1))
        return left.timestamp() == right.timestamp()

    def append_financial_observation(
        self,
        observation: FinancialObservationRevision,
        *,
        lineage_inputs: Iterable[tuple[str, str]] = (),
        extraction_revision_id: str | None = None,
    ) -> str:
        """Append one financial revision and its registry/lineage rows atomically."""
        connection = self._connection
        source = connection.execute(
            """SELECT d.checksum_sha256,
                      d.source_document_date, d.publication_date, CAST(d.published_at AS VARCHAR),
                      CAST(d.ingestion_timestamp AS VARCHAR), d.parser_version
               FROM source_document_revision d
               WHERE d.source_document_id = ?""",
            [observation.source_document_id],
        ).fetchone()
        if source is None:
            raise RepositoryIntegrityError("financial observation references an unknown source document")
        document_checksum, document_date, publication_date, published_at, ingested_at, parser_version = source
        if document_date != observation.source_document_date or publication_date != observation.publication_date:
            raise RepositoryIntegrityError("financial observation publication/document dates disagree with its source document")
        if not self._same_instant(observation.published_at, published_at):
            raise RepositoryIntegrityError("financial observation publication timestamp disagrees with its source document")
        from datetime import datetime

        if observation.ingestion_timestamp.timestamp() < datetime.fromisoformat(
            ingested_at.replace(" ", "T", 1)
        ).timestamp():
            raise RepositoryIntegrityError("financial observation ingestion precedes its source document ingestion")
        # source_document_revision.parser_version is the initial parser recorded
        # when the source bytes were first registered. Reprocessing identical
        # bytes may legitimately use a newer parser; registry and processing
        # revision rows carry the authoritative extraction parser version.

        metric = connection.execute(
            "SELECT canonical_unit, dimension FROM financial_metric_definition WHERE metric = ?",
            [observation.metric],
        ).fetchone()
        if metric is None:
            raise RepositoryIntegrityError("financial observation references an unknown metric")
        if metric[0] != observation.canonical_unit:
            raise RepositoryIntegrityError("financial observation canonical unit disagrees with metric definition")
        if observation.conversion_rule_id is not None:
            rule = connection.execute(
                """SELECT source_unit, canonical_unit, dimension, multiplier, additive_offset, review_status
                   FROM unit_conversion_rule_revision WHERE conversion_rule_id = ?""",
                [observation.conversion_rule_id],
            ).fetchone()
            if rule is None or rule[5] != "approved":
                raise RepositoryIntegrityError("financial observation references an unknown or unapproved unit conversion rule")
            if rule[0] != observation.raw_unit or rule[1] != observation.canonical_unit or rule[2] != metric[1]:
                raise RepositoryIntegrityError("unit conversion rule units or dimension disagree with financial observation")
            if observation.raw_value is not None and observation.canonical_value is not None:
                expected_canonical = observation.raw_value * Decimal(str(rule[3])) + Decimal(str(rule[4]))
                if abs(observation.canonical_value - expected_canonical) > Decimal("0.000000000001"):
                    raise RepositoryIntegrityError("financial observation canonical_value disagrees with conversion rule calculation")
        if connection.execute("SELECT 1 FROM issuer_entity WHERE entity_id = ?", [observation.subject_id]).fetchone() is None:
            raise RepositoryIntegrityError("financial observation references an unknown issuer entity")
        if connection.execute(
            "SELECT 1 FROM financial_observation_revision WHERE observation_id = ?", [observation.observation_id]
        ).fetchone() is not None:
            raise RepositoryIntegrityError("observation_id already exists; revisions require a new ID")

        if observation.supersedes_observation_id:
            parent = connection.execute(
                """SELECT subject_entity_id, metric, period_start, period_end, reporting_scope, revision_number
                   FROM financial_observation_revision WHERE observation_id = ?""",
                [observation.supersedes_observation_id],
            ).fetchone()
            if parent is None:
                raise RepositoryIntegrityError("superseded observation does not exist")
            parent_key = parent[:5]
            new_key = (
                observation.subject_id, observation.metric, observation.period_start,
                observation.period_end, observation.reporting_scope,
            )
            if parent_key != new_key:
                raise RepositoryIntegrityError("a revision must supersede the same financial natural key")
            if observation.revision_number != parent[5] + 1:
                raise RepositoryIntegrityError("revision_number must increment its superseded revision by one")
            branched = connection.execute(
                "SELECT 1 FROM financial_observation_revision WHERE supersedes_observation_id = ?",
                [observation.supersedes_observation_id],
            ).fetchone()
            if branched is not None:
                raise RepositoryIntegrityError("superseded revision already has a successor")
        elif observation.revision_number != 1:
            raise RepositoryIntegrityError("an initial observation must start at revision_number 1")

        inputs = tuple(lineage_inputs)
        if observation.formula_version and not inputs:
            raise RepositoryIntegrityError("derived financial observations require explicit lineage inputs")
        if inputs and not observation.formula_version:
            raise RepositoryIntegrityError("lineage inputs require a formula_version")
        for input_id, input_type in inputs:
            if connection.execute(
                "SELECT 1 FROM normalized_observation_registry WHERE observation_id = ? AND observation_type = ?",
                [input_id, input_type],
            ).fetchone() is None:
                raise RepositoryIntegrityError(f"unknown or mismatched lineage input: {input_id} ({input_type})")

        with self._transaction():
            if extraction_revision_id is None:
                extraction_revision_id = self._ensure_extraction_revision(observation)
            else:
                processing = connection.execute(
                    """SELECT source_document_id,parser_version,status FROM source_document_processing_revision
                       WHERE processing_revision_id=?""",
                    [extraction_revision_id],
                ).fetchone()
                if processing is None or processing[0] != observation.source_document_id or processing[1] != observation.parser_version or processing[2] not in ("started", "succeeded"):
                    raise RepositoryIntegrityError("normalized observation references an invalid extraction revision")
            connection.execute(
                """INSERT INTO normalized_observation_registry
                   (observation_id, observation_type, source_document_id, source_identifier,
                    checksum_sha256, parser_version, extraction_timestamp, extraction_locator, formula_version, extraction_revision_id)
                   SELECT ?, 'financial', d.source_document_id, d.source_identifier, d.checksum_sha256,
                          ?, ?, ?, ?, ?
                   FROM source_document_revision d WHERE d.source_document_id = ?""",
                [
                    observation.observation_id, observation.parser_version, observation.extraction_timestamp,
                    observation.source_locator, observation.formula_version, extraction_revision_id,
                    observation.source_document_id,
                ],
            )
            connection.execute(
                """INSERT INTO financial_observation_revision (
                   observation_id, observation_type, subject_entity_id, metric, raw_value, raw_unit,
                   canonical_value, canonical_unit, conversion_rule_id, period_start, period_end,
                   source_document_date, publication_date, published_at, publication_precision,
                   ingestion_timestamp, revision_number, source_document_id, as_reported_status,
                   quality_status, quality_reason, reporting_scope, parser_version,
                   extraction_timestamp, extraction_locator, formula_version, supersedes_observation_id, replay_timestamp
                   ) VALUES (?, 'financial', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    observation.observation_id, observation.subject_id, observation.metric,
                    observation.raw_value, observation.raw_unit, observation.canonical_value,
                    observation.canonical_unit, observation.conversion_rule_id, observation.period_start, observation.period_end,
                    observation.source_document_date, observation.publication_date, observation.published_at,
                    observation.publication_precision.value, observation.ingestion_timestamp,
                    observation.revision_number, observation.source_document_id,
                    observation.as_reported_status.value, observation.quality_status.value,
                    observation.quality_reason, observation.reporting_scope, observation.parser_version,
                    observation.extraction_timestamp, observation.source_locator, observation.formula_version,
                    observation.supersedes_observation_id,
                    observation.replay_timestamp,
                ],
            )
            for input_id, input_type in inputs:
                connection.execute(
                    """INSERT INTO observation_lineage_input
                       (derived_observation_id, derived_observation_type, input_observation_id,
                        input_observation_type, formula_version)
                       VALUES (?, 'financial', ?, ?, ?)""",
                    [observation.observation_id, input_id, input_type, observation.formula_version],
                )
        return observation.observation_id

    def register_local_source_document(self, source_path: str | Path, **metadata):
        """Archive and register one user-supplied exchange source through the existing source registry."""
        from hamsa.ingestion.source_registry import register_local_exchange_source

        return register_local_exchange_source(self, Path(source_path), **metadata)

    @staticmethod
    def _admission_id(prefix: str, *parts: object) -> str:
        payload = "|".join(str(part) for part in parts)
        return prefix + "-" + sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _require_source_for_exchange(self, source_document_id: str, exchange: str) -> tuple:
        if exchange not in ("NSE", "BSE"):
            raise RepositoryIntegrityError("exchange must be NSE or BSE")
        source = self._connection.execute(
            """SELECT provider,dataset,source_identifier,checksum_sha256,source_document_date,
                      publication_date,CAST(ingestion_timestamp AS VARCHAR)
               FROM source_document_revision WHERE source_document_id=?""", [source_document_id]
        ).fetchone()
        if source is None:
            raise RepositoryIntegrityError("source document is not registered")
        if str(source[0]).upper() != exchange:
            raise RepositoryIntegrityError("source document venue does not match the listing venue")
        return source

    def append_security_identity_candidate(
        self,
        *,
        issuer_entity_id: str,
        security_id: str,
        listing_id: str,
        exchange: str,
        exchange_instrument_id: str,
        isin: str,
        legal_name: str,
        identity_observed_from: date,
        source_document_id: str,
        source_locator: str,
        share_class: str | None = None,
    ) -> dict[str, str]:
        """Create an ISIN-backed identity candidate with a pending mapping review.

        The exchange instrument identifier selects a venue listing only. It is
        never used by itself to resolve a security. No listing status/effective
        interval or investment-universe classification is inferred here.
        """
        from hamsa.domain.security import is_valid_isin

        if not all(str(value).strip() for value in (
            issuer_entity_id, security_id, listing_id, exchange_instrument_id,
            legal_name, source_locator,
        )):
            raise RepositoryIntegrityError("identity candidate requires IDs, instrument reference, name, and source locator")
        isin = isin.strip().upper()
        if not is_valid_isin(isin):
            raise RepositoryIntegrityError("identity candidate ISIN is invalid")
        self._require_source_for_exchange(source_document_id, exchange)
        now = datetime.now().astimezone()
        mapping_id = self._admission_id("idmap", security_id, isin, identity_observed_from, source_document_id)
        name_id = self._admission_id("issuername", issuer_entity_id, legal_name, identity_observed_from, source_document_id)
        with self._transaction():
            issuer = self._connection.execute(
                "SELECT 1 FROM issuer_entity WHERE entity_id=?", [issuer_entity_id]
            ).fetchone()
            if not issuer:
                self._connection.execute("INSERT INTO issuer_entity VALUES (?,?)", [issuer_entity_id, now])
            security = self._connection.execute(
                "SELECT issuer_entity_id FROM equity_security WHERE security_id=?", [security_id]
            ).fetchone()
            if security and security[0] != issuer_entity_id:
                raise RepositoryIntegrityError("security ID is already attached to a different issuer")
            if not security:
                self._connection.execute(
                    "INSERT INTO equity_security VALUES (?,?,?,?)", [security_id, issuer_entity_id, share_class, now]
                )
            existing_listing = self._connection.execute(
                "SELECT listing_id,security_id FROM exchange_listing WHERE exchange=? AND exchange_instrument_id=?",
                [exchange, exchange_instrument_id],
            ).fetchone()
            if existing_listing:
                if existing_listing[0] != listing_id or existing_listing[1] != security_id:
                    raise RepositoryIntegrityError("exchange instrument already maps to a conflicting listing/security")
            else:
                listing_by_id = self._connection.execute(
                    "SELECT security_id,exchange,exchange_instrument_id FROM exchange_listing WHERE listing_id=?",
                    [listing_id],
                ).fetchone()
                if listing_by_id and listing_by_id != (security_id, exchange, exchange_instrument_id):
                    raise RepositoryIntegrityError("listing ID is already attached to a different security or instrument")
                if not listing_by_id:
                    self._connection.execute(
                        "INSERT INTO exchange_listing VALUES (?,?,?,?,?)",
                        [listing_id, security_id, exchange, exchange_instrument_id, now],
                    )
            name_exists = self._connection.execute(
                "SELECT 1 FROM issuer_name_revision WHERE name_revision_id=?", [name_id]
            ).fetchone()
            if not name_exists:
                self._connection.execute(
                    "INSERT INTO issuer_name_revision VALUES (?,?,?,?,?,?,NULL)",
                    [name_id, issuer_entity_id, legal_name.strip(), identity_observed_from, None, source_document_id],
                )

            overlap = self._connection.execute(
                """SELECT security_id,identifier_revision_id,mapping_review_status FROM security_identifier_revision
                   WHERE identifier_type='ISIN' AND identifier_value=?
                     AND effective_from<=COALESCE(?,DATE '9999-12-31')
                     AND COALESCE(effective_to,DATE '9999-12-31')>=?""",
                [isin, None, identity_observed_from],
            ).fetchall()
            conflicts = [row for row in overlap if row[0] != security_id]
            if conflicts:
                raise RepositoryIntegrityError("ISIN overlaps a different security mapping; resolve the conflict before creating a candidate")
            existing_mapping = self._connection.execute(
                """SELECT identifier_revision_id,source_document_id,mapping_review_status
                   FROM security_identifier_revision WHERE security_id=? AND identifier_type='ISIN'
                     AND identifier_value=? AND effective_from=?""",
                [security_id, isin, identity_observed_from],
            ).fetchone()
            if existing_mapping:
                if existing_mapping[1] != source_document_id:
                    raise RepositoryIntegrityError("identity mapping already exists for this effective date with different evidence")
                mapping_id = existing_mapping[0]
            else:
                self._connection.execute(
                    """INSERT INTO security_identifier_revision
                       (identifier_revision_id,security_id,identifier_type,identifier_value,effective_from,effective_to,
                        source_document_id,mapping_review_status,reviewed_by,reviewed_at,supersedes_identifier_revision_id,
                        parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                       VALUES (?,?, 'ISIN', ?,?,NULL,?,'pending',NULL,NULL,NULL,'admission-workflow-v1',?,?,NULL)""",
                    [mapping_id, security_id, isin, identity_observed_from, source_document_id, now, source_locator],
                )
        return {"issuer_entity_id": issuer_entity_id, "security_id": security_id,
                "listing_id": listing_id, "identifier_revision_id": mapping_id}

    def append_security_identifier_review(
        self,
        *,
        identifier_revision_id: str,
        review_status: str,
        reviewer: str | None,
        reviewer_actor_type: str | None,
        evidence_source_document_id: str,
        evidence_locator: str,
        rationale: str = "",
        supersedes_review_id: str | None = None,
    ) -> str:
        """Append a review decision for an ISIN identity candidate.

        The candidate row in security_identifier_revision is never modified.
        Each call inserts one row into security_identifier_revision_review and
        returns its review_id.

        reviewed_at and recorded_at are both set to datetime.now().astimezone()
        at write time.  recorded_at is the PIT visibility gate: a review row
        is not visible at any cutoff before recorded_at.

        supersedes_review_id must reference the existing active review for this
        candidate when re-reviewing.  Pass None only when no active review
        exists for the candidate yet.  The database enforces via composite FK
        that the referenced review belongs to the same candidate; the
        repository additionally validates that it has not already been
        superseded.
        """
        candidate = self._connection.execute(
            """SELECT security_id,identifier_type,identifier_value,effective_from,effective_to
               FROM security_identifier_revision WHERE identifier_revision_id=?""",
            [identifier_revision_id],
        ).fetchone()
        if candidate is None:
            raise RepositoryIntegrityError("identifier review references an unknown mapping revision")
        security_id, identifier_type, identifier_value, effective_from, effective_to = candidate
        if identifier_type != "ISIN":
            raise RepositoryIntegrityError("security admission review supports ISIN mappings only")
        if review_status not in ("pending", "approved", "rejected"):
            raise RepositoryIntegrityError("identifier review status must be pending, approved, or rejected")
        if review_status == "approved" and not str(evidence_locator or "").strip():
            raise RepositoryIntegrityError("identifier review requires a precise evidence locator")
        listing_exchange = self._connection.execute(
            "SELECT DISTINCT exchange FROM exchange_listing WHERE security_id=?", [security_id]
        ).fetchall()
        if len(listing_exchange) != 1:
            raise RepositoryIntegrityError("identifier review requires exactly one venue context")
        exchange = listing_exchange[0][0]
        self._require_source_for_exchange(evidence_source_document_id, exchange)
        reviewer = reviewer.strip() if reviewer else None
        if review_status in ("approved", "rejected") and not reviewer:
            raise RepositoryIntegrityError("approved/rejected identity review requires a named reviewer")
        if review_status in ("approved", "rejected") and reviewer_actor_type not in ("human", "system", "provider"):
            raise RepositoryIntegrityError("approved/rejected identity review requires actor type human, system, or provider")
        now = datetime.now().astimezone()

        # Validate supersession: the referenced prior review must exist,
        # belong to this candidate, and not already be superseded.
        if supersedes_review_id is not None:
            prior_review = self._connection.execute(
                """SELECT review_id FROM security_identifier_revision_review
                   WHERE review_id=? AND identifier_revision_id=?""",
                [supersedes_review_id, identifier_revision_id],
            ).fetchone()
            if prior_review is None:
                raise RepositoryIntegrityError(
                    "supersedes_review_id does not exist or belongs to a different candidate"
                )
            already_superseded = self._connection.execute(
                """SELECT 1 FROM security_identifier_revision_review
                   WHERE supersedes_review_id=?""",
                [supersedes_review_id],
            ).fetchone()
            if already_superseded:
                raise RepositoryIntegrityError(
                    "the referenced review has already been superseded; it cannot acquire a second successor"
                )
        else:
            # No supersession pointer supplied.  Reject if an active review
            # already exists: the caller must explicitly name what they supersede.
            active = self._connection.execute(
                """SELECT review_id FROM security_identifier_revision_review
                   WHERE identifier_revision_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM security_identifier_revision_review s
                       WHERE s.supersedes_review_id=security_identifier_revision_review.review_id
                     )""",
                [identifier_revision_id],
            ).fetchone()
            if active is not None:
                raise RepositoryIntegrityError(
                    "an active review already exists for this candidate; "
                    "provide supersedes_review_id to replace it"
                )

        # For approved: check for conflicting approved reviews on other
        # candidates covering the same ISIN interval.
        if review_status == "approved":
            if effective_from is None or (effective_to is not None and effective_from > effective_to):
                raise RepositoryIntegrityError("approved ISIN mapping requires a valid effective interval")
            conflicts = self._connection.execute(
                """SELECT r.review_id FROM security_identifier_revision_review r
                   JOIN security_identifier_revision i
                     ON i.identifier_revision_id = r.identifier_revision_id
                   WHERE i.identifier_type='ISIN' AND i.identifier_value=?
                     AND i.effective_from<=COALESCE(?,DATE '9999-12-31')
                     AND COALESCE(i.effective_to,DATE '9999-12-31')>=?
                     AND r.review_status='approved'
                     AND i.identifier_revision_id<>?
                     AND NOT EXISTS (
                       SELECT 1 FROM security_identifier_revision_review s
                       WHERE s.supersedes_review_id=r.review_id
                     )""",
                [identifier_value, effective_to, effective_from, identifier_revision_id],
            ).fetchall()
            if conflicts:
                raise RepositoryIntegrityError(
                    "approved ISIN mapping overlaps an existing approved mapping; no latest-row-wins"
                )

        review_id = self._admission_id(
            "idrev", identifier_revision_id, review_status, evidence_source_document_id, now.isoformat()
        )
        with self._transaction():
            self._connection.execute(
                """INSERT INTO security_identifier_revision_review
                   (review_id, identifier_revision_id, review_status, recorded_at,
                    reviewed_by, reviewer_actor_type, reviewed_at, evidence_source_document_id, evidence_locator,
                    rationale, supersedes_review_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    review_id,
                    identifier_revision_id,
                    review_status,
                    now,
                    reviewer if review_status != "pending" else None,
                    reviewer_actor_type if review_status != "pending" else None,
                    now if review_status != "pending" else None,
                    evidence_source_document_id if review_status != "pending" else None,
                    evidence_locator if review_status != "pending" else None,
                    rationale or None,
                    supersedes_review_id,
                ],
            )
        return review_id

    def append_exchange_listing_revision(self, revision: Mapping[str, object]) -> str:
        """Append a sourced listing/status interval without inferring snapshot dates."""
        required = ("listing_revision_id", "listing_id", "symbol", "status", "effective_from",
                    "source_document_id", "extraction_locator", "parser_version")
        missing = [key for key in required if key not in revision or revision[key] is None]
        if missing:
            raise RepositoryIntegrityError(f"listing revision missing fields: {', '.join(missing)}")
        listing = self._connection.execute(
            "SELECT exchange,exchange_instrument_id FROM exchange_listing WHERE listing_id=?", [revision["listing_id"]]
        ).fetchone()
        if listing is None:
            raise RepositoryIntegrityError("listing revision references an unknown listing")
        exchange, instrument_id = listing
        source = self._require_source_for_exchange(str(revision["source_document_id"]), exchange)
        if not str(revision["extraction_locator"]).strip() or not str(revision["parser_version"]).strip():
            raise RepositoryIntegrityError("listing revision requires parser and source locator")
        if str(revision.get("exchange_instrument_id", instrument_id)) != instrument_id:
            raise RepositoryIntegrityError("listing revision instrument identifier disagrees with listing identity")
        status = str(revision["status"])
        if status not in ("active", "suspended", "delisted", "relisted"):
            raise RepositoryIntegrityError("unsupported effective listing status")
        start, end = revision["effective_from"], revision.get("effective_to")
        if end is not None and start > end:
            raise RepositoryIntegrityError("listing revision effective interval is reversed")
        exact = self._connection.execute(
            """SELECT listing_revision_id,symbol,series,status,effective_from,effective_to,source_document_id,extraction_locator
               FROM exchange_listing_revision WHERE listing_id=? AND effective_from=?""", [revision["listing_id"], start]
        ).fetchone()
        content = (str(revision["symbol"]), revision.get("series"), status, start, end,
                   str(revision["source_document_id"]), str(revision["extraction_locator"]))
        if exact:
            if exact[1:] == content:
                return exact[0]
            raise RepositoryIntegrityError("conflicting listing revision already exists at this effective start")
        overlaps = self._connection.execute(
            """SELECT listing_revision_id FROM exchange_listing_revision WHERE listing_id=?
               AND effective_from<=COALESCE(?,DATE '9999-12-31')
               AND COALESCE(effective_to,DATE '9999-12-31')>=?""", [revision["listing_id"], end, start]
        ).fetchall()
        if overlaps:
            raise RepositoryIntegrityError("listing effective interval overlaps existing history; resolve rather than select latest")
        now = datetime.now().astimezone()
        with self._transaction():
            self._connection.execute(
                """INSERT INTO exchange_listing_revision
                   (listing_revision_id,listing_id,symbol,series,status,effective_from,effective_to,source_document_id,
                    supersedes_listing_revision_id,parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                   VALUES (?,?,?,?,?,?,?,?,NULL,?,?,?,NULL)""",
                [revision["listing_revision_id"], revision["listing_id"], revision["symbol"], revision.get("series"),
                 status, start, end, revision["source_document_id"], revision["parser_version"], now,
                 revision["extraction_locator"]],
            )
        return str(revision["listing_revision_id"])

    def _ensure_extraction_revision(self, observation: FinancialObservationRevision) -> str:
        existing = self._connection.execute(
            """SELECT processing_revision_id FROM source_document_processing_revision
               WHERE source_document_id=? AND parser_version=? AND status='succeeded'
               ORDER BY attempt_number DESC LIMIT 1""",
            [observation.source_document_id, observation.parser_version],
        ).fetchone()
        if existing:
            return existing[0]
        latest = self._connection.execute(
            """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
               WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""",
            [observation.source_document_id],
        ).fetchone()
        revision_id = "proc-" + sha256(
            f"{observation.source_document_id}|{observation.parser_version}|{observation.extraction_timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:32]
        self._connection.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,completed_at,
                replay_timestamp,status,accepted_count,rejected_count,quarantined_count,error_summary,supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,?,?,'succeeded',1,0,0,NULL,?)""",
            [revision_id, observation.source_document_id, observation.parser_version,
             latest[1] + 1 if latest else 1, observation.extraction_timestamp,
             observation.extraction_timestamp, observation.replay_timestamp, latest[0] if latest else None],
        )
        return revision_id

    def append_eod_price_observation(self, observation: Mapping[str, object]) -> str:
        """Append one venue-specific EOD observation with source registry lineage.

        This method intentionally has no update/delete counterpart. Provider
        ingestion must resolve identity and classification before calling it.
        """
        required = (
            "observation_id", "security_id", "listing_id", "exchange", "trade_date",
            "open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "turnover_raw",
            "source_document_id", "source_identifier", "checksum_sha256", "parser_version",
            "extraction_timestamp", "extraction_locator", "quality_status", "extraction_revision_id",
        )
        missing = [field for field in required if field not in observation]
        if missing:
            raise RepositoryIntegrityError(f"EOD observation missing fields: {', '.join(missing)}")
        if observation["exchange"] not in ("NSE", "BSE"):
            raise RepositoryIntegrityError("EOD observation exchange must be NSE or BSE")
        self._aware(observation["extraction_timestamp"], "EOD extraction_timestamp")
        if observation["quality_status"] not in ("observed", "missing", "invalid", "conflicted", "stale", "not_applicable"):
            raise RepositoryIntegrityError("unsupported EOD quality_status")
        listing = self._connection.execute(
            "SELECT security_id,exchange FROM exchange_listing WHERE listing_id=?",
            [observation["listing_id"]],
        ).fetchone()
        if listing != (observation["security_id"], observation["exchange"]):
            raise RepositoryIntegrityError("EOD security/listing/exchange mapping disagrees")
        source = self._connection.execute(
            """SELECT provider,dataset,source_identifier,checksum_sha256,CAST(ingestion_timestamp AS VARCHAR)
               FROM source_document_revision WHERE source_document_id=?""",
            [observation["source_document_id"]],
        ).fetchone()
        if source is None:
            raise RepositoryIntegrityError("EOD observation references an unknown source document")
        if source[2] != observation["source_identifier"] or source[3] != observation["checksum_sha256"]:
            raise RepositoryIntegrityError("EOD observation provenance differs from source document")
        if observation["extraction_timestamp"].timestamp() < datetime.fromisoformat(
            source[4].replace(" ", "T", 1)
        ).timestamp():
            raise RepositoryIntegrityError("EOD extraction precedes source-document ingestion")
        processing = self._connection.execute(
            """SELECT source_document_id,parser_version,status FROM source_document_processing_revision
               WHERE processing_revision_id=?""", [observation["extraction_revision_id"]]
        ).fetchone()
        if processing is None or processing[0] != observation["source_document_id"] or processing[1] != observation["parser_version"] or processing[2] not in ("started", "succeeded"):
            raise RepositoryIntegrityError("EOD observation references an invalid extraction revision")
        if self._connection.execute(
            "SELECT 1 FROM normalized_observation_registry WHERE observation_id=?", [observation["observation_id"]]
        ).fetchone():
            raise RepositoryIntegrityError("EOD observation ID already exists")

        parent_id = observation.get("supersedes_observation_id")
        if parent_id:
            parent = self._connection.execute(
                """SELECT p.security_id,p.listing_id,p.exchange,p.trade_date,p.source_document_id,
                          d.provider,d.dataset
                   FROM eod_price_observation_revision p
                   JOIN source_document_revision d USING(source_document_id)
                   WHERE p.observation_id=?""", [parent_id]
            ).fetchone()
            if parent is None or parent[:4] != (
                observation["security_id"], observation["listing_id"], observation["exchange"], observation["trade_date"]
            ) or parent[5:7] != source[:2]:
                raise RepositoryIntegrityError("EOD revision must supersede the same provider/listing/session natural key")
            if self._connection.execute(
                "SELECT 1 FROM eod_price_observation_revision WHERE supersedes_observation_id=?", [parent_id]
            ).fetchone():
                raise RepositoryIntegrityError("EOD observation revision already has a successor")
        elif self._connection.execute(
            """SELECT 1 FROM eod_price_observation_revision p
               JOIN source_document_revision d USING(source_document_id)
               WHERE p.listing_id=? AND p.trade_date=? AND d.provider=? AND d.dataset=?
                 AND NOT EXISTS (SELECT 1 FROM eod_price_observation_revision c WHERE c.supersedes_observation_id=p.observation_id)
               LIMIT 1""",
            [observation["listing_id"], observation["trade_date"], source[0], source[1]],
        ).fetchone():
            raise RepositoryIntegrityError("a prior EOD source observation exists; append a linked revision")

        values = [observation[name] for name in ("open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "turnover_raw")]
        for name, value in zip(("open", "high", "low", "close", "volume", "turnover"), values):
            if value is not None:
                try:
                    number = Decimal(str(value))
                except InvalidOperation as exc:
                    raise RepositoryIntegrityError(f"invalid EOD {name} value") from exc
                if not number.is_finite():
                    raise RepositoryIntegrityError(f"non-finite EOD {name} value")
                if name in ("volume", "turnover") and number < 0:
                    raise RepositoryIntegrityError(f"negative EOD {name} value")
        high, low = observation["high_raw"], observation["low_raw"]
        if high is not None and low is not None and Decimal(str(high)) < Decimal(str(low)):
            raise RepositoryIntegrityError("EOD high is below low")
        if observation["quality_status"] == "observed" and observation["close_raw"] is None:
            raise RepositoryIntegrityError("observed EOD row requires close")

        with self._transaction():
            self._connection.execute(
                """INSERT INTO normalized_observation_registry
                   (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                    parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                   VALUES (?,'eod_price',?,?,?,?,?,?,?)""",
                [observation["observation_id"], observation["source_document_id"], observation["source_identifier"],
                 observation["checksum_sha256"], observation["parser_version"], observation["extraction_timestamp"],
                 observation["extraction_locator"], observation["extraction_revision_id"]],
            )
            self._connection.execute(
                """INSERT INTO eod_price_observation_revision
                   (observation_id,observation_type,security_id,listing_id,exchange,trade_date,
                    open_raw,high_raw,low_raw,close_raw,price_unit,volume_raw,volume_unit,turnover_raw,turnover_unit,
                    source_document_id,source_identifier,checksum_sha256,parser_version,extraction_timestamp,
                    extraction_locator,quality_status,quality_reason,supersedes_observation_id)
                   VALUES (?,'eod_price',?,?,?,?,?,?,?,?,'INR_PER_SHARE',?,'SHARES',?,'INR',?,?,?,?,?,?,?,?,?)""",
                [observation["observation_id"], observation["security_id"], observation["listing_id"], observation["exchange"],
                 observation["trade_date"], observation["open_raw"], observation["high_raw"], observation["low_raw"],
                 observation["close_raw"], observation["volume_raw"], observation["turnover_raw"],
                 observation["source_document_id"], observation["source_identifier"], observation["checksum_sha256"],
                 observation["parser_version"], observation["extraction_timestamp"], observation["extraction_locator"],
                 observation["quality_status"], observation.get("quality_reason"), parent_id],
            )
        return str(observation["observation_id"])

    def eod_observations_as_of(
        self,
        *,
        exchange: str,
        trade_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
        parser_version: str | None = None,
        listing_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Select EOD revisions known/public by a session cutoff.

        `public_as_of` may use a later local extraction of a source that was
        already public. `hamsa_known_as_of` also requires source ingestion and
        extraction by the cutoff. An optional parser pin supports reproducible
        extraction-version snapshots.
        """
        self._aware(cutoff, "cutoff")
        if exchange not in ("NSE", "BSE") or availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("invalid exchange or EOD availability mode")
        if not calendar_version:
            raise RepositoryIntegrityError("calendar_version is required for EOD point-in-time selection")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
        if local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("EOD observation selection requires the 15:30 Asia/Kolkata cutoff")
        screen_date = local_cutoff.date()
        if screen_date < trade_date:
            return []
        is_session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s
               LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
            [exchange, screen_date, calendar_version],
        ).fetchone()
        if is_session is None or not is_session[0]:
            return []
        if not is_session[1] or is_session[2] is None or not str(is_session[2]).upper().startswith(exchange):
            return []
        source_cache: dict[str, bool] = {}
        def check_source(doc_id: str) -> bool:
            if doc_id not in source_cache:
                source_cache[doc_id] = self._source_available(
                    doc_id, exchange=exchange, screen_date=screen_date, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version,
                )
            return source_cache[doc_id]
        if not check_source(is_session[1]):
            return []
        query = """SELECT o.observation_id,o.listing_id,o.security_id,o.trade_date,o.open_raw,o.high_raw,
                          o.low_raw,o.close_raw,o.volume_raw,o.turnover_raw,o.parser_version,
                          o.supersedes_observation_id,o.source_document_id,
                          CAST(o.extraction_timestamp AS VARCHAR),d.publication_date,
                          CAST(d.published_at AS VARCHAR),CAST(d.ingestion_timestamp AS VARCHAR)
                   FROM eod_price_observation_revision o
                   JOIN source_document_revision d USING(source_document_id)
                   WHERE o.exchange=? AND o.trade_date=?"""
        params: list[object] = [exchange, trade_date]
        if listing_id is not None:
            query += " AND o.listing_id=?"
            params.append(listing_id)
        if parser_version is not None:
            query += " AND o.parser_version=?"
            params.append(parser_version)
        rows = self._connection.execute(query, params).fetchall()
        visible: dict[str, tuple] = {}
        for row in rows:
            if not check_source(row[12]):
                continue
            if availability_mode == "hamsa_known_as_of":
                extracted = datetime.fromisoformat(str(row[13]).replace(" ", "T", 1))
                if extracted > cutoff:
                    continue
            visible[row[0]] = row
        leaves = []
        for observation_id, row in visible.items():
            if not any(candidate[11] == observation_id for candidate in visible.values()):
                leaves.append({
                    "observation_id": observation_id, "listing_id": row[1], "security_id": row[2],
                    "trade_date": row[3], "open": row[4], "high": row[5], "low": row[6],
                    "close": row[7], "volume": row[8], "turnover": row[9],
                    "parser_version": row[10], "source_document_id": row[12],
                })
        return sorted(leaves, key=lambda item: (str(item["listing_id"]), str(item["observation_id"])))

    def financial_observations_as_of(
        self,
        *,
        exchange: str,
        session_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
        parser_version: str | None = None,
        subject_entity_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Return PIT-eligible financial revision leaves for one exchange session.

        Conflicting unsuperseded observations for a natural key are retained
        with ``quality_status='conflicted'``; callers must not choose one.
        """
        self._aware(cutoff, "cutoff")
        if exchange not in ("NSE", "BSE") or availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("invalid exchange or financial availability mode")
        if not calendar_version:
            raise RepositoryIntegrityError("calendar_version is required for financial point-in-time selection")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
        if local_cutoff.date() != session_date or local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("financial screen requires the 15:30 Asia/Kolkata session cutoff")
        session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
            [exchange, session_date, calendar_version],
        ).fetchone()
        if session is None or not session[0] or not session[1] or session[2] is None \
                or not str(session[2]).upper().startswith(exchange):
            raise RepositoryIntegrityError("selected exchange calendar lacks a sourced trading session")
        source_cache: dict[str, bool] = {}
        def check_source(doc_id: str) -> bool:
            if doc_id not in source_cache:
                source_cache[doc_id] = self._source_available(
                    doc_id, exchange=exchange, screen_date=session_date, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version,
                )
            return source_cache[doc_id]
        if not check_source(session[1]):
            raise RepositoryIntegrityError("selected exchange calendar source was not available at cutoff")
        query = """SELECT f.observation_id,f.subject_entity_id,f.metric,f.canonical_value,f.canonical_unit,
                          f.period_start,f.period_end,f.reporting_scope,f.quality_status,f.source_document_id,
                          f.supersedes_observation_id,f.parser_version,f.extraction_locator,
                          CAST(f.extraction_timestamp AS VARCHAR)
                   FROM financial_observation_revision f"""
        conditions: list[str] = []
        params: list[object] = []
        if subject_entity_id is not None:
            conditions.append("f.subject_entity_id=?")
            params.append(subject_entity_id)
        if parser_version:
            conditions.append("f.parser_version=?")
            params.append(parser_version)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        rows = self._connection.execute(query, params).fetchall()
        eligible: dict[str, tuple] = {}
        for row in rows:
            if not check_source(row[9]):
                continue
            if availability_mode == "hamsa_known_as_of":
                extracted = datetime.fromisoformat(str(row[13]).replace(" ", "T", 1))
                if extracted > cutoff:
                    continue
            eligible[row[0]] = row
        grouped: dict[tuple[object, ...], list[tuple]] = {}
        for row in eligible.values():
            grouped.setdefault((row[1], row[2], row[5], row[6], row[7]), []).append(row)
        result: list[dict[str, object]] = []
        for natural_key, revisions in grouped.items():
            superseded = {row[10] for row in revisions if row[10]}
            leaves = [row for row in revisions if row[0] not in superseded]
            observed_values = {(row[3], row[4]) for row in leaves if row[8] == "observed"}
            conflict = len(observed_values) > 1
            for row in leaves:
                result.append({
                    "observation_id": row[0], "subject_entity_id": row[1], "metric": row[2],
                    "value": row[3], "unit": row[4], "period_start": row[5], "period_end": row[6],
                    "reporting_scope": row[7], "quality_status": "conflicted" if conflict and row[8] == "observed" else row[8],
                    "source_document_id": row[9], "parser_version": row[11],
                    "extraction_locator": row[12], "natural_key": natural_key,
                })
        return sorted(result, key=lambda item: (str(item["subject_entity_id"]), str(item["metric"]),
            item["period_end"], str(item["observation_id"])))

    def delivery_observations_as_of(
        self,
        *,
        exchange: str,
        trade_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
        parser_version: str | None = None,
        listing_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Select venue-specific delivery revisions known/public by a session cutoff."""
        self._aware(cutoff, "cutoff")
        if exchange not in ("NSE", "BSE") or availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("invalid exchange or delivery availability mode")
        if not calendar_version:
            raise RepositoryIntegrityError("calendar_version is required for delivery point-in-time selection")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
        if local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("delivery observation selection requires the 15:30 Asia/Kolkata cutoff")
        screen_date = local_cutoff.date()
        if screen_date < trade_date:
            return []
        is_session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s
               LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
            [exchange, screen_date, calendar_version],
        ).fetchone()
        if is_session is None or not is_session[0] or not is_session[1] or is_session[2] is None \
                or not str(is_session[2]).upper().startswith(exchange):
            return []
        source_cache: dict[str, bool] = {}
        def check_source(doc_id: str) -> bool:
            if doc_id not in source_cache:
                source_cache[doc_id] = self._source_available(
                    doc_id, exchange=exchange, screen_date=screen_date, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version,
                )
            return source_cache[doc_id]
        if not check_source(is_session[1]):
            return []
        query = """SELECT o.observation_id,o.listing_id,o.security_id,o.exchange,o.trade_date,
                          o.delivery_quantity_raw,o.traded_quantity_raw,o.delivery_percentage_raw,
                          o.quality_status,o.parser_version,o.supersedes_observation_id,
                          o.source_document_id,o.extraction_locator,
                          CAST(o.extraction_timestamp AS VARCHAR)
                   FROM delivery_observation_revision o
                   JOIN source_document_revision d USING(source_document_id)
                   WHERE o.exchange=? AND o.trade_date=?"""
        params: list[object] = [exchange, trade_date]
        if listing_id is not None:
            query += " AND o.listing_id=?"
            params.append(listing_id)
        if parser_version is not None:
            query += " AND o.parser_version=?"
            params.append(parser_version)
        rows = self._connection.execute(query, params).fetchall()
        visible: dict[str, tuple] = {}
        for row in rows:
            if not check_source(row[11]):
                continue
            if availability_mode == "hamsa_known_as_of":
                extracted = datetime.fromisoformat(str(row[13]).replace(" ", "T", 1))
                if extracted > cutoff:
                    continue
            visible[row[0]] = row
        leaves = []
        for observation_id, row in visible.items():
            if not any(candidate[10] == observation_id for candidate in visible.values()):
                leaves.append({
                    "observation_id": observation_id, "listing_id": row[1], "security_id": row[2],
                    "exchange": row[3], "trade_date": row[4], "delivery_quantity": row[5],
                    "traded_quantity": row[6], "delivery_percentage": row[7],
                    "quality_status": row[8], "parser_version": row[9],
                    "source_document_id": row[11], "extraction_locator": row[12],
                })
        return sorted(leaves, key=lambda item: (str(item["listing_id"]), str(item["observation_id"])))

    def corporate_action_events_as_of(
        self,
        *,
        exchange: str,
        session_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
        issuer_entity_id: str | None = None,
        security_id: str | None = None,
    ) -> list[dict[str, object]]:
        """Select point-in-time unsuperseded corporate-action event revisions."""
        self._aware(cutoff, "cutoff")
        if exchange not in ("NSE", "BSE") or availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("invalid exchange or corporate-action availability mode")
        if not calendar_version:
            raise RepositoryIntegrityError("calendar_version is required for corporate-action point-in-time selection")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
        if local_cutoff.date() != session_date or local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("corporate-action selection requires the 15:30 Asia/Kolkata session cutoff")
        is_session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s
               LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
            [exchange, session_date, calendar_version],
        ).fetchone()
        if is_session is None or not is_session[0] or not is_session[1] or is_session[2] is None \
                or not str(is_session[2]).upper().startswith(exchange):
            return []
        if not self._source_available(
            is_session[1], exchange=exchange, screen_date=session_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
        ):
            return []
        query = """SELECT a.event_revision_id,a.event_id,a.revision_number,a.action_type,
                          a.affected_security_id,a.resulting_security_id,a.publication_date,
                          CAST(a.published_at AS VARCHAR),a.source_document_date,a.ex_date,
                          a.record_date,a.effective_date,a.terms_complete,CAST(a.terms_json AS VARCHAR),
                          a.source_document_id,d.source_identifier,d.checksum_sha256,
                          a.supersedes_event_revision_id,CAST(r.extraction_timestamp AS VARCHAR)
                   FROM corporate_action_event_revision a
                   JOIN source_document_revision d USING(source_document_id)
                   LEFT JOIN normalized_observation_registry r ON r.observation_id=a.event_revision_id"""
        conditions: list[str] = []
        params: list[object] = []
        if issuer_entity_id is not None:
            conditions.append("a.affected_security_id IN (SELECT security_id FROM equity_security WHERE issuer_entity_id=?)")
            params.append(issuer_entity_id)
        if security_id is not None:
            conditions.append("a.affected_security_id=?")
            params.append(security_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY coalesce(a.effective_date,a.publication_date),a.event_id,a.revision_number"
        rows = self._connection.execute(query, params).fetchall()
        visible: dict[str, tuple] = {}
        for row in rows:
            if not self._source_available(
                row[14], exchange=exchange, screen_date=session_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            ):
                continue
            if availability_mode == "hamsa_known_as_of" and row[18] is not None:
                extracted = datetime.fromisoformat(str(row[18]).replace(" ", "T", 1))
                if extracted > cutoff:
                    continue
            visible[row[0]] = row
        leaves = []
        for event_revision_id, row in visible.items():
            if not any(candidate[17] == event_revision_id for candidate in visible.values()):
                leaves.append({
                    "event_revision_id": event_revision_id, "event_id": row[1],
                    "revision_number": row[2], "action_type": row[3],
                    "affected_security_id": row[4], "resulting_security_id": row[5],
                    "publication_date": row[6], "published_at": row[7],
                    "source_document_date": row[8], "ex_date": row[9],
                    "record_date": row[10], "effective_date": row[11],
                    "terms_complete": row[12], "terms_json": row[13],
                    "source_document_id": row[14], "source_identifier": row[15],
                    "checksum_sha256": row[16], "supersedes_event_revision_id": row[17],
                })
        return leaves

    @staticmethod
    def _aware(value: datetime, label: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise RepositoryIntegrityError(f"{label} must be timezone-aware")
        return value

    @staticmethod
    def _json_text(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _ensure_extraction_revision_for_source(
        self, source_document_id: str, parser_version: str, extraction_timestamp: datetime
    ) -> str:
        existing = self._connection.execute(
            """SELECT processing_revision_id FROM source_document_processing_revision
               WHERE source_document_id=? AND parser_version=? AND status='succeeded'
               ORDER BY attempt_number DESC LIMIT 1""",
            [source_document_id, parser_version],
        ).fetchone()
        if existing:
            return existing[0]
        latest = self._connection.execute(
            """SELECT processing_revision_id,attempt_number FROM source_document_processing_revision
               WHERE source_document_id=? ORDER BY attempt_number DESC LIMIT 1""",
            [source_document_id],
        ).fetchone()
        revision_id = "proc-" + sha256(
            f"{source_document_id}|{parser_version}|{extraction_timestamp.isoformat()}".encode("utf-8")
        ).hexdigest()[:32]
        self._connection.execute(
            """INSERT INTO source_document_processing_revision
               (processing_revision_id,source_document_id,parser_version,attempt_number,started_at,completed_at,
                status,accepted_count,rejected_count,quarantined_count,supersedes_processing_revision_id)
               VALUES (?,?,?,?,?,?,'succeeded',1,0,0,?)""",
            [revision_id, source_document_id, parser_version,
             latest[1] + 1 if latest else 1, extraction_timestamp, extraction_timestamp,
             latest[0] if latest else None],
        )
        return revision_id

    def append_listing_classification_snapshot(self, snapshot: Mapping[str, object]) -> str:
        """Append one raw classification snapshot with typed registry provenance."""
        required = (
            "listing_classification_snapshot_id", "listing_id", "exchange", "source_document_id",
            "source_snapshot_date", "parser_version", "extraction_locator",
        )
        missing = [name for name in required if name not in snapshot]
        if missing:
            raise RepositoryIntegrityError(f"classification snapshot missing fields: {', '.join(missing)}")
        allowed = set(required) | {
            "raw_exchange_instrument_id", "raw_isin", "raw_symbol", "raw_series", "raw_listing_status",
            "raw_instrument_class_value", "raw_platform_class_value", "source_fields_json", "supersedes_snapshot_id",
        }
        unexpected = set(snapshot) - allowed
        if unexpected:
            raise RepositoryIntegrityError(f"unsupported classification snapshot fields: {', '.join(sorted(unexpected))}")
        sid = str(snapshot["listing_classification_snapshot_id"])
        listing_id = str(snapshot["listing_id"])
        exchange = str(snapshot["exchange"])
        extraction_at = datetime.now().astimezone()
        locator = str(snapshot["extraction_locator"])
        if not locator:
            raise RepositoryIntegrityError("classification snapshot extraction_locator cannot be empty")
        listing = self._connection.execute(
            "SELECT security_id,exchange,exchange_instrument_id FROM exchange_listing WHERE listing_id=?",
            [listing_id],
        ).fetchone()
        if listing is None:
            raise RepositoryIntegrityError("classification snapshot references an unknown listing")
        if listing[1] != exchange:
            raise RepositoryIntegrityError("classification snapshot exchange disagrees with exchange_listing")
        raw_instrument_id = snapshot.get("raw_exchange_instrument_id")
        if raw_instrument_id is not None and str(raw_instrument_id) != listing[2]:
            raise RepositoryIntegrityError("snapshot instrument identifier disagrees with exchange_listing")

        raw_isin = snapshot.get("raw_isin")
        if raw_isin is not None:
            mapped = self._connection.execute(
                """SELECT i.security_id FROM security_identifier_revision i
                   LEFT JOIN security_identifier_revision_review r
                     ON r.identifier_revision_id=i.identifier_revision_id
                    AND NOT EXISTS (
                      SELECT 1 FROM security_identifier_revision_review s
                      WHERE s.supersedes_review_id=r.review_id
                    )
                   WHERE i.identifier_type='ISIN' AND i.identifier_value=?
                     AND r.review_status='approved'
                     AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
                [str(raw_isin).strip().upper(), snapshot["source_snapshot_date"], snapshot["source_snapshot_date"]],
            ).fetchall()
            if len(mapped) != 1 or mapped[0][0] != listing[0]:
                raise RepositoryIntegrityError("snapshot ISIN has missing, conflicting, or mismatched approved identity mapping")

        source = self._connection.execute(
            """SELECT source_identifier,checksum_sha256,provider,CAST(ingestion_timestamp AS VARCHAR)
               FROM source_document_revision WHERE source_document_id=?""",
            [snapshot["source_document_id"]],
        ).fetchone()
        if source is None:
            raise RepositoryIntegrityError("classification snapshot references an unknown source document")
        if not str(source[2]).upper().startswith(exchange):
            raise RepositoryIntegrityError("classification snapshot source provider does not match its exchange")
        source_ingestion = datetime.fromisoformat(str(source[3]).replace(" ", "T", 1))
        if source_ingestion > extraction_at:
            raise RepositoryIntegrityError("classification snapshot extraction precedes source-document ingestion")
        if self._connection.execute(
            "SELECT 1 FROM normalized_observation_registry WHERE observation_id=?", [sid]
        ).fetchone():
            raise RepositoryIntegrityError("classification snapshot observation ID already exists")
        supersedes_id = snapshot.get("supersedes_snapshot_id")
        if supersedes_id:
            prior = self._connection.execute(
                "SELECT listing_id FROM listing_classification_snapshot WHERE listing_classification_snapshot_id=?",
                [supersedes_id],
            ).fetchone()
            if prior is None or prior[0] != listing_id:
                raise RepositoryIntegrityError("classification snapshot may only supersede a snapshot for the same listing")
            if self._connection.execute(
                "SELECT 1 FROM listing_classification_snapshot WHERE supersedes_snapshot_id=?", [supersedes_id]
            ).fetchone():
                raise RepositoryIntegrityError("classification snapshot supersession chain already has a successor")

        source_fields = snapshot.get("source_fields_json", {})
        if isinstance(source_fields, str):
            try:
                json.loads(source_fields)
            except json.JSONDecodeError as exc:
                raise RepositoryIntegrityError("source_fields_json is not valid JSON") from exc
            source_fields_json = source_fields
        else:
            source_fields_json = self._json_text(source_fields)

        with self._transaction():
            extraction_revision_id = self._ensure_extraction_revision_for_source(
                str(snapshot["source_document_id"]), str(snapshot["parser_version"]), extraction_at
            )
            self._connection.execute(
                """INSERT INTO normalized_observation_registry
                   (observation_id,observation_type,source_document_id,source_identifier,checksum_sha256,
                    parser_version,extraction_timestamp,extraction_locator,extraction_revision_id)
                   VALUES (?,'classification',?,?,?,?,?,?,?)""",
                 [sid, snapshot["source_document_id"], source[0], source[1], snapshot["parser_version"],
                 extraction_at, locator, extraction_revision_id],
            )
            self._connection.execute(
                """INSERT INTO listing_classification_snapshot
                   (listing_classification_snapshot_id,observation_type,listing_id,exchange,source_document_id,
                    source_snapshot_date,raw_exchange_instrument_id,raw_isin,raw_symbol,raw_series,raw_listing_status,
                    raw_instrument_class_value,raw_platform_class_value,source_fields_json,parser_version,
                    extraction_timestamp,extraction_locator,supersedes_snapshot_id)
                   VALUES (?,'classification',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [sid, listing_id, exchange, snapshot["source_document_id"], snapshot["source_snapshot_date"],
                 raw_instrument_id, raw_isin, snapshot.get("raw_symbol"), snapshot.get("raw_series"),
                 snapshot.get("raw_listing_status"), snapshot.get("raw_instrument_class_value"),
                 snapshot.get("raw_platform_class_value"), source_fields_json, snapshot["parser_version"],
                 extraction_at, locator, supersedes_id],
            )
        return sid

    def _validate_review_supersession(
        self, table: str, id_column: str, supersedes_id: str | None, target_column: str, target_id: str
    ) -> None:
        if not supersedes_id:
            return
        parent = self._connection.execute(
            f"SELECT {target_column} FROM {table} WHERE {id_column}=?", [supersedes_id]
        ).fetchone()
        if parent is None or parent[0] != target_id:
            raise RepositoryIntegrityError("review supersession must target an event for the same subject")
        if self._connection.execute(
            f"SELECT 1 FROM {table} WHERE supersedes_review_revision_id=?" if table == "listing_classification_review_revision"
            else f"SELECT 1 FROM {table} WHERE supersedes_review_id=?",
            [supersedes_id],
        ).fetchone():
            raise RepositoryIntegrityError("review chain already has a successor")

    def append_listing_classification_review_revision(self, review: Mapping[str, object]) -> str:
        """Append independent instrument/platform decisions; intervals are never updated in place."""
        required = ("classification_review_revision_id", "listing_classification_snapshot_id", "listing_id", "rationale")
        missing = [name for name in required if name not in review]
        if missing:
            raise RepositoryIntegrityError(f"classification review missing fields: {', '.join(missing)}")
        review_id = str(review["classification_review_revision_id"])
        snapshot_id = str(review["listing_classification_snapshot_id"])
        listing_id = str(review["listing_id"])
        if self._connection.execute(
            "SELECT 1 FROM listing_classification_snapshot WHERE listing_classification_snapshot_id=? AND listing_id=?",
            [snapshot_id, listing_id],
        ).fetchone() is None:
            raise RepositoryIntegrityError("classification review target snapshot/listing mismatch")
        supersedes_id = review.get("supersedes_review_revision_id")
        self._validate_review_supersession(
            "listing_classification_review_revision", "classification_review_revision_id",
            str(supersedes_id) if supersedes_id else None, "listing_classification_snapshot_id", snapshot_id,
        )
        if supersedes_id:
            parent_listing = self._connection.execute(
                "SELECT listing_id FROM listing_classification_review_revision WHERE classification_review_revision_id=?",
                [supersedes_id],
            ).fetchone()
            if parent_listing is None or parent_listing[0] != listing_id:
                raise RepositoryIntegrityError("classification review supersession changed listing target")
        else:
            active = self._connection.execute(
                """SELECT classification_review_revision_id FROM listing_classification_review_revision r
                   WHERE r.listing_classification_snapshot_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM listing_classification_review_revision n
                       WHERE n.supersedes_review_revision_id=r.classification_review_revision_id
                     )""",
                [snapshot_id],
            ).fetchone()
            if active is not None:
                raise RepositoryIntegrityError(
                    "an active classification review already exists for this snapshot; "
                    "provide supersedes_review_revision_id to replace it"
                )

        now = datetime.now().astimezone()
        values: list[object] = [review_id, snapshot_id, listing_id, "hamsa-storage", now, review["rationale"]]
        for dimension in ("instrument", "platform"):
            status = str(review.get(f"{dimension}_review_status", "pending"))
            klass = review.get(f"{dimension}_class")
            valid_from = review.get(f"{dimension}_valid_from")
            valid_to = review.get(f"{dimension}_valid_to")
            evidence_id = review.get(f"{dimension}_evidence_source_document_id")
            evidence_locator = review.get(f"{dimension}_evidence_locator")
            reviewer = review.get(f"{dimension}_reviewed_by")
            if status == "approved":
                if not reviewer or not str(reviewer).strip() or not evidence_id or not str(evidence_locator).strip():
                    raise RepositoryIntegrityError(f"approved {dimension} classification requires reviewer and evidence locator")
                self._require_exchange_evidence(listing_id, str(evidence_id))
                if valid_from is None or (valid_to is not None and valid_from > valid_to):
                    raise RepositoryIntegrityError(f"approved {dimension} classification requires a valid applicability interval")
                reviewed_at = now
            elif status == "pending":
                reviewer = reviewed_at = None
                valid_from = valid_to = evidence_id = evidence_locator = None
            elif status == "rejected":
                if not reviewer:
                    raise RepositoryIntegrityError(f"rejected {dimension} classification requires a reviewer")
                reviewed_at = now
                valid_from = valid_to = None
            else:
                raise RepositoryIntegrityError(f"unsupported {dimension} review status: {status}")
            values.extend([status, klass, valid_from, valid_to, evidence_id, evidence_locator, reviewer, reviewed_at])
        values.append(supersedes_id)
        with self._transaction():
            placeholders = ",".join("?" for _ in values)
            self._connection.execute(
                f"INSERT INTO listing_classification_review_revision VALUES ({placeholders})",
                values,
            )
        return review_id

    def _require_exchange_evidence(self, listing_id: str, source_document_id: str) -> None:
        listing = self._connection.execute("SELECT exchange FROM exchange_listing WHERE listing_id=?", [listing_id]).fetchone()
        document = self._connection.execute(
            "SELECT provider,CAST(ingestion_timestamp AS VARCHAR) FROM source_document_revision WHERE source_document_id=?",
            [source_document_id],
        ).fetchone()
        if listing is None or document is None:
            raise RepositoryIntegrityError("review evidence or listing does not exist")
        if not str(document[0]).upper().startswith(listing[0]):
            raise RepositoryIntegrityError("review evidence provider does not match the listing exchange")
        ingested_at = datetime.fromisoformat(str(document[1]).replace(" ", "T", 1))
        if ingested_at > datetime.now().astimezone():
            raise RepositoryIntegrityError("review evidence has not yet been ingested by HAMSA")

    def append_exchange_listing_revision_review(self, review: Mapping[str, object]) -> str:
        """Append a review of one exact effective listing revision."""
        required = ("listing_revision_review_id", "listing_revision_id", "review_status", "rationale")
        missing = [name for name in required if name not in review]
        if missing:
            raise RepositoryIntegrityError(f"listing revision review missing fields: {', '.join(missing)}")
        review_id = str(review["listing_revision_review_id"])
        revision_id = str(review["listing_revision_id"])
        revision = self._connection.execute(
            """SELECT l.listing_id,l.symbol,l.series,l.status,l.effective_from,l.effective_to
               FROM exchange_listing_revision l WHERE l.listing_revision_id=?""", [revision_id]
        ).fetchone()
        if revision is None:
            raise RepositoryIntegrityError("listing review references an unknown listing revision")
        status = str(review["review_status"])
        now = datetime.now().astimezone()
        evidence_id = review.get("evidence_source_document_id")
        locator = review.get("evidence_locator")
        reviewer = review.get("reviewed_by")
        if status == "approved":
            if not evidence_id or not locator or not str(locator).strip() or not reviewer or not str(reviewer).strip():
                raise RepositoryIntegrityError("approved listing revision review requires reviewer and evidence locator")
            self._require_exchange_evidence(revision[0], str(evidence_id))
        elif status == "pending":
            evidence_id = locator = reviewer = None
        elif status == "rejected":
            if not reviewer:
                raise RepositoryIntegrityError("rejected listing revision review requires a reviewer")
        else:
            raise RepositoryIntegrityError(f"unsupported listing revision review status: {status}")
        supersedes_id = review.get("supersedes_review_id")
        if supersedes_id:
            parent = self._connection.execute(
                "SELECT listing_revision_id FROM exchange_listing_revision_review WHERE listing_revision_review_id=?",
                [supersedes_id],
            ).fetchone()
            if parent is None or parent[0] != revision_id:
                raise RepositoryIntegrityError("listing review supersession must target the same listing revision")
            if self._connection.execute(
                "SELECT 1 FROM exchange_listing_revision_review WHERE supersedes_review_id=?", [supersedes_id]
            ).fetchone():
                raise RepositoryIntegrityError("listing revision review chain already has a successor")
        else:
            active = self._connection.execute(
                """SELECT listing_revision_review_id FROM exchange_listing_revision_review r
                   WHERE r.listing_revision_id=?
                     AND NOT EXISTS (
                       SELECT 1 FROM exchange_listing_revision_review n
                       WHERE n.supersedes_review_id=r.listing_revision_review_id
                     )""",
                [revision_id],
            ).fetchone()
            if active is not None:
                raise RepositoryIntegrityError(
                    "an active listing review already exists for this revision; "
                    "provide supersedes_review_id to replace it"
                )
        with self._transaction():
            self._connection.execute(
                """INSERT INTO exchange_listing_revision_review
                   (listing_revision_review_id,listing_revision_id,review_status,recorded_by,recorded_at,
                    reviewed_by,reviewed_at,evidence_source_document_id,evidence_locator,rationale,supersedes_review_id)
                   VALUES (?,?,?,'hamsa-storage',?,?,?,?,?,?,?)""",
                [review_id, revision_id, status, now, reviewer, now if reviewer else None,
                 evidence_id, locator, review["rationale"], supersedes_id],
            )
        return review_id

    def append_eod_observation_reconciliation(
        self,
        *,
        reconciliation_id: str,
        comparison_stream_id: str,
        comparator_version: str,
        match_status: str,
        official_observation_id: str | None = None,
        secondary_observation_id: str | None = None,
        not_compared_reason_code: str | None = None,
        supersedes_reconciliation_id: str | None = None,
    ) -> tuple[str, str]:
        """Append a source comparison, computing payloads from immutable source rows."""
        if comparator_version not in self.RECONCILIATION_COMPARATORS:
            raise RepositoryIntegrityError(f"unsupported comparator version: {comparator_version}")
        if match_status not in ("matched", "unmatched_official", "unmatched_secondary"):
            raise RepositoryIntegrityError(f"unsupported reconciliation match_status: {match_status}")
        if match_status == "matched":
            if not official_observation_id or not secondary_observation_id or official_observation_id == secondary_observation_id:
                raise RepositoryIntegrityError("matched reconciliation requires distinct official and secondary observations")
        elif match_status == "unmatched_official":
            if not official_observation_id or secondary_observation_id:
                raise RepositoryIntegrityError("unmatched_official requires only an official observation")
        elif not secondary_observation_id or official_observation_id:
            raise RepositoryIntegrityError("unmatched_secondary requires only a secondary observation")

        # Bind the stream ID to the source rows, not to a caller-chosen label.
        # This prevents a valid stream from being reused for another listing or
        # session while still allowing source/parser revisions to supersede it.
        subject_id = official_observation_id or secondary_observation_id
        subject_role = "official" if official_observation_id else "secondary"
        subject = self._eod_observation_for_comparison(subject_id, subject_role)
        if match_status == "matched":
            other_id = secondary_observation_id if official_observation_id else official_observation_id
            other_role = "secondary" if subject_role == "official" else "official"
            other = self._eod_observation_for_comparison(other_id, other_role)
            if subject[:4] != other[:4]:
                raise RepositoryIntegrityError("reconciliation observations must match exchange, listing, security, and trade date")
        expected_stream = self.eod_reconciliation_stream_id(subject[0], subject[1], subject[3])
        if comparison_stream_id != expected_stream:
            raise RepositoryIntegrityError("comparison stream does not match observation exchange, listing, session, and roles")

        parent = None
        if supersedes_reconciliation_id:
            parent = self._connection.execute(
                "SELECT comparison_stream_id,official_observation_id,secondary_observation_id FROM eod_observation_reconciliation WHERE reconciliation_id=?",
                [supersedes_reconciliation_id],
            ).fetchone()
            if parent is None or parent[0] != comparison_stream_id:
                raise RepositoryIntegrityError("reconciliation supersession must stay within one comparison stream")
            parent_subject_id = parent[1] or parent[2]
            parent_role = "official" if parent[1] else "secondary"
            parent_subject = self._eod_observation_for_comparison(parent_subject_id, parent_role)
            if parent_subject[:4] != subject[:4]:
                raise RepositoryIntegrityError("reconciliation supersession must preserve exchange, listing, security, and session")
            if self._connection.execute(
                "SELECT 1 FROM eod_observation_reconciliation WHERE supersedes_reconciliation_id=?",
                [supersedes_reconciliation_id],
            ).fetchone():
                raise RepositoryIntegrityError("reconciliation result already has a successor")
        leaves = self._connection.execute(
            """SELECT reconciliation_id FROM eod_observation_reconciliation r
               WHERE comparison_stream_id=? AND NOT EXISTS (
                 SELECT 1 FROM eod_observation_reconciliation n WHERE n.supersedes_reconciliation_id=r.reconciliation_id
               )""", [comparison_stream_id]
        ).fetchall()
        if len(leaves) > 1:
            raise RepositoryIntegrityError("comparison stream has multiple active reconciliation leaves")
        if leaves and (not supersedes_reconciliation_id or leaves[0][0] != supersedes_reconciliation_id):
            raise RepositoryIntegrityError("new comparison must supersede the active result in its stream")
        if not leaves and supersedes_reconciliation_id:
            raise RepositoryIntegrityError("cannot supersede a non-leaf reconciliation result")

        compared_fields_json = differences_json = None
        reason = not_compared_reason_code
        if match_status == "matched":
            official = self._eod_observation_for_comparison(official_observation_id, "official")
            secondary = self._eod_observation_for_comparison(secondary_observation_id, "secondary")
            if official[:4] != secondary[:4]:
                raise RepositoryIntegrityError("reconciliation observations must match exchange, listing, security, and trade date")
            if official[4] != secondary[4]:
                raise RepositoryIntegrityError("reconciliation canonical price, volume, or turnover units differ")
            fields = self.RECONCILIATION_COMPARATORS[comparator_version]
            values: dict[str, dict[str, str]] = {}
            differences: dict[str, dict[str, str]] = {}
            quality_reasons = {
                "missing": "missing_comparable_value",
                "not_applicable": "not_applicable_value",
                "invalid": "invalid_source_value",
                "stale": "stale_source_value",
                "conflicted": "conflicted_source_value",
            }
            invalid_quality = next((q for q in (official[6], secondary[6]) if q != "observed"), None)
            if invalid_quality is not None:
                reason = quality_reasons.get(invalid_quality, "invalid_source_value")
            else:
                for field in fields:
                    official_value = official[5][field]
                    secondary_value = secondary[5][field]
                    if official_value is None or secondary_value is None:
                        reason = "missing_comparable_value"
                        values = {}
                        differences = {}
                        break
                    try:
                        left, right = Decimal(str(official_value)), Decimal(str(secondary_value))
                    except InvalidOperation as exc:
                        raise RepositoryIntegrityError(f"non-numeric reconciliation field: {field}") from exc
                    if not left.is_finite() or not right.is_finite():
                        raise RepositoryIntegrityError(f"non-finite reconciliation field: {field}")
                    delta = right - left
                    item = {"official": str(left), "secondary": str(right), "delta": str(delta)}
                    values[field] = item
                    if delta != 0:
                        differences[field] = item
            if values:
                compared_fields_json = self._json_text(values)
                differences_json = self._json_text(differences)
                outcome = "discrepancy" if differences else "exact_match"
                reason = None
            else:
                outcome = "not_compared"
                if reason is None:
                    reason = "missing_comparable_value"
        else:
            outcome = "not_compared"
            if not reason:
                raise RepositoryIntegrityError("unmatched reconciliation requires a reason code")
            self._eod_observation_for_comparison(
                official_observation_id or secondary_observation_id,
                "official" if official_observation_id else "secondary",
            )

        now = datetime.now().astimezone()
        with self._transaction():
            self._connection.execute(
                """INSERT INTO eod_observation_reconciliation
                   (reconciliation_id,comparison_stream_id,comparator_version,official_observation_id,
                    secondary_observation_id,match_status,comparison_outcome,compared_fields_json,differences_json,
                    not_compared_reason_code,compared_at,supersedes_reconciliation_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [reconciliation_id, comparison_stream_id, comparator_version, official_observation_id,
                 secondary_observation_id, match_status, outcome, compared_fields_json, differences_json,
                 reason, now, supersedes_reconciliation_id],
            )
        return reconciliation_id, outcome

    def _eod_observation_for_comparison(self, observation_id: str, role: str):
        row = self._connection.execute(
            """SELECT o.exchange,o.listing_id,o.security_id,o.trade_date,o.price_unit,o.volume_unit,o.turnover_unit,
                      o.open_raw,o.high_raw,o.low_raw,o.close_raw,o.volume_raw,o.turnover_raw,o.quality_status,
                      d.provider,d.dataset
               FROM eod_price_observation_revision o
               JOIN source_document_revision d ON d.source_document_id=o.source_document_id
               WHERE o.observation_id=?""", [observation_id]
        ).fetchone()
        if row is None:
            raise RepositoryIntegrityError(f"unknown EOD observation: {observation_id}")
        provider = str(row[14]).upper()
        if role == "official" and not provider.startswith(row[0]):
            raise RepositoryIntegrityError("official reconciliation side does not have matching exchange provenance")
        if role == "secondary" and provider.startswith(("NSE", "BSE")):
            raise RepositoryIntegrityError("secondary reconciliation side has official-exchange provenance")
        fields = dict(zip(("open_raw", "high_raw", "low_raw", "close_raw", "volume_raw", "turnover_raw"), row[7:13]))
        return (row[0], row[1], row[2], row[3], (row[4], row[5], row[6]), fields, row[13])

    def _source_available(
        self,
        source_document_id: str,
        *,
        exchange: str,
        screen_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
    ) -> bool:
        source = self._connection.execute(
            """SELECT publication_date,CAST(published_at AS VARCHAR),
                      CAST(ingestion_timestamp AS VARCHAR)
               FROM source_document_revision WHERE source_document_id=?""",
            [source_document_id],
        ).fetchone()
        if source is None:
            return False
        publication_date, published_at, ingestion_timestamp = source
        if published_at is not None:
            published_at = datetime.fromisoformat(str(published_at).replace(" ", "T", 1))
            public = published_at <= cutoff
        else:
            session = self._connection.execute(
                """SELECT min(session_date) FROM exchange_trading_session
                   WHERE exchange=? AND calendar_version=? AND is_trading_session=TRUE
                     AND session_date>?""",
                [exchange, calendar_version, publication_date],
            ).fetchone()[0]
            public = session is not None and session <= screen_date
        if availability_mode == "public_as_of":
            return public
        if availability_mode == "hamsa_known_as_of":
            ingested_at = datetime.fromisoformat(str(ingestion_timestamp).replace(" ", "T", 1))
            return public and ingested_at <= cutoff
        raise RepositoryIntegrityError("availability_mode must be public_as_of or hamsa_known_as_of")

    def derive_universe_disposition(
        self,
        *,
        listing_id: str,
        observation_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str,
    ) -> str:
        """Derive mainboard eligibility from identity, independent classes, and effective listing status."""
        self._aware(cutoff, "cutoff")
        if availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("availability_mode must be public_as_of or hamsa_known_as_of")
        if not calendar_version:
            raise RepositoryIntegrityError("calendar_version is required for point-in-time eligibility")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        market_tz = MARKET_TIMEZONE
        local_cutoff = cutoff.astimezone(market_tz)
        if local_cutoff.date() != observation_date:
            raise RepositoryIntegrityError("screen cutoff date must equal the EOD observation date")
        if local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("listing eligibility requires the 15:30 Asia/Kolkata EOD cutoff")
        session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s
               LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=(SELECT exchange FROM exchange_listing WHERE listing_id=?)
                 AND s.session_date=? AND s.calendar_version=?""",
            [listing_id, observation_date, calendar_version],
        ).fetchone()
        if session is None or not session[0]:
            return "unresolved_classification"
        listing = self._connection.execute(
            "SELECT security_id,exchange FROM exchange_listing WHERE listing_id=?", [listing_id]
        ).fetchone()
        if listing is None:
            return "unresolved_classification"
        security_id, exchange = listing
        if not session[1] or session[2] is None or not str(session[2]).upper().startswith(exchange):
            return "unresolved_classification"
        if not self._source_available(
            session[1], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version,
        ):
            return "unresolved_classification"

        known_mode = availability_mode == "hamsa_known_as_of"
        identifier_rows = self._connection.execute(
            """SELECT i.identifier_value,COALESCE(r.evidence_source_document_id, i.source_document_id)
               FROM security_identifier_revision i
               LEFT JOIN security_identifier_revision_review r
                 ON r.identifier_revision_id=i.identifier_revision_id
                AND (? OR r.recorded_at<=?)
                AND NOT EXISTS (
                  SELECT 1 FROM security_identifier_revision_review s
                  WHERE s.supersedes_review_id=r.review_id AND (? OR s.recorded_at<=?)
                )
               WHERE i.security_id=? AND i.identifier_type='ISIN'
                 AND r.review_status='approved'
                 AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
            [not known_mode, cutoff, not known_mode, cutoff, security_id, observation_date, observation_date],
        ).fetchall()
        if len(identifier_rows) != 1:
            return "unresolved_classification"
        isin, identity_source_id = identifier_rows[0]
        competing_security = self._connection.execute(
            """SELECT DISTINCT i.security_id FROM security_identifier_revision i
               LEFT JOIN security_identifier_revision_review r
                 ON r.identifier_revision_id=i.identifier_revision_id
                AND (? OR r.recorded_at<=?)
                AND NOT EXISTS (
                  SELECT 1 FROM security_identifier_revision_review s
                  WHERE s.supersedes_review_id=r.review_id AND (? OR s.recorded_at<=?)
                )
               WHERE i.identifier_type='ISIN' AND i.identifier_value=?
                 AND r.review_status='approved'
                 AND i.effective_from<=? AND (i.effective_to IS NULL OR i.effective_to>=?)""",
            [not known_mode, cutoff, not known_mode, cutoff, isin, observation_date, observation_date],
        ).fetchall()
        if len(competing_security) != 1 or competing_security[0][0] != security_id:
            return "unresolved_classification"
        if not self._source_available(identity_source_id, exchange=exchange, screen_date=observation_date,
                                      cutoff=cutoff, availability_mode=availability_mode,
                                      calendar_version=calendar_version):
            return "unresolved_classification"

        listing_revisions = self._connection.execute(
            """SELECT listing_revision_id,status,source_document_id FROM exchange_listing_revision
               WHERE listing_id=? AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?)""",
            [listing_id, observation_date, observation_date],
        ).fetchall()
        approved_listing_revisions = []
        for revision_id, status, source_id in listing_revisions:
            reviews = self._connection.execute(
                """SELECT r.review_status,r.evidence_source_document_id
                   FROM exchange_listing_revision_review r
                   WHERE r.listing_revision_id=? AND (? OR r.recorded_at<=?)
                     AND r.reviewed_at IS NOT NULL AND (? OR r.reviewed_at<=?)
                     AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision_review n
                       WHERE n.supersedes_review_id=r.listing_revision_review_id AND (? OR n.recorded_at<=?))""",
                [revision_id, not known_mode, cutoff, not known_mode, cutoff, not known_mode, cutoff],
            ).fetchall()
            approved = [r for r in reviews if r[0] == "approved"]
            if len(approved) == 1 and self._source_available(source_id, exchange=exchange, screen_date=observation_date,
                    cutoff=cutoff, availability_mode=availability_mode, calendar_version=calendar_version) and self._source_available(
                    approved[0][1], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version):
                approved_listing_revisions.append(status)
        if len(approved_listing_revisions) != 1:
            return "unresolved_classification"
        listing_status = approved_listing_revisions[0]
        if listing_status in ("suspended", "delisted"):
            return "excluded_inactive_non_trading"

        dimension_values: dict[str, str] = {}
        for dimension in ("instrument", "platform"):
            status_col = f"{dimension}_review_status"
            class_col = f"{dimension}_class"
            from_col = f"{dimension}_valid_from"
            to_col = f"{dimension}_valid_to"
            evidence_col = f"{dimension}_evidence_source_document_id"
            query = f"""SELECT r.{class_col},r.{evidence_col},s.source_document_id,
                                CAST(s.extraction_timestamp AS VARCHAR)
                         FROM listing_classification_review_revision r
                         JOIN listing_classification_snapshot s
                           ON s.listing_classification_snapshot_id=r.listing_classification_snapshot_id
                         WHERE r.listing_id=? AND r.{status_col}='approved'
                           AND r.{from_col}<=? AND (r.{to_col} IS NULL OR r.{to_col}>=?)
                           AND (? OR r.recorded_at<=?)
                           AND r.{dimension}_reviewed_at IS NOT NULL AND (? OR r.{dimension}_reviewed_at<=?)
                           AND NOT EXISTS (SELECT 1 FROM listing_classification_review_revision n
                             WHERE n.supersedes_review_revision_id=r.classification_review_revision_id
                               AND (? OR n.recorded_at<=?))"""
            candidates = self._connection.execute(
                query, [listing_id, observation_date, observation_date, not known_mode, cutoff, not known_mode, cutoff, not known_mode, cutoff]
            ).fetchall()
            valid = []
            for value, evidence_id, snapshot_source_id, extraction_timestamp in candidates:
                if self._source_available(snapshot_source_id, exchange=exchange, screen_date=observation_date,
                        cutoff=cutoff, availability_mode=availability_mode, calendar_version=calendar_version) and self._source_available(
                        evidence_id, exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                        availability_mode=availability_mode, calendar_version=calendar_version):
                    if availability_mode == "hamsa_known_as_of":
                        extracted_at = datetime.fromisoformat(str(extraction_timestamp).replace(" ", "T", 1))
                        if extracted_at > cutoff:
                            continue
                    valid.append(value)
            if len(valid) != 1:
                return "unresolved_classification"
            dimension_values[dimension] = valid[0]

        instrument_class = dimension_values["instrument"]
        platform_class = dimension_values["platform"]
        if instrument_class == "unknown" or platform_class == "unknown":
            return "unresolved_classification"
        if instrument_class != "ordinary_equity":
            return "excluded_non_equity"
        if platform_class == "sme":
            return "excluded_sme"
        if platform_class == "other_platform":
            return "excluded_other_platform"
        if platform_class != "mainboard":
            return "unresolved_classification"
        return "eligible_mainboard_ordinary_equity"

    def source_documents_for_review(self, exchange: str | None = None) -> list[dict[str, object]]:
        """List registered evidence with file checksums and captured source locators."""
        if exchange is not None and exchange not in ("NSE", "BSE"):
            raise RepositoryIntegrityError("exchange must be NSE or BSE")
        query = """SELECT d.source_document_id,d.provider,d.dataset,d.source_identifier,d.checksum_sha256,
                          d.source_document_date,d.publication_date,CAST(d.published_at AS VARCHAR),
                          d.parser_version,d.extraction_locator,f.original_filename,f.archive_path,f.metadata_json
                   FROM source_document_revision d JOIN raw_source_file f USING(source_file_id)"""
        params: list[object] = []
        if exchange:
            query += " WHERE d.provider=?"
            params.append(exchange)
        query += " ORDER BY d.ingestion_timestamp DESC,d.source_identifier"
        rows = self._connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            try:
                metadata = json.loads(row[12] or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            output.append({
                "source_document_id": row[0], "provider": row[1], "dataset": row[2],
                "source_identifier": row[3], "checksum_sha256": row[4],
                "source_document_date": row[5], "publication_date": row[6],
                "published_at": row[7], "parser_version": row[8], "document_locator": row[9],
                "original_filename": row[10], "archive_path": row[11],
                "source_locator": metadata.get("source_locator"),
                "source_origin": metadata.get("source_origin", "not_recorded"),
            })
        return output

    def security_admission_candidates(self) -> list[dict[str, object]]:
        """Return identity/listing candidates without applying a latest-row-wins rule."""
        rows = self._connection.execute(
            """SELECT i.entity_id,n.legal_name,e.security_id,e.share_class,l.listing_id,l.exchange,
                      l.exchange_instrument_id,s.identifier_value
               FROM issuer_entity i
               LEFT JOIN issuer_name_revision n ON n.entity_id=i.entity_id
               LEFT JOIN equity_security e ON e.issuer_entity_id=i.entity_id
               LEFT JOIN exchange_listing l ON l.security_id=e.security_id
               LEFT JOIN security_identifier_revision s ON s.security_id=e.security_id AND s.identifier_type='ISIN'
               ORDER BY coalesce(n.legal_name,i.entity_id),e.security_id,l.exchange,l.exchange_instrument_id"""
        ).fetchall()
        return [dict(zip(("issuer_entity_id", "legal_name", "security_id", "share_class", "listing_id",
                          "exchange", "exchange_instrument_id", "isin"), row)) for row in rows]

    def security_identity_revisions(self, security_id: str | None = None) -> list[dict[str, object]]:
        query = """SELECT i.identifier_revision_id,i.security_id,i.identifier_type,i.identifier_value,
                          i.effective_from,i.effective_to,i.source_document_id,i.mapping_review_status,
                          r.review_status,r.reviewed_by,CAST(r.reviewed_at AS VARCHAR),
                          r.evidence_locator,i.supersedes_identifier_revision_id,
                          r.review_id
                   FROM security_identifier_revision i
                   LEFT JOIN security_identifier_revision_review r
                     ON r.identifier_revision_id=i.identifier_revision_id
                    AND NOT EXISTS (
                      SELECT 1 FROM security_identifier_revision_review s
                      WHERE s.supersedes_review_id=r.review_id
                    )"""
        params: list[object] = []
        if security_id:
            query += " WHERE i.security_id=?"
            params.append(security_id)
        query += " ORDER BY i.effective_from,i.identifier_revision_id"
        rows = self._connection.execute(query, params).fetchall()
        keys = ("identifier_revision_id", "security_id", "identifier_type", "identifier_value", "effective_from",
                "effective_to", "source_document_id", "candidate_status", "review_status", "reviewer",
                "reviewed_at", "evidence_locator", "supersedes_identifier_revision_id", "active_review_id")
        return [dict(zip(keys, row)) for row in rows]

    def exchange_listing_revisions(self, listing_id: str | None = None) -> list[dict[str, object]]:
        query = """SELECT r.listing_revision_id,r.listing_id,r.symbol,r.series,r.status,r.effective_from,r.effective_to,
                          r.source_document_id,r.extraction_locator,r.supersedes_listing_revision_id,
                          v.review_status,v.reviewed_by,v.evidence_source_document_id,v.evidence_locator,
                          v.listing_revision_review_id
                   FROM exchange_listing_revision r LEFT JOIN exchange_listing_revision_review v
                     ON v.listing_revision_id=r.listing_revision_id
                    AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision_review n
                      WHERE n.supersedes_review_id=v.listing_revision_review_id)"""
        params: list[object] = []
        if listing_id:
            query += " WHERE r.listing_id=?"
            params.append(listing_id)
        query += " ORDER BY r.effective_from,r.listing_revision_id"
        rows = self._connection.execute(query, params).fetchall()
        keys = ("listing_revision_id", "listing_id", "symbol", "series", "status", "effective_from", "effective_to",
                "source_document_id", "extraction_locator", "supersedes_listing_revision_id", "review_status",
                "reviewer", "review_evidence_source_document_id", "review_evidence_locator", "active_review_id")
        return [dict(zip(keys, row)) for row in rows]

    def classification_snapshots(self, listing_id: str | None = None) -> list[dict[str, object]]:
        query = """SELECT s.listing_classification_snapshot_id,s.listing_id,s.exchange,s.source_document_id,
                          s.source_snapshot_date,s.raw_isin,s.raw_symbol,s.raw_series,s.raw_listing_status,
                          s.raw_instrument_class_value,s.raw_platform_class_value,s.source_fields_json,
                          s.extraction_locator,r.classification_review_revision_id,r.instrument_review_status,
                          r.instrument_class,r.instrument_valid_from,r.instrument_valid_to,r.instrument_evidence_source_document_id,
                          r.instrument_evidence_locator,r.instrument_reviewed_by,r.platform_review_status,r.platform_class,
                          r.platform_valid_from,r.platform_valid_to,r.platform_evidence_source_document_id,
                          r.platform_evidence_locator,r.platform_reviewed_by,r.supersedes_review_revision_id
                   FROM listing_classification_snapshot s LEFT JOIN listing_classification_review_revision r
                     ON r.listing_classification_snapshot_id=s.listing_classification_snapshot_id
                    AND NOT EXISTS (SELECT 1 FROM listing_classification_review_revision n
                      WHERE n.supersedes_review_revision_id=r.classification_review_revision_id)"""
        params: list[object] = []
        if listing_id:
            query += " WHERE s.listing_id=?"
            params.append(listing_id)
        query += " ORDER BY s.source_snapshot_date,s.listing_classification_snapshot_id"
        rows = self._connection.execute(query, params).fetchall()
        keys = ("snapshot_id", "listing_id", "exchange", "source_document_id", "source_snapshot_date", "raw_isin",
                "raw_symbol", "raw_series", "raw_listing_status", "raw_instrument_class", "raw_platform_class",
                "source_fields", "extraction_locator", "review_revision_id", "instrument_review_status",
                "instrument_class", "instrument_valid_from", "instrument_valid_to", "instrument_evidence_source_document_id",
                "instrument_evidence_locator", "instrument_reviewer", "platform_review_status", "platform_class",
                "platform_valid_from", "platform_valid_to", "platform_evidence_source_document_id",
                "platform_evidence_locator", "platform_reviewer", "supersedes_review_revision_id")
        return [dict(zip(keys, row)) for row in rows]

    def _source_available_for_checklist(
        self,
        source_document_id: str,
        *,
        exchange: str,
        screen_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str | None,
    ) -> bool:
        if calendar_version is not None:
            return self._source_available(
                source_document_id, exchange=exchange, screen_date=screen_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            )
        source = self._connection.execute(
            """SELECT publication_date,CAST(published_at AS VARCHAR),
                      CAST(ingestion_timestamp AS VARCHAR)
               FROM source_document_revision WHERE source_document_id=?""",
            [source_document_id],
        ).fetchone()
        if source is None:
            return False
        publication_date, published_at, ingestion_timestamp = source
        if published_at is not None:
            public = datetime.fromisoformat(str(published_at).replace(" ", "T", 1)) <= cutoff
        else:
            public = publication_date < screen_date
        if availability_mode == "public_as_of":
            return public
        if availability_mode == "hamsa_known_as_of":
            ingested_at = datetime.fromisoformat(str(ingestion_timestamp).replace(" ", "T", 1))
            return public and ingested_at <= cutoff
        raise RepositoryIntegrityError("availability_mode must be public_as_of or hamsa_known_as_of")

    def security_admission_checklist(
        self,
        *,
        listing_id: str,
        observation_date: date,
        cutoff: datetime,
        availability_mode: str,
        calendar_version: str | None,
    ) -> dict[str, object]:
        """Explain each admission prerequisite while retaining fail-closed PIT behavior."""
        self._aware(cutoff, "cutoff")
        listing = self._connection.execute(
            """SELECT l.security_id,l.exchange,l.exchange_instrument_id,i.entity_id
               FROM exchange_listing l JOIN equity_security e USING(security_id)
               JOIN issuer_entity i ON i.entity_id=e.issuer_entity_id WHERE l.listing_id=?""", [listing_id]
        ).fetchone()
        if listing is None:
            raise RepositoryIntegrityError("unknown exchange listing")
        security_id, exchange, instrument_id, entity_id = listing
        checks: list[dict[str, object]] = []

        known_mode = availability_mode == "hamsa_known_as_of"
        identity = self._connection.execute(
            """SELECT i.identifier_revision_id,i.identifier_value,
                      COALESCE(r.evidence_source_document_id, i.source_document_id),
                      COALESCE(r.evidence_locator, i.extraction_locator)
               FROM security_identifier_revision i
               LEFT JOIN security_identifier_revision_review r
                 ON r.identifier_revision_id=i.identifier_revision_id
                AND (? OR r.recorded_at<=?)
                AND NOT EXISTS (
                  SELECT 1 FROM security_identifier_revision_review s
                  WHERE s.supersedes_review_id=r.review_id AND (? OR s.recorded_at<=?)
                )
               WHERE i.security_id=? AND i.identifier_type='ISIN'
                 AND r.review_status='approved'
                 AND i.effective_from<=?
                 AND (i.effective_to IS NULL OR i.effective_to>=?)""",
            [not known_mode, cutoff, not known_mode, cutoff, security_id, observation_date, observation_date],
        ).fetchall()
        identity_visible = [row for row in identity if self._source_available_for_checklist(
            row[2], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=calendar_version)]
        checks.append({"prerequisite": "ISIN identity mapping", "status": "Approved" if len(identity_visible)==1 else
                       "Conflict" if len(identity_visible)>1 else "Unproven",
                       "detail": identity_visible[0][1] if len(identity_visible)==1 else "One reviewed, effective ISIN mapping is required.",
                       "source_documents": [r[2] for r in identity_visible],
                       "locators": [r[3] for r in identity_visible]})

        listing_rows = self._connection.execute(
            """SELECT r.listing_revision_id,r.status,r.source_document_id,r.extraction_locator
               FROM exchange_listing_revision r WHERE r.listing_id=? AND r.effective_from<=?
                 AND (r.effective_to IS NULL OR r.effective_to>=?)""", [listing_id, observation_date, observation_date]
        ).fetchall()
        listing_approved = []
        for revision_id,status,source_id,locator in listing_rows:
            reviews = self._connection.execute(
                """SELECT r.review_status,r.evidence_source_document_id,r.evidence_locator
                   FROM exchange_listing_revision_review r WHERE r.listing_revision_id=? AND (? OR r.recorded_at<=?)
                     AND r.reviewed_at IS NOT NULL AND (? OR r.reviewed_at<=?)
                     AND NOT EXISTS (SELECT 1 FROM exchange_listing_revision_review n
                       WHERE n.supersedes_review_id=r.listing_revision_review_id AND (? OR n.recorded_at<=?))""",
                [revision_id, not known_mode, cutoff, not known_mode, cutoff, not known_mode, cutoff],
            ).fetchall()
            approved = [r for r in reviews if r[0] == "approved"]
            if len(approved)==1 and all(self._source_available_for_checklist(
                    source_id if source_idx==0 else approved[0][1],
                    exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                    availability_mode=availability_mode, calendar_version=calendar_version)
                    for source_idx in (0,1)):
                listing_approved.append((status,source_id,locator,approved[0][1],approved[0][2]))
        checks.append({"prerequisite": "Effective listing status", "status": "Approved" if len(listing_approved)==1 else
                       "Conflict" if len(listing_rows)>1 or len(listing_approved)>1 else "Unproven",
                       "detail": f"{listing_approved[0][0]}" if len(listing_approved)==1 else
                       "One effective listing interval and its approved evidence-backed review are required.",
                       "source_documents": [v for row in listing_approved for v in (row[1],row[3])],
                       "locators": [v for row in listing_approved for v in (row[2],row[4])]})

        for dimension in ("instrument", "platform"):
            status_col, class_col = f"{dimension}_review_status", f"{dimension}_class"
            from_col, to_col = f"{dimension}_valid_from", f"{dimension}_valid_to"
            evidence_col, locator_col = f"{dimension}_evidence_source_document_id", f"{dimension}_evidence_locator"
            reviewed_col = f"{dimension}_reviewed_at"
            rows = self._connection.execute(
                f"""SELECT r.classification_review_revision_id,r.{class_col},r.{evidence_col},r.{locator_col},
                           s.source_document_id,s.extraction_locator,CAST(s.extraction_timestamp AS VARCHAR)
                    FROM listing_classification_review_revision r JOIN listing_classification_snapshot s
                      ON s.listing_classification_snapshot_id=r.listing_classification_snapshot_id
                    WHERE r.listing_id=? AND r.{status_col}='approved' AND r.{from_col}<=?
                      AND (r.{to_col} IS NULL OR r.{to_col}>=?) AND (? OR r.recorded_at<=?)
                      AND r.{reviewed_col} IS NOT NULL AND (? OR r.{reviewed_col}<=?)
                      AND NOT EXISTS (SELECT 1 FROM listing_classification_review_revision n
                        WHERE n.supersedes_review_revision_id=r.classification_review_revision_id AND (? OR n.recorded_at<=?))""",
                [listing_id, observation_date, observation_date, not known_mode, cutoff, not known_mode, cutoff, not known_mode, cutoff],
            ).fetchall()
            visible = []
            for row in rows:
                if (self._source_available_for_checklist(row[2], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                        availability_mode=availability_mode, calendar_version=calendar_version) and self._source_available_for_checklist(
                        row[4], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                        availability_mode=availability_mode, calendar_version=calendar_version)):
                    if availability_mode == "hamsa_known_as_of" and datetime.fromisoformat(
                        str(row[6]).replace(" ","T",1)
                    ) > cutoff:
                        continue
                    visible.append(row)
            checks.append({"prerequisite": f"{dimension.title()} classification", "status": "Approved" if len(visible)==1 else
                           "Conflict" if len(visible)>1 else "Unproven",
                           "detail": visible[0][1] if len(visible)==1 else
                           f"Exactly one approved, evidence-backed {dimension} classification interval is required.",
                           "source_documents": [v for row in visible for v in (row[2],row[4])],
                           "locators": [v for row in visible for v in (row[3],row[5])]})

        calendar_status = "Unproven"
        calendar_detail = "Select a loaded, explicitly versioned exchange calendar."
        calendar_sources: list[str] = []
        if calendar_version:
            session = self._connection.execute(
                """SELECT s.is_trading_session,s.source_document_id FROM exchange_trading_session s
                   WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
                [exchange, observation_date, calendar_version],
            ).fetchone()
            if session and session[0] and session[1] and self._source_available(
                session[1], exchange=exchange, screen_date=observation_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            ):
                calendar_status, calendar_detail, calendar_sources = "Approved", calendar_version, [session[1]]
            elif session:
                calendar_detail = "Selected version has no eligible trading session for this date."
        checks.append({"prerequisite": "Exchange trading session", "status": calendar_status,
                       "detail": calendar_detail, "source_documents": calendar_sources, "locators": []})

        disposition = "unresolved_classification"
        if calendar_version:
            disposition = self.derive_universe_disposition(
                listing_id=listing_id, observation_date=observation_date, cutoff=cutoff,
                availability_mode=availability_mode, calendar_version=calendar_version,
            )
        return {"issuer_entity_id": entity_id, "security_id": security_id, "listing_id": listing_id,
                "exchange": exchange, "exchange_instrument_id": instrument_id,
                "checks": checks, "disposition": disposition}

    def append_unit_conversion_rule(
        self,
        *,
        conversion_rule_id: str,
        source_unit: str,
        canonical_unit: str,
        dimension: str,
        multiplier: Decimal,
        additive_offset: Decimal = Decimal("0"),
        rule_description: str,
        rule_version: str,
        review_status: str = "pending",
        source_document_id: str | None = None,
    ) -> str:
        """Append a unit conversion rule revision with canonical-unit validation."""
        if not all(str(v).strip() for v in (conversion_rule_id, source_unit, canonical_unit, dimension, rule_description, rule_version)):
            raise RepositoryIntegrityError("unit conversion rule requires non-empty identifiers, units, dimension, description, and version")
        if review_status not in ("pending", "approved", "rejected"):
            raise RepositoryIntegrityError("unit conversion rule review_status must be pending, approved, or rejected")
        if review_status == "approved" and not source_document_id:
            raise RepositoryIntegrityError("approved unit conversion rule requires a source_document_id")
        if source_document_id is not None:
            if self._connection.execute(
                "SELECT 1 FROM source_document_revision WHERE source_document_id=?", [source_document_id]
            ).fetchone() is None:
                raise RepositoryIntegrityError("unit conversion rule references an unknown source document")
        unit_row = self._connection.execute(
            "SELECT dimension FROM canonical_unit WHERE unit_code=?", [canonical_unit]
        ).fetchone()
        if unit_row is None or unit_row[0] != dimension:
            raise RepositoryIntegrityError("canonical_unit does not exist or disagrees with dimension")
        multiplier_dec = Decimal(str(multiplier))
        offset_dec = Decimal(str(additive_offset))
        if not multiplier_dec.is_finite() or multiplier_dec <= 0 or not offset_dec.is_finite():
            raise RepositoryIntegrityError("unit conversion multiplier must be positive finite and offset finite")
        now = datetime.now().astimezone()
        with self._transaction():
            self._connection.execute(
                """INSERT INTO unit_conversion_rule_revision
                   (conversion_rule_id,source_unit,canonical_unit,dimension,multiplier,additive_offset,
                    rule_description,rule_version,review_status,source_document_id,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                [conversion_rule_id, source_unit.strip(), canonical_unit.strip(), dimension.strip(),
                 multiplier_dec, offset_dec, rule_description.strip(), rule_version.strip(),
                 review_status, source_document_id, now],
            )
        return conversion_rule_id

    def append_screen_run(
        self,
        *,
        run_id: str,
        engine: str,
        profile_id: str,
        profile_version: str,
        business_class: str,
        configuration: Mapping[str, object],
        venue_policy_id: str,
        venue_policy_version: str,
        primary_exchange: str,
        fallback_exchange: str | None = None,
        combined_activity_allowed: bool = False,
        combined_activity_rule: str | None = None,
        as_of_session: date,
        cutoff: datetime,
        availability_mode: str,
        exchange_calendar_version: str,
        code_version: str,
        created_by: str,
        results: Iterable[Mapping[str, object]],
    ) -> str:
        """Persist an immutable point-in-time screen run and its source-linked results."""
        self._aware(cutoff, "cutoff")
        if engine not in ("compounders", "earnings_inflection", "capex_conversion", "cash_quality", "extreme_sell_side_liquidity"):
            raise RepositoryIntegrityError("unsupported screen engine")
        if business_class not in ("financial", "industrial"):
            raise RepositoryIntegrityError("screen profile business_class must be financial or industrial")
        if primary_exchange not in ("NSE", "BSE"):
            raise RepositoryIntegrityError("primary_exchange must be NSE or BSE")
        if availability_mode not in ("public_as_of", "hamsa_known_as_of"):
            raise RepositoryIntegrityError("invalid screen availability_mode")
        from hamsa.domain.trading_calendar import EOD_CUTOFF, MARKET_TIMEZONE

        local_cutoff = cutoff.astimezone(MARKET_TIMEZONE)
        if local_cutoff.date() != as_of_session or local_cutoff.time().replace(tzinfo=None) != EOD_CUTOFF:
            raise RepositoryIntegrityError("screen run cutoff must be 15:30 Asia/Kolkata on as_of_session")
        session = self._connection.execute(
            """SELECT s.is_trading_session,s.source_document_id,d.provider
               FROM exchange_trading_session s
               LEFT JOIN source_document_revision d USING(source_document_id)
               WHERE s.exchange=? AND s.session_date=? AND s.calendar_version=?""",
            [primary_exchange, as_of_session, exchange_calendar_version],
        ).fetchone()
        if session is None or not session[0] or not session[1] or session[2] is None \
                or not str(session[2]).upper().startswith(primary_exchange):
            raise RepositoryIntegrityError("screen run requires a sourced open trading session in the selected calendar")
        if not self._source_available(
            session[1], exchange=primary_exchange, screen_date=as_of_session, cutoff=cutoff,
            availability_mode=availability_mode, calendar_version=exchange_calendar_version,
        ):
            raise RepositoryIntegrityError("selected exchange calendar source was not available at screen cutoff")

        now = datetime.now().astimezone()
        config_json = self._json_text(dict(configuration))
        materialized_results = tuple(results)
        with self._transaction():
            existing_venue = self._connection.execute(
                """SELECT primary_exchange,fallback_exchange,combined_activity_allowed,combined_activity_rule
                   FROM venue_policy_revision WHERE policy_id=? AND version=?""",
                [venue_policy_id, venue_policy_version],
            ).fetchone()
            if existing_venue is None:
                self._connection.execute(
                    """INSERT INTO venue_policy_revision
                       (policy_id,version,primary_exchange,fallback_exchange,combined_activity_allowed,
                        combined_activity_rule,created_at,created_by)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [venue_policy_id, venue_policy_version, primary_exchange, fallback_exchange,
                     combined_activity_allowed, combined_activity_rule, now, created_by],
                )
            elif existing_venue != (primary_exchange, fallback_exchange, combined_activity_allowed, combined_activity_rule):
                raise RepositoryIntegrityError("venue policy version already exists with different rules")

            existing_profile = self._connection.execute(
                """SELECT business_class,CAST(configuration_json AS VARCHAR),venue_policy_id,venue_policy_version
                   FROM screen_profile_revision WHERE profile_id=? AND version=? AND engine=?""",
                [profile_id, profile_version, engine],
            ).fetchone()
            if existing_profile is None:
                self._connection.execute(
                    """INSERT INTO screen_profile_revision
                       (profile_id,version,business_class,engine,enabled,configuration_json,
                        venue_policy_id,venue_policy_version,created_at,created_by)
                       VALUES (?,?,?,?,TRUE,?,?,?,?,?)""",
                    [profile_id, profile_version, business_class, engine, config_json,
                     venue_policy_id, venue_policy_version, now, created_by],
                )
            elif (existing_profile[0], json.loads(existing_profile[1]), existing_profile[2], existing_profile[3]) != (
                business_class, dict(configuration), venue_policy_id, venue_policy_version
            ):
                raise RepositoryIntegrityError("screen profile version already exists with different configuration")

            self._connection.execute(
                """INSERT INTO screen_run
                   (run_id,engine,profile_id,profile_version,as_of_session,cutoff,availability_mode,
                    exchange_calendar_version,code_version,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [run_id, engine, profile_id, profile_version, as_of_session, cutoff,
                 availability_mode, exchange_calendar_version, code_version, now],
            )
            for item in materialized_results:
                result_id = str(item["result_id"])
                subject_id = str(item["subject_entity_id"])
                inputs_json = self._json_text(dict(item.get("inputs", {})))
                self._connection.execute(
                    """INSERT INTO screen_result
                       (result_id,run_id,subject_entity_id,calculation_expression,evaluated_inputs_json,result,explanation)
                       VALUES (?,?,?,?,?,?,?)""",
                    [result_id, run_id, subject_id, str(item["calculation_expression"]),
                     inputs_json, str(item["result"]), str(item["explanation"])],
                )
                for doc_id in dict.fromkeys(item.get("source_document_ids", ())):
                    self._connection.execute(
                        "INSERT INTO screen_result_source_document (result_id,source_document_id) VALUES (?,?)",
                        [result_id, str(doc_id)],
                    )
                for obs_id in dict.fromkeys(item.get("source_observation_ids", ())):
                    reg = self._connection.execute(
                        "SELECT observation_type FROM normalized_observation_registry WHERE observation_id=?",
                        [str(obs_id)],
                    ).fetchone()
                    if reg is None:
                        raise RepositoryIntegrityError(f"screen result references unknown observation: {obs_id}")
                    self._connection.execute(
                        "INSERT INTO screen_result_source_observation (result_id,observation_id,observation_type) VALUES (?,?,?)",
                        [result_id, str(obs_id), reg[0]],
                    )
        return run_id

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DuckDBRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
