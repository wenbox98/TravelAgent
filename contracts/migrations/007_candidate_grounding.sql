-- Rebuild the attempt CHECK constraint without changing historical statuses/counters.
CREATE TABLE extraction_attempts_v7 (
    attempt_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES extraction_batches(batch_id),
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    normalization_version INTEGER NOT NULL CHECK(normalization_version = 1),
    extraction_version INTEGER NOT NULL CHECK(extraction_version >= 1),
    attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 2),
    status TEXT NOT NULL CHECK(status IN ('PENDING','RUNNING','PENDING_REVIEW','PARTIAL_SUCCESS',
        'SUCCEEDED','NO_ACCEPTED_EVIDENCE','FAILED','INTERRUPTED','OBSOLETE')),
    diagnostic_json TEXT,
    retry_fix_commit TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    content_hash TEXT NOT NULL,
    extraction_mode TEXT,
    UNIQUE(batch_id, content_id, attempt_number)
);
INSERT INTO extraction_attempts_v7
SELECT a.*, c.content_hash, NULL FROM extraction_attempts a JOIN source_contents c USING(content_id);
DROP TABLE extraction_attempts;
ALTER TABLE extraction_attempts_v7 RENAME TO extraction_attempts;

-- Private necessary claim/quote/conditions only; never model envelopes or reasoning.
-- Lifetime is bounded by the original snapshot/attempt; deletion cascades.
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
