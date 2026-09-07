-- Casework schema. Applied fresh to both the dev DB (docker-compose "db") and
-- the disposable integration-test DB (docker-compose "db_test").

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

CREATE TABLE personas (
    account_id               TEXT PRIMARY KEY,
    display_name             TEXT NOT NULL,
    tenure_days              INTEGER NOT NULL,
    lifetime_volume_cents    BIGINT NOT NULL,
    prior_case_count         INTEGER NOT NULL DEFAULT 0,
    default_device_context   TEXT NOT NULL CHECK (default_device_context IN ('known_device', 'new_device')),
    default_geo_context      TEXT NOT NULL CHECK (default_geo_context IN ('usual_location', 'new_or_foreign_location')),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE rules (
    rule_id       TEXT PRIMARY KEY,
    pattern       TEXT CHECK (
        pattern IS NULL OR pattern IN (
            'card_testing', 'account_takeover', 'merchant_fraud',
            'mule_activity', 'friendly_fraud', 'benign'
        )
    ),
    title         TEXT NOT NULL,
    description   TEXT NOT NULL,
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE cases (
    case_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id                 TEXT NOT NULL UNIQUE,
    account_id                TEXT NOT NULL,
    signal_type               TEXT NOT NULL CHECK (signal_type IN ('transaction', 'login', 'chargeback')),
    occurred_at               TIMESTAMPTZ NOT NULL,
    upstream_score            DOUBLE PRECISION NOT NULL,
    flag_reason               TEXT NOT NULL,
    payload                   JSONB NOT NULL,

    pattern                   TEXT CHECK (
        pattern IS NULL OR pattern IN (
            'card_testing', 'account_takeover', 'merchant_fraud',
            'mule_activity', 'friendly_fraud', 'benign'
        )
    ),
    triage_tier               TEXT CHECK (triage_tier IS NULL OR triage_tier IN ('low', 'elevated', 'critical')),
    confidence                DOUBLE PRECISION,
    entities                  JSONB,

    matched_rules             JSONB,
    similar_cases             JSONB,
    evidence                  JSONB,

    risk_score                DOUBLE PRECISION,
    recommended_action        TEXT CHECK (
        recommended_action IS NULL OR recommended_action IN ('block', 'flag_for_review', 'monitor', 'clear')
    ),
    draft_note                TEXT,

    route                     TEXT CHECK (route IS NULL OR route IN ('critical', 'elevated', 'low')),
    status                    TEXT NOT NULL CHECK (
        status IN ('auto_escalated', 'pending_review', 'closed', 'error')
    ),
    resolution                TEXT NOT NULL DEFAULT 'none' CHECK (resolution IN ('approved', 'denied', 'none')),
    approved_by               TEXT,

    stripe_payment_intent_id  TEXT,
    source                    TEXT NOT NULL CHECK (
        source IN ('live_stripe', 'bulk_synthetic', 'eval', 'integration_test')
    ),

    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_cases_status ON cases (status) WHERE status = 'pending_review';
CREATE INDEX idx_cases_account_id ON cases (account_id);
CREATE INDEX idx_cases_pattern ON cases (pattern);
CREATE INDEX idx_cases_source ON cases (source);

CREATE TABLE case_events (
    event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id        UUID NOT NULL REFERENCES cases (case_id) ON DELETE CASCADE,
    event_type     TEXT NOT NULL,
    event_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_case_events_case_id ON case_events (case_id);

CREATE TABLE signals_log (
    signal_id       TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    device_context  TEXT,
    geo_context     TEXT,
    signal_type     TEXT NOT NULL CHECK (signal_type IN ('transaction', 'login', 'chargeback')),
    occurred_at     TIMESTAMPTZ NOT NULL,
    source          TEXT NOT NULL CHECK (
        source IN ('live_stripe', 'bulk_synthetic', 'eval', 'integration_test')
    ),
    raw_signal      JSONB NOT NULL
);

CREATE INDEX idx_signals_log_account_time ON signals_log (account_id, occurred_at);
CREATE INDEX idx_signals_log_device_time ON signals_log (device_context, occurred_at);
