-- Adds extraction/parser-attempt lineage independently of source-file revisions.
ALTER TABLE source_document_revision
    ADD COLUMN IF NOT EXISTS replay_timestamp TIMESTAMPTZ;

ALTER TABLE financial_observation_revision
    ADD COLUMN IF NOT EXISTS replay_timestamp TIMESTAMPTZ;

ALTER TABLE normalized_observation_registry
    ADD COLUMN IF NOT EXISTS extraction_revision_id VARCHAR;

ALTER TABLE security_identifier_revision ADD COLUMN IF NOT EXISTS parser_version VARCHAR;
ALTER TABLE security_identifier_revision ADD COLUMN IF NOT EXISTS extraction_timestamp TIMESTAMPTZ;
ALTER TABLE security_identifier_revision ADD COLUMN IF NOT EXISTS extraction_locator VARCHAR;
ALTER TABLE security_identifier_revision ADD COLUMN IF NOT EXISTS extraction_revision_id VARCHAR;

ALTER TABLE exchange_listing_revision ADD COLUMN IF NOT EXISTS parser_version VARCHAR;
ALTER TABLE exchange_listing_revision ADD COLUMN IF NOT EXISTS extraction_timestamp TIMESTAMPTZ;
ALTER TABLE exchange_listing_revision ADD COLUMN IF NOT EXISTS extraction_locator VARCHAR;
ALTER TABLE exchange_listing_revision ADD COLUMN IF NOT EXISTS extraction_revision_id VARCHAR;

CREATE TABLE IF NOT EXISTS source_document_processing_revision (
    processing_revision_id VARCHAR PRIMARY KEY,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    parser_version VARCHAR NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    replay_timestamp TIMESTAMPTZ,
    status VARCHAR NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
    accepted_count INTEGER NOT NULL CHECK (accepted_count >= 0),
    rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
    quarantined_count INTEGER NOT NULL CHECK (quarantined_count >= 0),
    error_summary VARCHAR,
    supersedes_processing_revision_id VARCHAR REFERENCES source_document_processing_revision(processing_revision_id),
    UNIQUE (source_document_id, parser_version, attempt_number)
);

-- Backfill parser-attempt provenance for normalized rows that predate this table.
INSERT INTO source_document_processing_revision (
    processing_revision_id, source_document_id, parser_version, attempt_number,
    started_at, completed_at, replay_timestamp, status,
    accepted_count, rejected_count, quarantined_count, error_summary, supersedes_processing_revision_id
)
SELECT 'proc-' || md5(source_document_id || '|' || parser_version || '|' || CAST(extraction_timestamp AS VARCHAR)),
       source_document_id,
       parser_version,
       row_number() OVER (PARTITION BY source_document_id, parser_version ORDER BY extraction_timestamp),
       extraction_timestamp,
       extraction_timestamp,
       NULL,
       'succeeded',
       0, 0, 0, 'migrated from schema v1 registry', NULL
FROM (
    SELECT DISTINCT source_document_id, parser_version, extraction_timestamp
    FROM normalized_observation_registry
    WHERE source_document_id IS NOT NULL AND parser_version IS NOT NULL AND extraction_timestamp IS NOT NULL
) prior
WHERE NOT EXISTS (
    SELECT 1 FROM source_document_processing_revision p
    WHERE p.source_document_id = prior.source_document_id
      AND p.parser_version = prior.parser_version
      AND p.started_at = prior.extraction_timestamp
);

UPDATE normalized_observation_registry AS r
SET extraction_revision_id = p.processing_revision_id
FROM source_document_processing_revision AS p
WHERE r.source_document_id = p.source_document_id
  AND r.parser_version = p.parser_version
  AND r.extraction_timestamp = p.started_at
  AND r.extraction_revision_id IS NULL;

UPDATE security_identifier_revision AS i
SET parser_version=d.parser_version, extraction_timestamp=d.extraction_timestamp,
    extraction_locator=d.extraction_locator,
    extraction_revision_id=p.processing_revision_id
FROM source_document_revision AS d
LEFT JOIN source_document_processing_revision AS p
  ON p.source_document_id=d.source_document_id AND p.parser_version=d.parser_version AND p.status='succeeded'
WHERE i.source_document_id=d.source_document_id AND i.parser_version IS NULL;

UPDATE exchange_listing_revision AS l
SET parser_version=d.parser_version, extraction_timestamp=d.extraction_timestamp,
    extraction_locator=d.extraction_locator,
    extraction_revision_id=p.processing_revision_id
FROM source_document_revision AS d
LEFT JOIN source_document_processing_revision AS p
  ON p.source_document_id=d.source_document_id AND p.parser_version=d.parser_version AND p.status='succeeded'
WHERE l.source_document_id=d.source_document_id AND l.parser_version IS NULL;
