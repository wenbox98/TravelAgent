-- Extend the same durable operation ledger; preserve all existing rows and grants.
CREATE TABLE saved_map_operations AS SELECT * FROM continuation_operations;
DROP TABLE continuation_operations;
CREATE TABLE continuation_operations (
    continuation_id TEXT NOT NULL REFERENCES research_continuations(continuation_id),
    kind TEXT NOT NULL CHECK(kind IN ('CONNECT','SEARCH','DETAIL','MODEL','MAP_PLACE','MAP_ROUTE')),
    fingerprint TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    PRIMARY KEY(continuation_id,kind,fingerprint)
);
INSERT INTO continuation_operations SELECT * FROM saved_map_operations;
DROP TABLE saved_map_operations;

-- Only user-authored inputs and original Evidence references, NEVER map results.
CREATE TABLE route_preview_inputs (
    session_id TEXT PRIMARY KEY REFERENCES preview_sessions(session_id),
    account_scope TEXT NOT NULL,
    option_id TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    draft_json TEXT NOT NULL,
    adopted_json TEXT,
    updated_at TEXT NOT NULL
);
