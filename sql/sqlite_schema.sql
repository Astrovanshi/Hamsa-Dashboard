-- Local app metadata and append-only human dossier review ledger.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filter_review (
    review_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    filter_key TEXT NOT NULL CHECK (filter_key IN (
        'gap', 'choke_point', 'turbo', 'real_buyers', 'stack', 'trigger',
        'jockey', 'thin_float', 'ceiling', 'what_kills_it', 'extreme_liquidity'
    )),
    status TEXT NOT NULL CHECK (status IN ('Pass', 'Unproven', 'Fail')),
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    rationale TEXT NOT NULL,
    supersedes_review_id TEXT REFERENCES filter_review(review_id)
);

CREATE TABLE IF NOT EXISTS filter_review_evidence (
    review_id TEXT NOT NULL REFERENCES filter_review(review_id),
    source_document_id TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),
    locator TEXT NOT NULL,
    note TEXT NOT NULL,
    PRIMARY KEY (review_id, source_document_id, locator)
);

CREATE INDEX IF NOT EXISTS idx_filter_review_entity_time
    ON filter_review (entity_id, reviewed_at);

-- Prevent edits/deletes of review history; corrections append a new review.
CREATE TRIGGER IF NOT EXISTS filter_review_no_update
BEFORE UPDATE ON filter_review
BEGIN
    SELECT RAISE(ABORT, 'filter reviews are append-only');
END;

CREATE TRIGGER IF NOT EXISTS filter_review_no_delete
BEFORE DELETE ON filter_review
BEGIN
    SELECT RAISE(ABORT, 'filter reviews are append-only');
END;

CREATE TRIGGER IF NOT EXISTS filter_review_evidence_no_update
BEFORE UPDATE ON filter_review_evidence
BEGIN
    SELECT RAISE(ABORT, 'filter evidence is append-only');
END;

CREATE TRIGGER IF NOT EXISTS filter_review_evidence_no_delete
BEFORE DELETE ON filter_review_evidence
BEGIN
    SELECT RAISE(ABORT, 'filter evidence is append-only');
END;
