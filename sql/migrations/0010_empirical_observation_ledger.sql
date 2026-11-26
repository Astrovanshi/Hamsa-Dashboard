-- Migration 0010: Phase II Empirical Market Event Observation Ledger & Outcome Tracking
-- Supports:
-- 1. market_event_observation_ledger: Durable append-only record of detected anomalies across market sessions
-- 2. market_event_outcome_tracking: Forward outcome measurements (1D, 3D, 5D, 10D, 20D, 60D) with MFE/MAE and status
-- 3. market_event_research_journal: Chronological research journal documenting observation, evidence, hypothesis, counterevidence, confidence, next test

CREATE TABLE IF NOT EXISTS market_event_observation_ledger (
    event_id VARCHAR PRIMARY KEY,
    isin VARCHAR NOT NULL REFERENCES security_universe_registry(isin),
    symbol VARCHAR NOT NULL,
    company_name VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    event_type VARCHAR NOT NULL CHECK (event_type IN (
        'VOLUME_SURGE', 'DELIVERY_EXPANSION', 'DUAL_SURGE', 'SUPPLY_ABSORPTION',
        'RANGE_BREAKOUT', 'RANGE_COMPRESSION', '52W_HIGH_MOMENTUM', 'DRAWDOWN_LIQUIDITY'
    )),
    detector_profile VARCHAR NOT NULL,
    observed_close DECIMAL(18,4) NOT NULL,
    volume_multiple DECIMAL(18,4),
    delivery_percentage DECIMAL(8,4),
    delivery_chg_pp DECIMAL(8,4),
    drawdown_20d_pct DECIMAL(8,4),
    close_range_position DECIMAL(6,4),
    turnover_cr DECIMAL(18,2),
    liquidity_tier VARCHAR NOT NULL,
    market_regime VARCHAR,
    initial_characteristics_json JSON,
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_document_id VARCHAR REFERENCES source_document_revision(source_document_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_event_obs ON market_event_observation_ledger(isin, trade_date, event_type, detector_profile);
CREATE INDEX IF NOT EXISTS idx_event_obs_date_type ON market_event_observation_ledger(trade_date, event_type);

CREATE TABLE IF NOT EXISTS market_event_outcome_tracking (
    outcome_id VARCHAR PRIMARY KEY,
    event_id VARCHAR NOT NULL REFERENCES market_event_observation_ledger(event_id),
    horizon_days INTEGER NOT NULL CHECK (horizon_days IN (1, 3, 5, 10, 20, 60)),
    eval_status VARCHAR NOT NULL CHECK (eval_status IN ('PENDING', 'EVALUATED', 'INCOMPLETE_DATA', 'EXPIRED')),
    forward_target_date DATE,
    forward_close DECIMAL(18,4),
    forward_return_pct DECIMAL(8,4),
    max_favorable_excursion_pct DECIMAL(8,4),
    max_adverse_excursion_pct DECIMAL(8,4),
    structural_breakout_occurred BOOLEAN,
    expansion_continued BOOLEAN,
    signal_failed BOOLEAN,
    event_repeated BOOLEAN DEFAULT FALSE,
    evaluated_at TIMESTAMP WITH TIME ZONE
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_event_outcome_horizon ON market_event_outcome_tracking(event_id, horizon_days);

CREATE TABLE IF NOT EXISTS market_event_research_journal (
    journal_id VARCHAR PRIMARY KEY,
    entry_date DATE NOT NULL,
    title VARCHAR NOT NULL,
    observation_summary TEXT NOT NULL,
    evidence_data_json JSON NOT NULL,
    pattern_type VARCHAR NOT NULL CHECK (pattern_type IN ('ISOLATED', 'RECURRING', 'REGIME_DEPENDENT', 'SECTOR_CLUSTER')),
    hypothesis TEXT NOT NULL,
    counter_evidence TEXT,
    confidence_level VARCHAR NOT NULL CHECK (confidence_level IN ('INSUFFICIENT', 'EMERGING', 'REPEATED', 'STRONGLY_SUPPORTED')),
    next_test TEXT NOT NULL,
    recorded_by VARCHAR NOT NULL DEFAULT 'hamsa-empirical-researcher',
    recorded_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_date ON market_event_research_journal(entry_date);