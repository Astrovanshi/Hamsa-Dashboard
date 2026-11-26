-- Migration 0009: Full-Universe Security Master Registry and Historical Coverage Tracking
DROP TABLE IF EXISTS security_historical_coverage;
DROP TABLE IF EXISTS security_universe_registry;

CREATE TABLE IF NOT EXISTS security_universe_registry (
    isin VARCHAR PRIMARY KEY,
    symbol VARCHAR NOT NULL,
    company_name VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL DEFAULT 'NSE',
    series VARCHAR NOT NULL DEFAULT 'EQ',
    operational_state VARCHAR NOT NULL CHECK (operational_state IN (
        'ELIGIBLE', 'MAPPING_PENDING', 'DATA_PENDING', 'HISTORY_BUILDING', 'RADAR_READY', 'DATA_ERROR', 'EXCLUDED'
    )),
    exclusion_reason VARCHAR,
    listing_date DATE,
    entity_id VARCHAR,
    security_id VARCHAR,
    listing_id VARCHAR,
    registered_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id)
);
CREATE INDEX IF NOT EXISTS idx_universe_registry_state ON security_universe_registry(operational_state);
CREATE INDEX IF NOT EXISTS idx_universe_registry_symbol ON security_universe_registry(symbol);

CREATE TABLE IF NOT EXISTS security_historical_coverage (
    isin VARCHAR PRIMARY KEY,
    first_eod_date DATE,
    latest_eod_date DATE,
    total_eod_sessions INTEGER NOT NULL DEFAULT 0,
    total_delivery_sessions INTEGER NOT NULL DEFAULT 0,
    delivery_coverage_pct DECIMAL(6,2) DEFAULT 0.0,
    rolling_20d_ready BOOLEAN NOT NULL DEFAULT FALSE,
    rolling_60d_ready BOOLEAN NOT NULL DEFAULT FALSE,
    avg_turnover_20d_cr DECIMAL(18,2) DEFAULT 0.0,
    liquidity_tier VARCHAR NOT NULL DEFAULT 'ILLIQUID' CHECK (liquidity_tier IN ('MEGA_LIQUID', 'HIGH_LIQUID', 'MID_LIQUID', 'LOW_LIQUID', 'ILLIQUID')),
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_coverage_readiness ON security_historical_coverage(rolling_20d_ready, liquidity_tier);