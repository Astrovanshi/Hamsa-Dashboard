-- Migration 0004: Append-only review decisions for ISIN identity candidates.
--
-- security_identifier_revision rows remain immutable after creation.
-- This table is the authoritative source for approval/rejection state.
-- recorded_at is the point-in-time visibility gate.

CREATE TABLE IF NOT EXISTS security_identifier_revision_review (
    review_id                   VARCHAR     PRIMARY KEY,
    identifier_revision_id      VARCHAR     NOT NULL
        REFERENCES security_identifier_revision(identifier_revision_id),
    review_status               VARCHAR     NOT NULL
        CHECK (review_status IN ('pending', 'approved', 'rejected')),
    recorded_at                 TIMESTAMPTZ NOT NULL,
    reviewed_by                 VARCHAR,
    reviewed_at                 TIMESTAMPTZ,
    evidence_source_document_id VARCHAR
        REFERENCES source_document_revision(source_document_id),
    evidence_locator            VARCHAR,
    rationale                   VARCHAR,
    supersedes_review_id        VARCHAR,
    UNIQUE (review_id, identifier_revision_id),
    UNIQUE (supersedes_review_id),
    FOREIGN KEY (supersedes_review_id, identifier_revision_id)
        REFERENCES security_identifier_revision_review(review_id, identifier_revision_id),
    CHECK (
        (review_status = 'pending'
            AND reviewed_by                 IS NULL
            AND reviewed_at                 IS NULL
            AND evidence_source_document_id IS NULL
            AND evidence_locator            IS NULL)
     OR (review_status = 'rejected'
            AND reviewed_by  IS NOT NULL
            AND reviewed_at  IS NOT NULL)
     OR (review_status = 'approved'
            AND reviewed_by                 IS NOT NULL
            AND reviewed_at                 IS NOT NULL
            AND evidence_source_document_id IS NOT NULL
            AND evidence_locator            IS NOT NULL
            AND length(evidence_locator)    > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_identifier_review_candidate
    ON security_identifier_revision_review (identifier_revision_id, recorded_at);

-- Backfill reviews from existing security_identifier_revision rows.
INSERT INTO security_identifier_revision_review (
    review_id,
    identifier_revision_id,
    review_status,
    recorded_at,
    reviewed_by,
    reviewed_at,
    evidence_source_document_id,
    evidence_locator,
    rationale,
    supersedes_review_id
)
SELECT
    'idrev-backfill-' || md5(identifier_revision_id),
    identifier_revision_id,
    CASE
        -- A legacy decision without a named reviewer and review timestamp
        -- cannot truthfully become an approved/rejected review event.
        -- Preserve the candidate but fail closed until it is reviewed again.
        WHEN mapping_review_status IN ('approved', 'rejected')
             AND reviewed_by IS NOT NULL
             AND reviewed_at IS NOT NULL
             AND extraction_locator IS NOT NULL
             AND length(extraction_locator) > 0
        THEN mapping_review_status
        ELSE 'pending'
    END,
    COALESCE(reviewed_at, extraction_timestamp, CURRENT_TIMESTAMP),
    CASE WHEN mapping_review_status IN ('approved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND extraction_locator IS NOT NULL AND length(extraction_locator) > 0 THEN reviewed_by ELSE NULL END,
    CASE WHEN mapping_review_status IN ('approved', 'rejected') AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND extraction_locator IS NOT NULL AND length(extraction_locator) > 0 THEN reviewed_at ELSE NULL END,
    CASE WHEN mapping_review_status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND extraction_locator IS NOT NULL AND length(extraction_locator) > 0 THEN source_document_id ELSE NULL END,
    CASE WHEN mapping_review_status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND extraction_locator IS NOT NULL AND length(extraction_locator) > 0 THEN extraction_locator ELSE NULL END,
    CASE WHEN mapping_review_status IN ('approved', 'rejected') AND (reviewed_by IS NULL OR reviewed_at IS NULL OR extraction_locator IS NULL OR length(extraction_locator) = 0)
         THEN 'Legacy decision lacks traceable reviewer, decision timestamp, or evidence locator; pending re-review required.'
         ELSE 'Backfill from security_identifier_revision migration v4'
    END,
    NULL
FROM security_identifier_revision
WHERE NOT EXISTS (
    SELECT 1 FROM security_identifier_revision_review r
    WHERE r.identifier_revision_id = security_identifier_revision.identifier_revision_id
);
