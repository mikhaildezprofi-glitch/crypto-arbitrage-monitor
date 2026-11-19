CREATE TABLE IF NOT EXISTS quote_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    pair TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    indicative_only INTEGER NOT NULL,
    source_pair_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_quote_observations_source_id
    ON quote_observations(source, id DESC);
CREATE TABLE IF NOT EXISTS source_status (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL,
    last_success_at TEXT,
    error_type TEXT
);
