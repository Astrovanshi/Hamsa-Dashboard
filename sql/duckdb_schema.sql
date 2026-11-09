-- HAMSA analytical schema. Append-only revisions; no market data is included.
CREATE TABLE IF NOT EXISTS schema_metadata (
    schema_name VARCHAR PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK (current_version >= 1),
    current_migration VARCHAR NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migration (
    migration_id VARCHAR PRIMARY KEY,
    from_version INTEGER NOT NULL,
    to_version INTEGER NOT NULL,
    migration_checksum_sha256 VARCHAR NOT NULL CHECK (length(migration_checksum_sha256) = 64),
    applied_at TIMESTAMPTZ NOT NULL,
    applied_by VARCHAR NOT NULL,
    UNIQUE (from_version, to_version),
    CHECK (to_version = from_version + 1)
);

INSERT INTO schema_metadata VALUES (
    'hamsa_analytics', 1, '0001_initial_analytics', CURRENT_TIMESTAMP
) ON CONFLICT (schema_name) DO NOTHING;

CREATE TABLE IF NOT EXISTS raw_source_file (
    source_file_id VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    original_filename VARCHAR NOT NULL,
    checksum_sha256 VARCHAR NOT NULL UNIQUE CHECK (length(checksum_sha256) = 64),
    archive_path VARCHAR NOT NULL UNIQUE,
    captured_at TIMESTAMPTZ NOT NULL,
    source_as_of_date DATE,
    license_review_reference VARCHAR NOT NULL,
    license_status VARCHAR NOT NULL CHECK (license_status IN ('approved', 'restricted', 'pending', 'rejected')),
    metadata_json JSON
);

CREATE TABLE IF NOT EXISTS source_document_revision (
    source_document_id VARCHAR PRIMARY KEY,
    provider VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    source_identifier VARCHAR NOT NULL,
    source_file_id VARCHAR NOT NULL REFERENCES raw_source_file(source_file_id),
    checksum_sha256 VARCHAR NOT NULL CHECK (length(checksum_sha256) = 64),
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    source_document_date DATE NOT NULL,
    publication_date DATE NOT NULL,
    published_at TIMESTAMPTZ,
    ingestion_timestamp TIMESTAMPTZ NOT NULL,
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    supersedes_source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    UNIQUE (provider, dataset, source_identifier, revision_number)
);

CREATE TABLE IF NOT EXISTS source_document_sighting (
    provider VARCHAR NOT NULL,
    dataset VARCHAR NOT NULL,
    source_identifier VARCHAR NOT NULL,
    checksum_sha256 VARCHAR NOT NULL CHECK (length(checksum_sha256) = 64),
    source_file_id VARCHAR NOT NULL REFERENCES raw_source_file(source_file_id),
    first_seen_at TIMESTAMPTZ NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    PRIMARY KEY (provider, dataset, source_identifier, checksum_sha256, source_file_id)
);

-- Registry is the typed FK target for lineage and screen-result sources.
CREATE TABLE IF NOT EXISTS normalized_observation_registry (
    observation_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type IN (
        'financial', 'eod_price', 'delivery', 'classification', 'corporate_action',
        'adjustment_factor', 'adjusted_price'
    )),
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    source_identifier VARCHAR,
    checksum_sha256 VARCHAR CHECK (checksum_sha256 IS NULL OR length(checksum_sha256) = 64),
    parser_version VARCHAR,
    extraction_timestamp TIMESTAMPTZ,
    extraction_locator VARCHAR,
    formula_version VARCHAR,
    UNIQUE (observation_id, observation_type),
    CHECK (
        (source_document_id IS NOT NULL AND source_identifier IS NOT NULL
            AND checksum_sha256 IS NOT NULL AND parser_version IS NOT NULL
            AND extraction_timestamp IS NOT NULL AND extraction_locator IS NOT NULL)
        OR (formula_version IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS observation_lineage_input (
    derived_observation_id VARCHAR NOT NULL,
    derived_observation_type VARCHAR NOT NULL,
    input_observation_id VARCHAR NOT NULL,
    input_observation_type VARCHAR NOT NULL,
    formula_version VARCHAR NOT NULL,
    PRIMARY KEY (derived_observation_id, input_observation_id, formula_version),
    FOREIGN KEY (derived_observation_id, derived_observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    FOREIGN KEY (input_observation_id, input_observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    CHECK (derived_observation_id <> input_observation_id)
);

-- Issuer, security, and exchange listing are different identity levels.
CREATE TABLE IF NOT EXISTS issuer_entity (
    entity_id VARCHAR PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS issuer_name_revision (
    name_revision_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    legal_name VARCHAR NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    supersedes_name_revision_id VARCHAR REFERENCES issuer_name_revision(name_revision_id)
);

CREATE TABLE IF NOT EXISTS issuer_classification_revision (
    classification_revision_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'classification'),
    entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    business_class VARCHAR NOT NULL CHECK (business_class IN ('financial', 'industrial', 'other', 'unclassified')),
    sector VARCHAR,
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    publication_date DATE NOT NULL,
    published_at TIMESTAMPTZ,
    ingestion_timestamp TIMESTAMPTZ NOT NULL,
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL CHECK (quality_status IN (
        'observed', 'missing', 'stale', 'invalid', 'conflicted', 'not_applicable'
    )),
    supersedes_classification_revision_id VARCHAR REFERENCES issuer_classification_revision(classification_revision_id),
    FOREIGN KEY (classification_revision_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS equity_security (
    security_id VARCHAR PRIMARY KEY,
    issuer_entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    share_class VARCHAR,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS security_identifier_revision (
    identifier_revision_id VARCHAR PRIMARY KEY,
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    identifier_type VARCHAR NOT NULL CHECK (identifier_type IN ('ISIN', 'OTHER')),
    identifier_value VARCHAR NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    mapping_review_status VARCHAR NOT NULL CHECK (mapping_review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMPTZ,
    supersedes_identifier_revision_id VARCHAR REFERENCES security_identifier_revision(identifier_revision_id),
    UNIQUE (identifier_type, identifier_value, effective_from)
);

CREATE TABLE IF NOT EXISTS entity_relationship_revision (
    relationship_id VARCHAR PRIMARY KEY,
    from_entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    to_entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    relationship_type VARCHAR NOT NULL CHECK (relationship_type IN (
        'same_legal_issuer_identifier_change', 'predecessor_of', 'successor_of',
        'merged_into', 'demerged_into', 'spun_out_to'
    )),
    effective_date DATE NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    review_status VARCHAR NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMPTZ,
    supersedes_relationship_id VARCHAR REFERENCES entity_relationship_revision(relationship_id),
    CHECK (from_entity_id <> to_entity_id)
);

CREATE TABLE IF NOT EXISTS security_relationship_revision (
    relationship_id VARCHAR PRIMARY KEY,
    from_security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    to_security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    relationship_type VARCHAR NOT NULL CHECK (relationship_type IN (
        'identifier_change', 'predecessor_of', 'successor_of', 'merged_into', 'demerged_into', 'spun_out_to'
    )),
    effective_date DATE NOT NULL,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    review_status VARCHAR NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewed_by VARCHAR,
    reviewed_at TIMESTAMPTZ,
    supersedes_relationship_id VARCHAR REFERENCES security_relationship_revision(relationship_id),
    CHECK (from_security_id <> to_security_id)
);

CREATE TABLE IF NOT EXISTS exchange_listing (
    listing_id VARCHAR PRIMARY KEY,
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    exchange_instrument_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS exchange_listing_revision (
    listing_revision_id VARCHAR PRIMARY KEY,
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    symbol VARCHAR NOT NULL,
    series VARCHAR,
    status VARCHAR NOT NULL CHECK (status IN ('active', 'suspended', 'delisted', 'relisted')),
    effective_from DATE NOT NULL,
    effective_to DATE,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    supersedes_listing_revision_id VARCHAR REFERENCES exchange_listing_revision(listing_revision_id)
);

CREATE TABLE IF NOT EXISTS exchange_trading_session (
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    session_date DATE NOT NULL,
    is_trading_session BOOLEAN NOT NULL,
    session_type VARCHAR NOT NULL CHECK (session_type IN ('regular', 'special', 'holiday')),
    calendar_version VARCHAR NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    PRIMARY KEY (exchange, session_date, calendar_version)
);

-- Canonical quantities: prices INR/share, turnover INR, quantities shares,
-- percentages percent points, ratios x, and durations days unless a metric
-- definition explicitly specifies otherwise.
CREATE TABLE IF NOT EXISTS canonical_unit (
    unit_code VARCHAR PRIMARY KEY,
    dimension VARCHAR NOT NULL,
    description VARCHAR NOT NULL
);
INSERT INTO canonical_unit VALUES
    ('INR_PER_SHARE', 'price', 'Indian rupees per share'),
    ('INR', 'currency', 'Indian rupees'),
    ('SHARES', 'quantity', 'Shares'),
    ('PERCENT', 'percentage', 'Percentage points from 0 to 100'),
    ('RATIO_X', 'ratio', 'Dimensionless multiple'),
    ('DAYS', 'duration', 'Calendar days')
ON CONFLICT (unit_code) DO NOTHING;

CREATE TABLE IF NOT EXISTS financial_metric_definition (
    metric VARCHAR PRIMARY KEY,
    canonical_unit VARCHAR NOT NULL REFERENCES canonical_unit(unit_code),
    dimension VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    definition_version VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS unit_conversion_rule_revision (
    conversion_rule_id VARCHAR PRIMARY KEY,
    source_unit VARCHAR NOT NULL,
    canonical_unit VARCHAR NOT NULL REFERENCES canonical_unit(unit_code),
    dimension VARCHAR NOT NULL,
    multiplier DECIMAL(38, 16) NOT NULL CHECK (multiplier > 0),
    additive_offset DECIMAL(38, 16) NOT NULL DEFAULT 0,
    rule_description VARCHAR NOT NULL,
    rule_version VARCHAR NOT NULL,
    review_status VARCHAR NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS observation_quarantine (
    quarantine_id VARCHAR PRIMARY KEY,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    source_locator VARCHAR NOT NULL,
    reason_code VARCHAR NOT NULL,
    detail VARCHAR NOT NULL,
    quarantined_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolution_reference VARCHAR
);

CREATE TABLE IF NOT EXISTS financial_observation_revision (
    observation_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'financial'),
    subject_entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    metric VARCHAR NOT NULL REFERENCES financial_metric_definition(metric),
    raw_value DECIMAL(38, 12),
    raw_unit VARCHAR,
    canonical_value DECIMAL(38, 12),
    canonical_unit VARCHAR NOT NULL REFERENCES canonical_unit(unit_code),
    conversion_rule_id VARCHAR REFERENCES unit_conversion_rule_revision(conversion_rule_id),
    period_start DATE,
    period_end DATE NOT NULL,
    source_document_date DATE NOT NULL,
    publication_date DATE NOT NULL,
    published_at TIMESTAMPTZ,
    publication_precision VARCHAR NOT NULL CHECK (publication_precision IN ('timestamp', 'date_only')),
    ingestion_timestamp TIMESTAMPTZ NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    as_reported_status VARCHAR NOT NULL CHECK (as_reported_status IN (
        'original', 'restatement', 'recast', 'provider_backfill'
    )),
    quality_status VARCHAR NOT NULL CHECK (quality_status IN (
        'observed', 'missing', 'stale', 'invalid', 'conflicted', 'not_applicable'
    )),
    quality_reason VARCHAR,
    reporting_scope VARCHAR NOT NULL CHECK (reporting_scope IN ('standalone', 'consolidated', 'not_applicable')),
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    formula_version VARCHAR,
    supersedes_observation_id VARCHAR REFERENCES financial_observation_revision(observation_id),
    CHECK ((publication_precision = 'timestamp' AND published_at IS NOT NULL)
        OR (publication_precision = 'date_only' AND published_at IS NULL)),
    CHECK ((quality_status IN ('missing', 'not_applicable') AND canonical_value IS NULL)
        OR quality_status NOT IN ('missing', 'not_applicable')),
    CHECK (quality_status <> 'observed' OR canonical_value IS NOT NULL),
    FOREIGN KEY (observation_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    CHECK (period_start IS NULL OR period_start <= period_end)
);

CREATE TABLE IF NOT EXISTS metric_staleness_policy_revision (
    metric VARCHAR NOT NULL REFERENCES financial_metric_definition(metric),
    source VARCHAR NOT NULL,
    max_age_days INTEGER NOT NULL CHECK (max_age_days >= 0),
    policy_version VARCHAR NOT NULL,
    effective_from DATE NOT NULL,
    PRIMARY KEY (metric, source, policy_version)
);

-- Original prices and delivery remain venue-specific, append-only observations.
CREATE TABLE IF NOT EXISTS eod_price_observation_revision (
    observation_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'eod_price'),
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    trade_date DATE NOT NULL,
    open_raw DECIMAL(28, 10),
    high_raw DECIMAL(28, 10),
    low_raw DECIMAL(28, 10),
    close_raw DECIMAL(28, 10),
    price_unit VARCHAR NOT NULL DEFAULT 'INR_PER_SHARE' REFERENCES canonical_unit(unit_code),
    volume_raw DECIMAL(38, 8),
    volume_unit VARCHAR NOT NULL DEFAULT 'SHARES' REFERENCES canonical_unit(unit_code),
    turnover_raw DECIMAL(38, 8),
    turnover_unit VARCHAR NOT NULL DEFAULT 'INR' REFERENCES canonical_unit(unit_code),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    source_identifier VARCHAR NOT NULL,
    checksum_sha256 VARCHAR NOT NULL CHECK (length(checksum_sha256) = 64),
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL CHECK (quality_status IN (
        'observed', 'missing', 'stale', 'invalid', 'conflicted', 'not_applicable'
    )),
    quality_reason VARCHAR,
    supersedes_observation_id VARCHAR REFERENCES eod_price_observation_revision(observation_id),
    CHECK (high_raw IS NULL OR low_raw IS NULL OR high_raw >= low_raw),
    CHECK (volume_raw IS NULL OR volume_raw >= 0),
    CHECK (turnover_raw IS NULL OR turnover_raw >= 0),
    CHECK (quality_status <> 'observed' OR close_raw IS NOT NULL),
    FOREIGN KEY (observation_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS delivery_observation_revision (
    observation_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'delivery'),
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    trade_date DATE NOT NULL,
    delivery_quantity_raw DECIMAL(38, 8),
    traded_quantity_raw DECIMAL(38, 8),
    delivery_percentage_raw DECIMAL(18, 8),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    parser_version VARCHAR NOT NULL,
    extraction_timestamp TIMESTAMPTZ NOT NULL,
    extraction_locator VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL CHECK (quality_status IN (
        'observed', 'missing', 'stale', 'invalid', 'conflicted', 'not_applicable'
    )),
    supersedes_observation_id VARCHAR REFERENCES delivery_observation_revision(observation_id),
    FOREIGN KEY (observation_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type),
    CHECK (delivery_percentage_raw IS NULL OR (delivery_percentage_raw >= 0 AND delivery_percentage_raw <= 100))
);

CREATE TABLE IF NOT EXISTS corporate_action_event_revision (
    event_revision_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'corporate_action'),
    event_id VARCHAR NOT NULL,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    action_type VARCHAR NOT NULL CHECK (action_type IN (
        'split', 'bonus', 'rights', 'merger', 'demerger', 'symbol_change',
        'isin_change', 'suspension', 'delisting', 'relisting'
    )),
    affected_security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    resulting_security_id VARCHAR REFERENCES equity_security(security_id),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    publication_date DATE NOT NULL,
    published_at TIMESTAMPTZ,
    source_document_date DATE NOT NULL,
    ex_date DATE,
    record_date DATE,
    effective_date DATE,
    terms_complete BOOLEAN NOT NULL,
    terms_json JSON NOT NULL,
    supersedes_event_revision_id VARCHAR REFERENCES corporate_action_event_revision(event_revision_id),
    UNIQUE (event_id, revision_number),
    CHECK (affected_security_id <> resulting_security_id OR resulting_security_id IS NULL),
    FOREIGN KEY (event_revision_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS adjustment_factor_revision (
    factor_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'adjustment_factor'),
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    event_revision_id VARCHAR NOT NULL REFERENCES corporate_action_event_revision(event_revision_id),
    effective_date DATE NOT NULL,
    price_factor DECIMAL(38, 16) NOT NULL CHECK (price_factor > 0),
    volume_factor DECIMAL(38, 16) NOT NULL CHECK (volume_factor > 0),
    factor_version VARCHAR NOT NULL,
    formula_version VARCHAR NOT NULL,
    methodology_review_status VARCHAR NOT NULL CHECK (methodology_review_status = 'approved'),
    terms_complete BOOLEAN NOT NULL CHECK (terms_complete = TRUE),
    publication_date DATE NOT NULL,
    publication_precision VARCHAR NOT NULL CHECK (publication_precision IN ('timestamp', 'date_only')),
    publicly_available_at TIMESTAMPTZ,
    public_availability_session DATE NOT NULL,
    availability_calendar_version VARCHAR NOT NULL,
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    created_at TIMESTAMPTZ NOT NULL,
    created_by VARCHAR NOT NULL,
    UNIQUE (security_id, event_revision_id, factor_version),
    CHECK ((publication_precision = 'timestamp' AND publicly_available_at IS NOT NULL)
        OR (publication_precision = 'date_only' AND publicly_available_at IS NULL)),
    FOREIGN KEY (factor_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS adjustment_factor_input_price (
    factor_id VARCHAR NOT NULL REFERENCES adjustment_factor_revision(factor_id),
    input_observation_id VARCHAR NOT NULL REFERENCES eod_price_observation_revision(observation_id),
    formula_version VARCHAR NOT NULL,
    PRIMARY KEY (factor_id, input_observation_id)
);

CREATE TABLE IF NOT EXISTS adjusted_price_series_revision (
    series_id VARCHAR PRIMARY KEY,
    security_id VARCHAR NOT NULL REFERENCES equity_security(security_id),
    basis_date DATE NOT NULL,
    factor_set_version VARCHAR NOT NULL,
    availability_mode VARCHAR NOT NULL CHECK (availability_mode IN ('public_as_of', 'hamsa_known_as_of', 'retrospective')),
    as_of_cutoff TIMESTAMPTZ NOT NULL,
    formula_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS adjusted_price_factor_input (
    series_id VARCHAR NOT NULL REFERENCES adjusted_price_series_revision(series_id),
    factor_id VARCHAR NOT NULL REFERENCES adjustment_factor_revision(factor_id),
    PRIMARY KEY (series_id, factor_id)
);

CREATE TABLE IF NOT EXISTS adjusted_price_point (
    observation_id VARCHAR PRIMARY KEY,
    observation_type VARCHAR NOT NULL CHECK (observation_type = 'adjusted_price'),
    series_id VARCHAR NOT NULL REFERENCES adjusted_price_series_revision(series_id),
    raw_observation_id VARCHAR NOT NULL REFERENCES eod_price_observation_revision(observation_id),
    adjusted_open DECIMAL(38, 16),
    adjusted_high DECIMAL(38, 16),
    adjusted_low DECIMAL(38, 16),
    adjusted_close DECIMAL(38, 16),
    adjusted_volume DECIMAL(38, 16),
    formula_version VARCHAR NOT NULL,
    UNIQUE (series_id, raw_observation_id),
    FOREIGN KEY (observation_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS venue_policy_revision (
    policy_id VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    primary_exchange VARCHAR NOT NULL CHECK (primary_exchange IN ('NSE', 'BSE')),
    fallback_exchange VARCHAR CHECK (fallback_exchange IN ('NSE', 'BSE')),
    combined_activity_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    combined_activity_rule VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    created_by VARCHAR NOT NULL,
    PRIMARY KEY (policy_id, version),
    CHECK (fallback_exchange IS NULL OR fallback_exchange <> primary_exchange),
    CHECK (combined_activity_allowed = FALSE OR combined_activity_rule IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS screen_profile_revision (
    profile_id VARCHAR NOT NULL,
    version VARCHAR NOT NULL,
    business_class VARCHAR NOT NULL CHECK (business_class IN ('financial', 'industrial')),
    engine VARCHAR NOT NULL CHECK (engine IN ('compounders', 'earnings_inflection', 'capex_conversion', 'cash_quality', 'extreme_sell_side_liquidity')),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    configuration_json JSON NOT NULL,
    venue_policy_id VARCHAR NOT NULL,
    venue_policy_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    created_by VARCHAR NOT NULL,
    PRIMARY KEY (profile_id, version, engine),
    FOREIGN KEY (venue_policy_id, venue_policy_version) REFERENCES venue_policy_revision(policy_id, version)
);

CREATE TABLE IF NOT EXISTS screen_run (
    run_id VARCHAR PRIMARY KEY,
    engine VARCHAR NOT NULL,
    profile_id VARCHAR NOT NULL,
    profile_version VARCHAR NOT NULL,
    as_of_session DATE NOT NULL,
    cutoff TIMESTAMPTZ NOT NULL,
    availability_mode VARCHAR NOT NULL CHECK (availability_mode IN ('public_as_of', 'hamsa_known_as_of')),
    exchange_calendar_version VARCHAR NOT NULL,
    code_version VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (profile_id, profile_version, engine)
        REFERENCES screen_profile_revision(profile_id, version, engine)
);

CREATE TABLE IF NOT EXISTS screen_result (
    result_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL REFERENCES screen_run(run_id),
    subject_entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    calculation_expression VARCHAR NOT NULL,
    evaluated_inputs_json JSON NOT NULL,
    result VARCHAR NOT NULL,
    explanation VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS screen_result_source_document (
    result_id VARCHAR NOT NULL REFERENCES screen_result(result_id),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    PRIMARY KEY (result_id, source_document_id)
);

CREATE TABLE IF NOT EXISTS screen_result_source_observation (
    result_id VARCHAR NOT NULL REFERENCES screen_result(result_id),
    observation_id VARCHAR NOT NULL,
    observation_type VARCHAR NOT NULL,
    PRIMARY KEY (result_id, observation_id, observation_type),
    FOREIGN KEY (observation_id, observation_type)
        REFERENCES normalized_observation_registry(observation_id, observation_type)
);

CREATE TABLE IF NOT EXISTS filter_review (
    review_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    filter_key VARCHAR NOT NULL CHECK (filter_key IN (
        'gap', 'choke_point', 'turbo', 'real_buyers', 'stack', 'trigger',
        'jockey', 'thin_float', 'ceiling', 'what_kills_it', 'extreme_liquidity'
    )),
    status VARCHAR NOT NULL CHECK (status IN ('Pass', 'Unproven', 'Fail')),
    reviewer VARCHAR NOT NULL,
    reviewed_at TIMESTAMPTZ NOT NULL,
    rationale VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS filter_review_evidence (
    review_id VARCHAR NOT NULL REFERENCES filter_review(review_id),
    source_document_id VARCHAR NOT NULL REFERENCES source_document_revision(source_document_id),
    locator VARCHAR NOT NULL,
    note VARCHAR NOT NULL,
    PRIMARY KEY (review_id, source_document_id, locator)
);

-- Single-column ART indexes are reserved for highly selective lookups.
CREATE INDEX IF NOT EXISTS idx_security_identifier_value
    ON security_identifier_revision (identifier_value);
CREATE INDEX IF NOT EXISTS idx_source_document_identifier
    ON source_document_revision (source_identifier);
CREATE INDEX IF NOT EXISTS idx_financial_subject_entity
    ON financial_observation_revision (subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_eod_price_security
    ON eod_price_observation_revision (security_id);
