-- P01 user choices only. No source, review, research or operation ledger updates.
CREATE TABLE preview_sessions (
    session_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('SYNTHETIC_DEMO','CACHED_PRIVATE_PREVIEW')),
    research_id TEXT REFERENCES research_questions(research_id),
    research_revision INTEGER,
    evidence_revision TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    state_json TEXT NOT NULL CHECK(json_valid(state_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE preview_receipts (
    account_scope TEXT NOT NULL,
    mode TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES preview_sessions(session_id),
    PRIMARY KEY(account_scope,mode,idempotency_key)
);
