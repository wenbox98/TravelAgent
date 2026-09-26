-- Extend the existing single-use authorization table; no new permission framework.
-- Copy all related rows before rebuilding the FK cycle. Entire migration is atomic.
PRAGMA defer_foreign_keys=ON;
CREATE TABLE saved_authorizations AS SELECT * FROM extraction_authorizations;
CREATE TABLE saved_attempts AS SELECT * FROM extraction_attempts;
CREATE TABLE saved_candidates AS SELECT * FROM extraction_candidates;
DROP TABLE extraction_candidates;
DROP TABLE extraction_authorizations;
DROP TABLE extraction_attempts;
CREATE TABLE extraction_authorizations (
    authorization_id TEXT PRIMARY KEY CHECK(authorization_id IN ('t064-response-timeout-once','t066-reference-s2-once','t066-reference-s3-once')),
    base_attempt_id TEXT NOT NULL UNIQUE REFERENCES extraction_attempts(attempt_id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL REFERENCES extraction_batches(batch_id),
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    account_scope TEXT NOT NULL,
    normalization_version INTEGER NOT NULL CHECK(normalization_version=1),
    fix_commit TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    consumed_at TEXT,
    dispatch_started_at TEXT
);
CREATE TABLE extraction_attempts (
    attempt_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES extraction_batches(batch_id),
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    normalization_version INTEGER NOT NULL CHECK(normalization_version = 1),
    extraction_version INTEGER NOT NULL CHECK(extraction_version >= 1),
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 3),
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','PENDING_REVIEW','PARTIAL_SUCCESS',
        'SUCCEEDED','NO_ACCEPTED_EVIDENCE','FAILED','INTERRUPTED','OBSOLETE')),
    diagnostic_json TEXT,
    retry_fix_commit TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    content_hash TEXT NOT NULL,
    extraction_mode TEXT,
    authorization_id TEXT UNIQUE REFERENCES extraction_authorizations(authorization_id) ON DELETE CASCADE,
    CHECK((attempt_number <= 2 AND authorization_id IS NULL) OR (attempt_number=3 AND authorization_id IS NOT NULL)),
    UNIQUE(batch_id, content_id, attempt_number)
);
CREATE TABLE extraction_candidates (
    attempt_id TEXT NOT NULL REFERENCES extraction_attempts(attempt_id) ON DELETE CASCADE,
    candidate_index INTEGER NOT NULL CHECK(candidate_index BETWEEN 0 AND 11),
    candidate_json TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    context_status TEXT NOT NULL CHECK(context_status IN ('PENDING','REJECTED','ACCEPTED')),
    context_reason TEXT NOT NULL,
    review_json TEXT,
    claim_id TEXT REFERENCES claims(claim_id) ON DELETE CASCADE,
    PRIMARY KEY(attempt_id, candidate_index)
);

INSERT INTO extraction_attempts SELECT * FROM saved_attempts;
INSERT INTO extraction_authorizations SELECT * FROM saved_authorizations;
INSERT INTO extraction_candidates SELECT * FROM saved_candidates;
DROP TABLE saved_candidates;
DROP TABLE saved_attempts;
DROP TABLE saved_authorizations;
