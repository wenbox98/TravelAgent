-- One operator-approved continuation. No cascade: deleting cache cannot renew permits.
CREATE TABLE research_continuations (
    continuation_id TEXT PRIMARY KEY CHECK(continuation_id='t065-coverage-first-plan'),
    account_scope TEXT NOT NULL,
    predecessor TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE continuation_operations (
    continuation_id TEXT NOT NULL REFERENCES research_continuations(continuation_id),
    kind TEXT NOT NULL CHECK(kind IN ('CONNECT','SEARCH','DETAIL','MODEL')),
    fingerprint TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    PRIMARY KEY(continuation_id,kind,fingerprint)
);
