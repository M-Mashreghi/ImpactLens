-- ImpactLens schema v1: system of record for portfolios, securities, news, analyses, impacts, alerts.
-- Timestamps are ISO-8601 UTC strings. JSON columns hold validated, structured payloads.

CREATE TABLE securities (
    security_id     TEXT PRIMARY KEY,
    issuer_id       TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    mic             TEXT,
    country         TEXT,
    currency        TEXT,
    sector          TEXT,
    industry        TEXT,
    share_class     TEXT,
    aliases_json    TEXT NOT NULL DEFAULT '[]',
    active          INTEGER NOT NULL DEFAULT 1,
    UNIQUE (ticker, exchange)
);
CREATE INDEX ix_securities_ticker ON securities (ticker);
CREATE INDEX ix_securities_issuer ON securities (issuer_id);

CREATE TABLE security_relationships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_security_id  TEXT NOT NULL REFERENCES securities (security_id),
    target_security_id  TEXT NOT NULL REFERENCES securities (security_id),
    relationship_type   TEXT NOT NULL CHECK (relationship_type IN ('supplier', 'customer', 'competitor')),
    strength            REAL NOT NULL CHECK (strength > 0 AND strength <= 1),
    provenance_source   TEXT NOT NULL,
    provenance_ref      TEXT NOT NULL,
    as_of               TEXT NOT NULL,
    UNIQUE (source_security_id, target_security_id, relationship_type)
);

CREATE TABLE security_factor_exposures (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    security_id      TEXT NOT NULL REFERENCES securities (security_id),
    factor_key       TEXT NOT NULL,
    family           TEXT NOT NULL CHECK (family IN ('country', 'commodity', 'macro')),
    sensitivity      REAL NOT NULL CHECK (sensitivity >= -1 AND sensitivity <= 1 AND sensitivity != 0),
    provenance_source TEXT NOT NULL,
    provenance_ref   TEXT NOT NULL,
    as_of            TEXT NOT NULL,
    UNIQUE (security_id, factor_key)
);

CREATE TABLE portfolios (
    portfolio_id  TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    base_currency TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE portfolio_snapshots (
    snapshot_id     TEXT PRIMARY KEY,
    portfolio_id    TEXT NOT NULL REFERENCES portfolios (portfolio_id),
    as_of           TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    source          TEXT NOT NULL,
    weight_basis    TEXT NOT NULL,
    total_market_value REAL,
    content_hash    TEXT NOT NULL
);
CREATE INDEX ix_snapshots_portfolio_asof ON portfolio_snapshots (portfolio_id, as_of);

CREATE TABLE positions (
    snapshot_id   TEXT NOT NULL REFERENCES portfolio_snapshots (snapshot_id),
    line_no       INTEGER NOT NULL,
    security_id   TEXT,
    ticker        TEXT NOT NULL,
    exchange      TEXT,
    display_name  TEXT NOT NULL,
    asset_type    TEXT NOT NULL CHECK (asset_type IN ('security', 'cash')),
    quantity      REAL,
    market_value  REAL,
    weight        REAL NOT NULL,
    currency      TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, line_no)
);
CREATE INDEX ix_positions_security ON positions (security_id);

-- Snapshots are immutable: historical impacts must keep referencing the exact holdings used.
CREATE TRIGGER trg_snapshots_no_update BEFORE UPDATE ON portfolio_snapshots
BEGIN SELECT RAISE(ABORT, 'portfolio snapshots are immutable'); END;
CREATE TRIGGER trg_snapshots_no_delete BEFORE DELETE ON portfolio_snapshots
BEGIN SELECT RAISE(ABORT, 'portfolio snapshots are immutable'); END;
CREATE TRIGGER trg_positions_no_update BEFORE UPDATE ON positions
BEGIN SELECT RAISE(ABORT, 'positions are immutable'); END;
CREATE TRIGGER trg_positions_no_delete BEFORE DELETE ON positions
BEGIN SELECT RAISE(ABORT, 'positions are immutable'); END;

