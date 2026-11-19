CREATE TABLE IF NOT EXISTS current_quotes (
    source TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    indicative_only INTEGER NOT NULL,
    source_pair_id TEXT
);
CREATE TABLE IF NOT EXISTS source_status (
    source TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    last_attempt_at TEXT NOT NULL,
    last_success_at TEXT,
    error_type TEXT
);
