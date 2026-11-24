CREATE TABLE listing_classification_snapshot (
    listing_classification_snapshot_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'classification'),
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    source_snapshot_date DATE NOT NULL,
    raw_exchange_instrument_id VARCHAR,
    raw_isin VARCHAR,
    raw_symbol VARCHAR,
    raw_series VARCHAR,
    raw_listing_status VARCHAR,
    raw_instrument_class_value VARCHAR,
    raw_platform_class_value VARCHAR,
    source_fields_json JSON NOT NULL,
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    supersedes_snapshot_id VARCHAR,
    UNIQUE (listing_classification_snapshot_id, listing_id),
    UNIQUE (listing_id, source_document_id, extraction_locator),
    FOREIGN KEY (listing_classification_snapshot_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    FOREIGN KEY (supersedes_snapshot_id, listing_id)
        REFERENCES listing_classification_snapshot(listing_classification_snapshot_id, listing_id)
);

CREATE TABLE listing_classification_review_revision (
    classification_review_revision_id VARCHAR PRIMARY KEY,
    listing_classification_snapshot_id VARCHAR NOT NULL,
    listing_id VARCHAR NOT NULL,
    recorded_by VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    rationale VARCHAR NOT NULL,

    instrument_review_status VARCHAR NOT NULL
        CHECK (instrument_review_status IN ('pending', 'approved', 'rejected')),
    instrument_class VARCHAR CHECK (instrument_class IN (
        'ordinary_equity', 'etf', 'mutual_fund', 'reit', 'invit', 'preference',
        'warrant', 'rights', 'debt', 'other', 'unknown'
    )),
    instrument_valid_from DATE,
    instrument_valid_to DATE,
    instrument_evidence_source_document_id VARCHAR
        REFERENCES source_document_revision(source_document_id),
    instrument_evidence_locator VARCHAR,
    instrument_reviewed_by VARCHAR,
    instrument_reviewed_at TIMESTAMPTZ,

    platform_review_status VARCHAR NOT NULL
        CHECK (platform_review_status IN ('pending', 'approved', 'rejected')),
    platform_class VARCHAR CHECK (platform_class IN ('mainboard', 'sme', 'other_platform', 'unknown')),
    platform_valid_from DATE,
    platform_valid_to DATE,
    platform_evidence_source_document_id VARCHAR
        REFERENCES source_document_revision(source_document_id),
    platform_evidence_locator VARCHAR,
    platform_reviewed_by VARCHAR,
    platform_reviewed_at TIMESTAMPTZ,

    supersedes_review_revision_id VARCHAR,
    UNIQUE (classification_review_revision_id, listing_classification_snapshot_id, listing_id),
    UNIQUE (supersedes_review_revision_id),
    FOREIGN KEY (listing_classification_snapshot_id, listing_id)
        REFERENCES listing_classification_snapshot(listing_classification_snapshot_id, listing_id),
    FOREIGN KEY (supersedes_review_revision_id, listing_classification_snapshot_id, listing_id)
        REFERENCES listing_classification_review_revision(
            classification_review_revision_id, listing_classification_snapshot_id, listing_id
        ),
    CHECK (instrument_valid_to IS NULL OR instrument_valid_from IS NULL
        OR instrument_valid_from <= instrument_valid_to),
    CHECK (platform_valid_to IS NULL OR platform_valid_from IS NULL
        OR platform_valid_from <= platform_valid_to),
    CHECK (
        (instrument_review_status = 'approved'
            AND instrument_class IS NOT NULL AND instrument_valid_from IS NOT NULL
            AND instrument_evidence_source_document_id IS NOT NULL
            AND instrument_evidence_locator IS NOT NULL AND length(instrument_evidence_locator) > 0
            AND instrument_reviewed_by IS NOT NULL AND instrument_reviewed_at IS NOT NULL)
        OR (instrument_review_status = 'pending'
            AND instrument_valid_from IS NULL AND instrument_valid_to IS NULL
            AND instrument_evidence_source_document_id IS NULL AND instrument_evidence_locator IS NULL
            AND instrument_reviewed_by IS NULL AND instrument_reviewed_at IS NULL)
        OR (instrument_review_status = 'rejected'
            AND instrument_valid_from IS NULL AND instrument_valid_to IS NULL
            AND instrument_reviewed_by IS NOT NULL AND instrument_reviewed_at IS NOT NULL)
    ),
    CHECK (
        (platform_review_status = 'approved'
            AND platform_class IS NOT NULL AND platform_valid_from IS NOT NULL
            AND platform_evidence_source_document_id IS NOT NULL
            AND platform_evidence_locator IS NOT NULL AND length(platform_evidence_locator) > 0
            AND platform_reviewed_by IS NOT NULL AND platform_reviewed_at IS NOT NULL)
        OR (platform_review_status = 'pending'
            AND platform_valid_from IS NULL AND platform_valid_to IS NULL
            AND platform_evidence_source_document_id IS NULL AND platform_evidence_locator IS NULL
            AND platform_reviewed_by IS NULL AND platform_reviewed_at IS NULL)
        OR (platform_review_status = 'rejected'
            AND platform_valid_from IS NULL AND platform_valid_to IS NULL
            AND platform_reviewed_by IS NOT NULL AND platform_reviewed_at IS NOT NULL)
    )
);

