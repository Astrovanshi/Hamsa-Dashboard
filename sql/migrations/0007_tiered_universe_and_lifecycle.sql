-- Migration 0007: Tiered Universe Architecture & Company Intelligence Lifecycle
-- Supports:
-- Tier 1: RADAR (Entire eligible market, continuous daily price/delivery & behavioral radar signals)
-- Tier 2: CANDIDATE (Configurable behavioral trigger admission for selective fundamental intelligence)
-- Tier 3: INVESTIGATION (Deep asymmetric human research & HAMSA 11)
-- Plus WATCH and ARCHIVED lifecycle states with automatic re-entry and complete audit transition history.

-- 1. Company Intelligence Lifecycle Event History (Append-Only)
CREATE TABLE IF NOT EXISTS company_intelligence_lifecycle_event (
    event_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    previous_tier VARCHAR NOT NULL CHECK (previous_tier IN ('NONE', 'RADAR', 'CANDIDATE', 'INVESTIGATION', 'WATCH', 'ARCHIVED')),
    new_tier VARCHAR NOT NULL CHECK (new_tier IN ('RADAR', 'CANDIDATE', 'INVESTIGATION', 'WATCH', 'ARCHIVED')),
    transition_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    transition_type VARCHAR NOT NULL CHECK (transition_type IN ('automated_signal', 'human_review', 'system_initialization', 'decay_demotion', 're_entry')),
    primary_trigger VARCHAR NOT NULL,
    trigger_detail VARCHAR,
    supporting_signals_json JSON,
    recorded_by VARCHAR NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id)
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_entity_time ON company_intelligence_lifecycle_event(entity_id, transition_timestamp);

-- 2. Daily Radar Behavioral Signals Table
-- Stores deterministic price/volume/delivery/breakout/dislocation signals across the eligible universe
CREATE TABLE IF NOT EXISTS security_radar_signal_daily (
    signal_id VARCHAR PRIMARY KEY,
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    trade_date DATE NOT NULL,
    exchange VARCHAR NOT NULL CHECK (exchange IN ('NSE', 'BSE')),
    volume_multiple DECIMAL(18,4),
    turnover_multiple DECIMAL(18,4),
    avg_turnover_20d_inr DECIMAL(28,4),
    delivery_percentage DECIMAL(8,4),
    delivery_chg_pp DECIMAL(8,4),
    session_return_pct DECIMAL(8,4),
    drawdown_20d_pct DECIMAL(8,4),
    close_range_position DECIMAL(6,4),
    is_52w_high BOOLEAN DEFAULT FALSE,
    is_52w_low BOOLEAN DEFAULT FALSE,
    is_range_expansion BOOLEAN DEFAULT FALSE,
    is_breakout BOOLEAN DEFAULT FALSE,
    is_volume_dislocation BOOLEAN DEFAULT FALSE,
    is_delivery_surge BOOLEAN DEFAULT FALSE,
    is_extreme_sell_side BOOLEAN DEFAULT FALSE,
    composite_radar_flags_json JSON,
    calculated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_radar_signal_listing_date ON security_radar_signal_daily(listing_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_radar_signal_date_flags ON security_radar_signal_daily(trade_date, is_volume_dislocation, is_delivery_surge);

-- 3. Candidate Admission Rule Configurations
CREATE TABLE IF NOT EXISTS candidate_admission_rule_revision (
    rule_revision_id VARCHAR PRIMARY KEY,
    rule_name VARCHAR NOT NULL,
    rule_version VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    volume_multiple_min DECIMAL(8,4),
    delivery_chg_pp_min DECIMAL(8,4),
    turnover_cr_min DECIMAL(18,4),
    session_drawdown_max_pct DECIMAL(8,4),
    required_concurrent_flags INTEGER NOT NULL DEFAULT 1,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by VARCHAR NOT NULL,
    rationale VARCHAR NOT NULL
);

-- Seed initial standard candidate admission rule
INSERT OR IGNORE INTO candidate_admission_rule_revision (
    rule_revision_id, rule_name, rule_version, is_active,
    volume_multiple_min, delivery_chg_pp_min, turnover_cr_min, session_drawdown_max_pct,
    required_concurrent_flags, effective_from, effective_to, created_at, created_by, rationale
) VALUES (
    'rule-candidate-v1',
    'Standard Market Dislocation & Behavioral Candidate Admission',
    'v1.0',
    TRUE,
    1.5000,
    5.0000,
    10.0000,
    -5.0000,
    1,
    '2015-01-01',
    NULL,
    '2026-11-24 20:39:06+00',
    'hamsa-system',
    'Admits equities with >=1.5x 20D volume, >=5pp delivery expansion, or extreme sell-side absorption into Tier 2 candidate intelligence'
);