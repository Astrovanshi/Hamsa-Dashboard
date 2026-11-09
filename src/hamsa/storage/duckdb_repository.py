"""Application repository with append-only historical observation writes.

There is deliberately no public SQL connection, UPDATE, or DELETE method.
DuckDB file owners retain direct database access and can bypass this boundary;
see the architecture notes for that limitation.
"""

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Iterator

import duckdb

from hamsa.domain.financials import FinancialObservationRevision


class RepositoryIntegrityError(ValueError):
    """An append violates a cross-table or revision-chain invariant."""


class DuckDBRepository:
    SCHEMA_NAME = "hamsa_analytics"
    SCHEMA_VERSION = 1
    BASELINE_MIGRATION = "0001_initial_analytics"

    def __init__(self, database_path: str | Path = ":memory:", *, schema_path: str | Path | None = None):
        self._database_path = str(database_path)
        self._schema_path = Path(schema_path) if schema_path else Path(__file__).resolve().parents[3] / "sql" / "duckdb_schema.sql"
        self._connection = duckdb.connect(self._database_path)
        try:
            self._initialize()
        except Exception:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        schema_bytes = self._schema_path.read_bytes()
        self._connection.execute(schema_bytes.decode("utf-8"))
        schema_checksum = sha256(schema_bytes).hexdigest()
        metadata = self._connection.execute(
            "SELECT current_version, current_migration FROM schema_metadata WHERE schema_name = ?",
            [self.SCHEMA_NAME],
        ).fetchone()
        if metadata is None:
            raise RepositoryIntegrityError("schema metadata row is missing after schema initialization")
        version, migration = metadata
        if version != self.SCHEMA_VERSION or migration != self.BASELINE_MIGRATION:
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
                [self.BASELINE_MIGRATION, self.SCHEMA_VERSION, schema_checksum, "hamsa-storage"],
            )
        elif existing[0] != schema_checksum:
            raise RepositoryIntegrityError(
                "baseline schema checksum differs from the migration record; an explicit migration is required"
            )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN TRANSACTION")
        try:
            yield
        except Exception:
            self._connection.execute("ROLLBACK")
            raise
        else:
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
        if observation.parser_version != parser_version:
            raise RepositoryIntegrityError("financial observation parser version disagrees with its source document")

        metric = connection.execute(
            "SELECT canonical_unit FROM financial_metric_definition WHERE metric = ?",
            [observation.metric],
        ).fetchone()
        if metric is None:
            raise RepositoryIntegrityError("financial observation references an unknown metric")
        if metric[0] != observation.canonical_unit:
            raise RepositoryIntegrityError("financial observation canonical unit disagrees with metric definition")
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
            connection.execute(
                """INSERT INTO normalized_observation_registry
                   (observation_id, observation_type, source_document_id, source_identifier,
                    checksum_sha256, parser_version, extraction_timestamp, extraction_locator, formula_version)
                   SELECT ?, 'financial', d.source_document_id, d.source_identifier, d.checksum_sha256,
                          ?, ?, ?, ?
                   FROM source_document_revision d WHERE d.source_document_id = ?""",
                [
                    observation.observation_id, observation.parser_version, observation.extraction_timestamp,
                    observation.source_locator, observation.formula_version, observation.source_document_id,
                ],
            )
            connection.execute(
                """INSERT INTO financial_observation_revision (
                   observation_id, observation_type, subject_entity_id, metric, raw_value, raw_unit,
                   canonical_value, canonical_unit, conversion_rule_id, period_start, period_end,
                   source_document_date, publication_date, published_at, publication_precision,
                   ingestion_timestamp, revision_number, source_document_id, as_reported_status,
                   quality_status, quality_reason, reporting_scope, parser_version,
                   extraction_timestamp, extraction_locator, formula_version, supersedes_observation_id
                   ) VALUES (?, 'financial', ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    observation.observation_id, observation.subject_id, observation.metric,
                    observation.raw_value, observation.raw_unit, observation.canonical_value,
                    observation.canonical_unit, observation.period_start, observation.period_end,
                    observation.source_document_date, observation.publication_date, observation.published_at,
                    observation.publication_precision.value, observation.ingestion_timestamp,
                    observation.revision_number, observation.source_document_id,
                    observation.as_reported_status.value, observation.quality_status.value,
                    observation.quality_reason, observation.reporting_scope, observation.parser_version,
                    observation.extraction_timestamp, observation.source_locator, observation.formula_version,
                    observation.supersedes_observation_id,
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

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "DuckDBRepository":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