CREATE TABLE exchange_listing_revision_review (
    listing_revision_review_id VARCHAR PRIMARY KEY,
    listing_revision_id VARCHAR NOT NULL REFERENCES exchange_listing_revision(listing_revision_id),
    review_status VARCHAR NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    recorded_by VARCHAR NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMPTZ,
    evidence_source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    evidence_locator VARCHAR,
    rationale VARCHAR NOT NULL,
    supersedes_review_id VARCHAR,
    UNIQUE (listing_revision_review_id, listing_revision_id),
    UNIQUE (supersedes_review_id),
    FOREIGN KEY (supersedes_review_id, listing_revision_id)
        REFERENCES exchange_listing_revision_review(listing_revision_review_id, listing_revision_id),
    CHECK (
        (review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL
            AND evidence_source_document_id IS NULL AND evidence_locator IS NULL)
        OR (review_status = 'rejected' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)
        OR (review_status = 'approved' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL
            AND evidence_source_document_id IS NOT NULL
            AND evidence_locator IS NOT NULL AND length(evidence_locator) > 0)
    )
);

CREATE TABLE eod_observation_reconciliation (
    reconciliation_id VARCHAR PRIMARY KEY,
    comparison_stream_id VARCHAR NOT NULL,
    comparator_version VARCHAR NOT NULL,
    official_observation_id VARCHAR REFERENCES eod_price_observation_revision(observation_id),
    secondary_observation_id VARCHAR REFERENCES eod_price_observation_revision(observation_id),
    match_status VARCHAR NOT NULL CHECK (match_status IN (
        'matched', 'unmatched_official', 'unmatched_secondary'
    )),
    comparison_outcome VARCHAR NOT NULL CHECK (comparison_outcome IN (
        'exact_match', 'discrepancy', 'not_compared'
    )),
    compared_fields_json JSON,
    differences_json JSON,
    not_compared_reason_code VARCHAR,
    compared_at TIMESTAMPTZ NOT NULL,
    supersedes_reconciliation_id VARCHAR,
    UNIQUE (reconciliation_id, comparison_stream_id),
    UNIQUE (supersedes_reconciliation_id),
    FOREIGN KEY (supersedes_reconciliation_id, comparison_stream_id)
        REFERENCES eod_observation_reconciliation(reconciliation_id, comparison_stream_id),
    CHECK (
        (match_status = 'matched' AND official_observation_id IS NOT NULL
            AND secondary_observation_id IS NOT NULL
            AND official_observation_id <> secondary_observation_id)
        OR (match_status = 'unmatched_official' AND official_observation_id IS NOT NULL
            AND secondary_observation_id IS NULL)
        OR (match_status = 'unmatched_secondary' AND official_observation_id IS NULL
            AND secondary_observation_id IS NOT NULL)
    ),
    CHECK (
        (comparison_outcome IN ('exact_match', 'discrepancy') AND match_status = 'matched'
            AND compared_fields_json IS NOT NULL AND differences_json IS NOT NULL
            AND not_compared_reason_code IS NULL)
        OR (comparison_outcome = 'not_compared' AND compared_fields_json IS NULL
            AND differences_json IS NULL AND not_compared_reason_code IS NOT NULL)
    ),
    CHECK (comparison_outcome <> 'exact_match' OR match_status = 'matched'),
    CHECK (comparison_outcome <> 'discrepancy' OR match_status = 'matched')
);

CREATE INDEX listing_classification_snapshot_listing_date_idx
    ON listing_classification_snapshot(listing_id, source_snapshot_date);
CREATE INDEX listing_classification_review_target_idx
    ON listing_classification_review_revision(listing_id, recorded_at);
CREATE INDEX listing_revision_review_target_idx
    ON exchange_listing_revision_review(listing_revision_id, recorded_at);
CREATE INDEX eod_reconciliation_stream_idx
    ON eod_observation_reconciliation(comparison_stream_id, compared_at);
CREATE INDEX eod_reconciliation_official_idx
    ON eod_observation_reconciliation(official_observation_id);
CREATE INDEX eod_reconciliation_secondary_idx
    ON eod_observation_reconciliation(secondary_observation_id);
