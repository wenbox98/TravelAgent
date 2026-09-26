-- Generalize the existing continuation ledger without resetting any old permit.
PRAGMA defer_foreign_keys=ON;
CREATE TABLE saved_continuations AS SELECT * FROM research_continuations;
CREATE TABLE saved_operations AS SELECT * FROM continuation_operations;
DROP TABLE continuation_operations;
DROP TABLE research_continuations;
CREATE TABLE research_continuations (
    continuation_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    predecessor TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    limits_json TEXT,
    gate_json TEXT
);
CREATE TABLE continuation_operations (
    continuation_id TEXT NOT NULL REFERENCES research_continuations(continuation_id),
    kind TEXT NOT NULL CHECK(kind IN ('CONNECT','SEARCH','DETAIL','MODEL')),
    fingerprint TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    PRIMARY KEY(continuation_id,kind,fingerprint)
);
INSERT INTO research_continuations(continuation_id,account_scope,predecessor,config_json,created_at,started_at,finished_at)
    SELECT * FROM saved_continuations;
INSERT INTO continuation_operations SELECT * FROM saved_operations;
DROP TABLE saved_operations;
DROP TABLE saved_continuations;

CREATE TABLE context_review_runs (
    review_id TEXT PRIMARY KEY,
    continuation_id TEXT NOT NULL REFERENCES research_continuations(continuation_id),
    attempt_id TEXT NOT NULL REFERENCES extraction_attempts(attempt_id) ON DELETE CASCADE,
    account_scope TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('EVALUATION','RUNTIME')),
    revision INTEGER NOT NULL,
    input_hash TEXT NOT NULL,
    target_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','COMPLETED','FAILED','INTERRUPTED','OBSOLETE')),
    diagnostic_json TEXT,
    results_json TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(continuation_id,attempt_id)
);

CREATE TABLE preview_jobs (
    job_id TEXT PRIMARY KEY,
    continuation_id TEXT NOT NULL REFERENCES research_continuations(continuation_id),
    session_id TEXT NOT NULL REFERENCES preview_sessions(session_id),
    account_scope TEXT NOT NULL,
    request_revision INTEGER NOT NULL,
    research_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','WAITING_LOGIN','VERIFICATION_REQUIRED',
        'PARTIAL','COMPLETED','NEEDS_REVIEW','FAILED','CANCELED','INTERRUPTED')),
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(account_scope,idempotency_key)
);
CREATE UNIQUE INDEX one_live_preview_job ON preview_jobs(continuation_id);