CREATE TABLE source_checkpoints (
    source_key   TEXT PRIMARY KEY,
    cursor_json  TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE TABLE news (
    news_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name          TEXT NOT NULL,
    source_kind          TEXT NOT NULL,
    source_item_id       TEXT,
    source_url           TEXT,
    canonical_url        TEXT,
    title                TEXT NOT NULL,
    normalized_title     TEXT NOT NULL,
    body_text            TEXT NOT NULL,
    normalized_text      TEXT NOT NULL,
    published_at         TEXT,
    published_at_quality TEXT NOT NULL,
    retrieved_at         TEXT NOT NULL,
    content_hash         TEXT NOT NULL,
    canonical_news_id    INTEGER REFERENCES news (news_id),
    ingestion_status     TEXT NOT NULL,
    error_json           TEXT,
    provenance_json      TEXT NOT NULL DEFAULT '{}',
    status_updated_at    TEXT NOT NULL
);
CREATE INDEX ix_news_hash ON news (content_hash);
CREATE INDEX ix_news_status ON news (ingestion_status);
CREATE INDEX ix_news_published ON news (published_at);
CREATE INDEX ix_news_canonical_url ON news (canonical_url);
CREATE INDEX ix_news_source_item ON news (source_name, source_item_id);

CREATE TABLE news_status_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id     INTEGER NOT NULL REFERENCES news (news_id),
    status      TEXT NOT NULL,
    at          TEXT NOT NULL,
    detail_json TEXT
);
CREATE INDEX ix_news_history_news ON news_status_history (news_id);

CREATE TABLE ingestion_failures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key  TEXT NOT NULL,
    item_ref    TEXT,
    stage       TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    at          TEXT NOT NULL
);

CREATE TABLE analyses (
    analysis_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id         INTEGER NOT NULL REFERENCES news (news_id),
    status          TEXT NOT NULL CHECK (status IN ('Valid', 'Uncertain', 'Failed')),
    schema_version  TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    model_provider  TEXT NOT NULL,
    model_name      TEXT NOT NULL,
    event_type      TEXT,
    event_summary   TEXT,
    direction       TEXT,
    severity        TEXT,
    confidence      REAL,
    time_horizon    TEXT,
    analysis_json   TEXT,
    evidence_report_json TEXT,
    resolution_json TEXT,
    raw_response    TEXT,
    failure_json    TEXT,
    attempts        INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    UNIQUE (news_id, schema_version, prompt_version, model_provider, model_name)
);
CREATE INDEX ix_analyses_status ON analyses (status);
CREATE INDEX ix_analyses_event_type ON analyses (event_type);

CREATE TABLE impacts (
    impact_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id       INTEGER NOT NULL REFERENCES analyses (analysis_id),
    news_id           INTEGER NOT NULL REFERENCES news (news_id),
    snapshot_id       TEXT NOT NULL REFERENCES portfolio_snapshots (snapshot_id),
    scoring_version   TEXT NOT NULL,
    rules_version     TEXT NOT NULL,
    signed_score      REAL NOT NULL,
    absolute_priority REAL NOT NULL,
    impact_level      TEXT NOT NULL,
    result_json       TEXT NOT NULL,
    explanation_json  TEXT NOT NULL,
    computed_at       TEXT NOT NULL,
    UNIQUE (analysis_id, snapshot_id, scoring_version)
);
CREATE INDEX ix_impacts_priority ON impacts (absolute_priority);
CREATE INDEX ix_impacts_snapshot ON impacts (snapshot_id);

CREATE TABLE impact_components (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    impact_id          INTEGER NOT NULL REFERENCES impacts (impact_id) ON DELETE CASCADE,
    security_id        TEXT,
    ticker             TEXT NOT NULL,
    relationship_type  TEXT NOT NULL,
    direction          TEXT NOT NULL,
    signed_component   REAL NOT NULL,
    absolute_component REAL NOT NULL,
    counted            INTEGER NOT NULL,
    component_json     TEXT NOT NULL
);
CREATE INDEX ix_components_impact ON impact_components (impact_id);

CREATE TABLE alerts (
    alert_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    idempotency_key  TEXT NOT NULL UNIQUE,
    impact_id        INTEGER NOT NULL REFERENCES impacts (impact_id),
    news_id          INTEGER NOT NULL,
    portfolio_id     TEXT NOT NULL,
    snapshot_id      TEXT NOT NULL,
    scoring_version  TEXT NOT NULL,
    channel          TEXT NOT NULL,
    impact_level     TEXT NOT NULL,
    status           TEXT NOT NULL,
    detail_json      TEXT,
    created_at       TEXT NOT NULL
);
CREATE INDEX ix_alerts_portfolio_channel ON alerts (portfolio_id, channel, created_at);

CREATE TABLE event_studies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id         INTEGER NOT NULL REFERENCES news (news_id),
    security_id     TEXT NOT NULL,
    benchmark_symbol TEXT NOT NULL,
    config_version  TEXT NOT NULL,
    as_of           TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (news_id, security_id, benchmark_symbol, config_version, as_of)
);

CREATE TABLE job_runs (
    run_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    summary_json TEXT,
    error       TEXT
);
CREATE INDEX ix_job_runs_name ON job_runs (job_name, started_at);
