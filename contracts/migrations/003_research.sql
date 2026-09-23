-- T05 internal research ledger. Sources/claims remain the existing Evidence schema.
CREATE TABLE research_questions (
    research_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    current_revision INTEGER NOT NULL CHECK(current_revision >= 0),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE research_runs (
    run_id TEXT PRIMARY KEY,
    research_id TEXT NOT NULL REFERENCES research_questions(research_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'FINISHED')),
    summary_json TEXT CHECK(summary_json IS NULL OR json_valid(summary_json)),
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX research_runs_question ON research_runs(research_id, revision);

-- A snapshot contains allowlisted metadata only. The source_id is intentionally not
-- an FK to sources: temporary :memory: research keeps its Evidence exclusively in RAM.
CREATE TABLE source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    account_scope TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    UNIQUE(source_id, account_scope),
    FOREIGN KEY(policy_id, policy_version) REFERENCES source_policies(policy_id, version)
);
CREATE TABLE research_run_sources (
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES source_snapshots(snapshot_id) ON DELETE CASCADE,
    PRIMARY KEY(run_id, snapshot_id)
);
CREATE TABLE research_gaps (
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    gap_id TEXT NOT NULL,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    PRIMARY KEY(run_id, gap_id)
);
CREATE TABLE research_queries (
    research_id TEXT NOT NULL REFERENCES research_questions(research_id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    PRIMARY KEY(research_id, query)
);
CREATE TABLE research_ops (
    research_id TEXT NOT NULL REFERENCES research_questions(research_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    kind TEXT NOT NULL CHECK(kind IN ('SEARCH', 'DETAIL')),
    fingerprint TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    PRIMARY KEY(research_id, kind, fingerprint)
);
CREATE INDEX research_ops_run ON research_ops(run_id, kind);
