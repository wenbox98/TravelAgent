-- Durable model attempts are independent of browser operations and raw retention.
CREATE TABLE extraction_batches (
    batch_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 12)
);
CREATE TABLE extraction_attempts (
    attempt_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES extraction_batches(batch_id),
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    normalization_version INTEGER NOT NULL CHECK(normalization_version = 1),
    extraction_version INTEGER NOT NULL CHECK(extraction_version >= 1),
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 2),
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','INTERRUPTED','OBSOLETE')),
    diagnostic_json TEXT,
    retry_fix_commit TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(batch_id, content_id, extraction_version, attempt_number)
);
