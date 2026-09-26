-- A separate, single-use authorization; old batch ceilings and attempts are untouched.
CREATE TABLE extraction_authorizations (
    authorization_id TEXT PRIMARY KEY CHECK(authorization_id='t064-response-timeout-once'),
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
CREATE TABLE extraction_attempts_v8 (
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
INSERT INTO extraction_attempts_v8 SELECT a.*,NULL FROM extraction_attempts a;
CREATE TABLE candidate_migration_copy AS SELECT * FROM extraction_candidates;
DROP TABLE extraction_candidates;
DROP TABLE extraction_attempts;
ALTER TABLE extraction_attempts_v8 RENAME TO extraction_attempts;
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
INSERT INTO extraction_candidates SELECT * FROM candidate_migration_copy;
DROP TABLE candidate_migration_copy;
