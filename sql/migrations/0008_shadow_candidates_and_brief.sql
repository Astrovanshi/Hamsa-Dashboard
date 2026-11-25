-- Migration 0008: Shadow Candidate Engine & Daily Market Intelligence Brief
-- Supports:
-- 1. shadow_candidate_evaluation: Record of every qualifying candidate evaluated under versioned experimental profiles
-- 2. daily_market_intelligence_brief: Persisted EOD market regime, breadth, absorption watch, and momentum briefings

CREATE TABLE IF NOT EXISTS shadow_candidate_evaluation (
    evaluation_id VARCHAR PRIMARY KEY,
    entity_id VARCHAR NOT NULL REFERENCES issuer_entity(entity_id),
    listing_id VARCHAR NOT NULL REFERENCES exchange_listing(listing_id),
    trade_date DATE NOT NULL,
    profile_version VARCHAR NOT NULL,
    is_qualifying BOOLEAN NOT NULL,
    primary_trigger VARCHAR NOT NULL,
    trigger_detail VARCHAR,
    volume_multiple DECIMAL(18,4),
    turnover_multiple DECIMAL(18,4),
    avg_turnover_20d_inr DECIMAL(28,4),
    delivery_percentage DECIMAL(8,4),
    delivery_chg_pp DECIMAL(8,4),
    drawdown_20d_pct DECIMAL(8,4),
    close_range_position DECIMAL(6,4),
    qualifying_flags_count INTEGER NOT NULL,
    supporting_measurements_json JSON,
    evaluated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_shadow_candidate_eval ON shadow_candidate_evaluation(listing_id, trade_date, profile_version);
CREATE INDEX IF NOT EXISTS idx_shadow_candidate_date_prof ON shadow_candidate_evaluation(trade_date, profile_version, is_qualifying);

CREATE TABLE IF NOT EXISTS daily_market_intelligence_brief (
    brief_id VARCHAR PRIMARY KEY,
    trade_date DATE NOT NULL UNIQUE,
    market_regime VARCHAR NOT NULL,
    breadth_ratio DECIMAL(8,4) NOT NULL,
    advancers_count INTEGER NOT NULL,
    decliners_count INTEGER NOT NULL,
    unchanged_count INTEGER NOT NULL,
    total_turnover_cr DECIMAL(18,2) NOT NULL,
    high_importance_events_json JSON,
    absorption_watch_json JSON,
    momentum_expansion_json JSON,
    new_shadow_candidates_json JSON,
    existing_candidate_updates_json JSON,
    system_health_summary_json JSON,
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_by VARCHAR NOT NULL DEFAULT 'hamsa-daily-pipeline'
);