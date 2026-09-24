-- Private local research only. Application gates detail provenance, policy, scope,
-- sensitive text and retention before any write. No URLs/images/browser credentials.
CREATE TABLE source_contents (
    content_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
    account_scope TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
    raw_text TEXT NOT NULL,
    dom_text TEXT,
    normalized_text TEXT NOT NULL,
    normalization_version INTEGER NOT NULL DEFAULT 1 CHECK(normalization_version = 1),
    content_completeness TEXT NOT NULL CHECK(content_completeness IN ('FULL_TEXT','PARTIAL_TEXT')),
    retrieved_at TEXT NOT NULL,
    last_retrieved_at TEXT NOT NULL,
    published_at TEXT,
    body_origin TEXT NOT NULL CHECK(body_origin IN ('STATE','DOM','UNKNOWN')),
    canonical_relation TEXT NOT NULL,
    truncation_risk INTEGER NOT NULL CHECK(truncation_risk IN (0,1)),
    image_count INTEGER NOT NULL CHECK(image_count >= 0),
    image_status TEXT NOT NULL CHECK(image_status = 'IMAGE_NOT_ANALYZED'),
    retention TEXT NOT NULL CHECK(retention IN ('7_DAYS','30_DAYS','PERSISTENT')),
    expires_at TEXT,
    FOREIGN KEY(policy_id,policy_version) REFERENCES source_policies(policy_id,version),
    UNIQUE(source_id, account_scope, content_hash)
);
CREATE TABLE source_body_blocks (
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    block_index INTEGER NOT NULL CHECK(block_index >= 0),
    normalized_text TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
    locator TEXT NOT NULL,
    origin TEXT NOT NULL,
    truncation_risk INTEGER NOT NULL CHECK(truncation_risk IN (0,1)),
    PRIMARY KEY(content_id, block_index)
);
CREATE TABLE research_run_contents (
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    content_id TEXT NOT NULL REFERENCES source_contents(content_id) ON DELETE CASCADE,
    PRIMARY KEY(run_id, content_id)
);
