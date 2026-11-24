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

-- Additive local company-research workflow. Events are append-only; latest
-- state is selected from the un-superseded leaf, never overwritten in place.
CREATE TABLE IF NOT EXISTS research_watchlist_revision (
    revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('watch', 'research_priority', 'cooling', 'rejected')),
    reviewer TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    rationale TEXT NOT NULL,
    supersedes_revision_id TEXT UNIQUE REFERENCES research_watchlist_revision(revision_id)
);
CREATE INDEX IF NOT EXISTS idx_watchlist_entity_time ON research_watchlist_revision(entity_id, recorded_at);

CREATE TABLE IF NOT EXISTS company_research_note_revision (
    note_revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    business_thesis TEXT NOT NULL,
    thesis_killers TEXT NOT NULL,
    next_review_date TEXT,
    reviewer TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    supersedes_note_revision_id TEXT UNIQUE REFERENCES company_research_note_revision(note_revision_id)
);
CREATE INDEX IF NOT EXISTS idx_research_note_entity_time ON company_research_note_revision(entity_id, recorded_at);

CREATE TABLE IF NOT EXISTS company_research_note_evidence (
    note_revision_id TEXT NOT NULL REFERENCES company_research_note_revision(note_revision_id),
    source_document_id TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL CHECK (length(checksum_sha256) = 64),
    locator TEXT NOT NULL,
    note TEXT NOT NULL,
    PRIMARY KEY (note_revision_id, source_document_id, locator)
);

CREATE TABLE IF NOT EXISTS issuer_business_classification_review_revision (
    review_revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    business_class TEXT NOT NULL CHECK (business_class IN ('financial', 'industrial')),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('approved', 'rejected')),
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_source_document_id TEXT NOT NULL,
    evidence_source_identifier TEXT NOT NULL,
    evidence_checksum_sha256 TEXT NOT NULL CHECK (length(evidence_checksum_sha256) = 64),
    evidence_locator TEXT NOT NULL,
    supersedes_review_revision_id TEXT UNIQUE REFERENCES issuer_business_classification_review_revision(review_revision_id),
    CHECK (valid_to IS NULL OR valid_from <= valid_to)
);
CREATE INDEX IF NOT EXISTS idx_business_class_review_entity ON issuer_business_classification_review_revision(entity_id, recorded_at);

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

CREATE TRIGGER IF NOT EXISTS watchlist_no_update BEFORE UPDATE ON research_watchlist_revision
BEGIN SELECT RAISE(ABORT, 'watchlist history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS watchlist_no_delete BEFORE DELETE ON research_watchlist_revision
BEGIN SELECT RAISE(ABORT, 'watchlist history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS research_note_no_update BEFORE UPDATE ON company_research_note_revision
BEGIN SELECT RAISE(ABORT, 'company research notes are append-only'); END;
CREATE TRIGGER IF NOT EXISTS research_note_no_delete BEFORE DELETE ON company_research_note_revision
BEGIN SELECT RAISE(ABORT, 'company research notes are append-only'); END;
CREATE TRIGGER IF NOT EXISTS research_evidence_no_update BEFORE UPDATE ON company_research_note_evidence
BEGIN SELECT RAISE(ABORT, 'company research evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS research_evidence_no_delete BEFORE DELETE ON company_research_note_evidence
BEGIN SELECT RAISE(ABORT, 'company research evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS business_class_review_no_update BEFORE UPDATE ON issuer_business_classification_review_revision
BEGIN SELECT RAISE(ABORT, 'business classification reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS business_class_review_no_delete BEFORE DELETE ON issuer_business_classification_review_revision
BEGIN SELECT RAISE(ABORT, 'business classification reviews are append-only'); END;

CREATE TABLE IF NOT EXISTS engine_evidence_review_revision (
    review_revision_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    evidence_key TEXT NOT NULL CHECK (evidence_key IN (
        'commissioning', 'demand', 'customer_evidence',
        'documented_expansion', 'forced_selling', 'absorption_capacity'
    )),
    review_status TEXT NOT NULL CHECK (review_status IN ('approved', 'rejected', 'unproven')),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_source_document_id TEXT,
    evidence_source_identifier TEXT,
    evidence_checksum_sha256 TEXT CHECK (evidence_checksum_sha256 IS NULL OR length(evidence_checksum_sha256) = 64),
    evidence_locator TEXT,
    supersedes_review_revision_id TEXT UNIQUE REFERENCES engine_evidence_review_revision(review_revision_id),
    CHECK (valid_to IS NULL OR valid_from <= valid_to),
    CHECK (
        (review_status IN ('approved', 'rejected')
            AND evidence_source_document_id IS NOT NULL
            AND evidence_source_identifier IS NOT NULL
            AND evidence_checksum_sha256 IS NOT NULL
            AND evidence_locator IS NOT NULL
            AND length(evidence_locator) > 0)
        OR review_status = 'unproven'
    )
);
CREATE INDEX IF NOT EXISTS idx_engine_evidence_review_entity
    ON engine_evidence_review_revision(entity_id, evidence_key, recorded_at);

CREATE TRIGGER IF NOT EXISTS engine_evidence_review_no_update BEFORE UPDATE ON engine_evidence_review_revision
BEGIN SELECT RAISE(ABORT, 'engine evidence reviews are append-only'); END;
CREATE TRIGGER IF NOT EXISTS engine_evidence_review_no_delete BEFORE DELETE ON engine_evidence_review_revision
BEGIN SELECT RAISE(ABORT, 'engine evidence reviews are append-only'); END;
