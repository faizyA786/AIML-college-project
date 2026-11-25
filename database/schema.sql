-- Cross-Domain Research Signal Lab schema
-- Source observations are unverified by default. The one-time migration below
-- downgrades rows that may have inherited the old DEFAULT 'curated' value.

CREATE TABLE IF NOT EXISTS research_papers (
    id BIGSERIAL PRIMARY KEY,
    domain TEXT NOT NULL,
    year INTEGER NOT NULL,
    title TEXT NOT NULL,
    authors TEXT NOT NULL,
    venue TEXT NOT NULL,
    method TEXT NOT NULL,
    relevance TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    frequency TEXT,
    coverage TEXT,
    limitations TEXT,
    retrieved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS benchmark_monthly_observations (
    series_key TEXT NOT NULL,
    period DATE NOT NULL,
    target_value_usd DOUBLE PRECISION NOT NULL CHECK (target_value_usd >= 0),
    policy_signal DOUBLE PRECISION,
    sector_ip_index DOUBLE PRECISION,
    economic_index DOUBLE PRECISION,
    target_published_at DATE,
    policy_published_at DATE,
    source_version TEXT NOT NULL,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CONSTRAINT benchmark_observations_source_status_check
        CHECK (source_status IN ('unverified', 'curated')),
    PRIMARY KEY (series_key, period)
);

ALTER TABLE benchmark_monthly_observations
    ADD COLUMN IF NOT EXISTS source_status TEXT;
ALTER TABLE benchmark_monthly_observations
    ALTER COLUMN source_status SET DEFAULT 'unverified';

-- Earlier schema versions defaulted source_status to curated. Since the old
-- schema cannot tell explicit human verification from an inherited default,
-- conservatively downgrade those legacy rows once. Re-curate only after review.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = '2026-11-source-status-default') THEN
        UPDATE benchmark_monthly_observations
        SET source_status = 'unverified'
        WHERE source_status IS NULL OR source_status NOT IN ('unverified', 'curated') OR source_status = 'curated';
        INSERT INTO schema_migrations(version) VALUES ('2026-11-source-status-default');
    END IF;
END $$;

ALTER TABLE benchmark_monthly_observations
    ALTER COLUMN source_status SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'benchmark_observations_source_status_check'
          AND conrelid = 'benchmark_monthly_observations'::regclass
    ) THEN
        ALTER TABLE benchmark_monthly_observations
            ADD CONSTRAINT benchmark_observations_source_status_check
            CHECK (source_status IN ('unverified', 'curated'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS policy_events (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    published_at DATE NOT NULL,
    effective_at DATE,
    destination_code TEXT,
    direction TEXT NOT NULL DEFAULT 'ambiguous'
        CONSTRAINT policy_events_direction_check
        CHECK (direction IN ('restrictive', 'relaxing', 'neutral', 'ambiguous')),
    severity INTEGER NOT NULL DEFAULT 1
        CONSTRAINT policy_events_severity_check
        CHECK (severity BETWEEN 1 AND 5),
    signal_value DOUBLE PRECISION,
    source_url TEXT NOT NULL,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CONSTRAINT policy_events_source_status_check
        CHECK (source_status IN ('unverified', 'curated')),
    notes TEXT
);

ALTER TABLE policy_events ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'ambiguous';
ALTER TABLE policy_events ADD COLUMN IF NOT EXISTS severity INTEGER NOT NULL DEFAULT 1;
ALTER TABLE policy_events ADD COLUMN IF NOT EXISTS source_status TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE policy_events ALTER COLUMN signal_value DROP NOT NULL;
ALTER TABLE policy_events ALTER COLUMN signal_value DROP DEFAULT;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_events_direction_check' AND conrelid = 'policy_events'::regclass
    ) THEN
        ALTER TABLE policy_events ADD CONSTRAINT policy_events_direction_check
            CHECK (direction IN ('restrictive', 'relaxing', 'neutral', 'ambiguous'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_events_severity_check' AND conrelid = 'policy_events'::regclass
    ) THEN
        ALTER TABLE policy_events ADD CONSTRAINT policy_events_severity_check
            CHECK (severity BETWEEN 1 AND 5);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'policy_events_source_status_check' AND conrelid = 'policy_events'::regclass
    ) THEN
        ALTER TABLE policy_events ADD CONSTRAINT policy_events_source_status_check
            CHECK (source_status IN ('unverified', 'curated'));
    END IF;
END $$;

-- Explicit monthly coverage prevents an absent event row from being interpreted
-- as zero policy activity. Only complete + curated months may be zero-filled.
CREATE TABLE IF NOT EXISTS policy_event_coverage (
    series_key TEXT NOT NULL,
    period DATE NOT NULL,
    coverage_status TEXT NOT NULL CHECK (coverage_status IN ('complete', 'incomplete')),
    source_url TEXT NOT NULL,
    source_version TEXT NOT NULL,
    source_status TEXT NOT NULL DEFAULT 'unverified'
        CONSTRAINT policy_event_coverage_source_status_check
        CHECK (source_status IN ('unverified', 'curated')),
    notes TEXT,
    PRIMARY KEY (series_key, period)
);

CREATE TABLE IF NOT EXISTS forecast_runs (
    id BIGSERIAL PRIMARY KEY,
    benchmark_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    model_version TEXT NOT NULL DEFAULT 'benchmark-v1',
    model_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    horizon_months INTEGER NOT NULL CHECK (horizon_months > 0),
    data_version TEXT NOT NULL,
    target_period DATE NOT NULL,
    metrics JSONB NOT NULL,
    forecasts JSONB NOT NULL,
    caveats JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
    model_id TEXT NOT NULL,
    forecast_origin DATE NOT NULL,
    target_period DATE NOT NULL,
    predicted_change_pct DOUBLE PRECISION NOT NULL,
    implied_value_usd DOUBLE PRECISION NOT NULL CHECK (implied_value_usd >= 0),
    observed_value_usd DOUBLE PRECISION,
    observed_change_pct DOUBLE PRECISION,
    evaluated_at TIMESTAMPTZ,
    evaluation_status TEXT NOT NULL DEFAULT 'awaiting_outcome'
        CHECK (evaluation_status IN ('awaiting_outcome', 'observed', 'not_evaluable'))
);

ALTER TABLE forecast_runs ADD COLUMN IF NOT EXISTS model_version TEXT NOT NULL DEFAULT 'benchmark-v1';
ALTER TABLE forecast_runs ADD COLUMN IF NOT EXISTS model_config JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE predictions ADD COLUMN IF NOT EXISTS observed_change_pct DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_benchmark_observations_period
    ON benchmark_monthly_observations (period);
CREATE INDEX IF NOT EXISTS idx_policy_events_publication
    ON policy_events (published_at, destination_code);
CREATE UNIQUE INDEX IF NOT EXISTS idx_policy_events_unique_source_record
    ON policy_events (title, published_at, source_url);
CREATE INDEX IF NOT EXISTS idx_policy_coverage_period
    ON policy_event_coverage (series_key, period, coverage_status, source_status);
CREATE INDEX IF NOT EXISTS idx_predictions_target_period
    ON predictions (target_period, evaluation_status);
