-- TravelAgent v0.1 initial schema DRAFT. Executed against SQLite for structural validation only.
-- No external content may be written until application SourcePolicy checks succeed.
-- Immutable v1 baseline. Apply migrations/002_poc.sql for the current v1.1 contract.
-- Current runtime also applies 003, 004 and 005; 005 adds private detail text/blocks.
PRAGMA foreign_keys = ON;
CREATE TABLE schema_version(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
INSERT INTO schema_version VALUES(1, '2026-09-22T00:00:00Z');
CREATE TABLE trips(
 trip_id TEXT PRIMARY KEY, original_request TEXT NOT NULL, current_revision INTEGER NOT NULL DEFAULT 0 CHECK(current_revision>=0),
 phase TEXT NOT NULL, intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK(is_synthetic IN(0,1))
);
CREATE TABLE trip_revisions(
 trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE, revision INTEGER NOT NULL CHECK(revision>=0),
 parent_revision INTEGER, selection_json TEXT NOT NULL CHECK(json_valid(selection_json)),
 locked_json TEXT NOT NULL CHECK(json_valid(locked_json)), safe_plan_json TEXT CHECK(safe_plan_json IS NULL OR json_valid(safe_plan_json)),
 created_at TEXT NOT NULL, PRIMARY KEY(trip_id,revision)
);
CREATE TABLE proposals(
 proposal_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 base_revision INTEGER NOT NULL, patch_json TEXT NOT NULL CHECK(json_valid(patch_json)),
 safe_result_json TEXT CHECK(safe_result_json IS NULL OR json_valid(safe_result_json)),
 status TEXT NOT NULL CHECK(status IN('PENDING','CONFIRMED','REJECTED','OBSOLETE')), created_at TEXT NOT NULL
);
CREATE TABLE choice_events(
 event_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL, patch_json TEXT NOT NULL CHECK(json_valid(patch_json)), reason TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE auth_sessions(
 session_id TEXT PRIMARY KEY, generation INTEGER NOT NULL CHECK(generation>=0),
 state TEXT NOT NULL CHECK(state IN('DISCONNECTED','CONNECTING','QR_READY','WAITING_CONFIRMATION','VERIFYING','CONNECTED','EXPIRED','ACTION_REQUIRED','DISCONNECTING','ERROR','CANCELED')),
 account_scope TEXT, expires_at TEXT, last_verified_at TEXT, created_at TEXT NOT NULL
 -- NEVER add cookie, xsec_token, QR image or a raw browser profile to this table.
);
CREATE TABLE research_sessions(
 research_session_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 account_scope TEXT NOT NULL, budget_json TEXT NOT NULL CHECK(json_valid(budget_json)),
 spent_json TEXT NOT NULL CHECK(json_valid(spent_json)), generation INTEGER NOT NULL DEFAULT 0,
 policy_version INTEGER NOT NULL, created_at TEXT NOT NULL, closed_at TEXT
);
CREATE TABLE jobs(
 job_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 research_session_id TEXT NOT NULL REFERENCES research_sessions(research_session_id), revision INTEGER NOT NULL,
 generation INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN('QUEUED','RUNNING','WAITING_USER','WAITING_AUTH','PAUSED_RATE_LIMIT','PAUSED_BUDGET','COMPLETED','PARTIAL','FAILED','CANCELED','OBSOLETE')),
 phase TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, attempt INTEGER NOT NULL DEFAULT 0 CHECK(attempt>=0),
 safe_state_json TEXT NOT NULL CHECK(json_valid(safe_state_json)), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX idx_jobs_claim ON jobs(status,lease_until,created_at);
CREATE TABLE operations(
 operation_id TEXT PRIMARY KEY, operation_key TEXT NOT NULL UNIQUE,
 research_session_id TEXT NOT NULL REFERENCES research_sessions(research_session_id),
 job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE, revision INTEGER NOT NULL, generation INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN('SEARCH','DETAIL','AUTH_PROBE','IMAGE','MODEL','AMAP','QUOTE')),
 request_fingerprint TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN('RESERVED','DISPATCHED','COMPLETED','FAILED','CANCELED','UNKNOWN_OUTCOME')),
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0), result_handle TEXT,
 navigation_count INTEGER CHECK(navigation_count IS NULL OR navigation_count>=0),
 http_count INTEGER CHECK(http_count IS NULL OR http_count>=0), network_measurement TEXT NOT NULL DEFAULT 'UNAVAILABLE',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE job_events(
 job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE, event_id INTEGER NOT NULL CHECK(event_id>=0),
 revision INTEGER NOT NULL, type TEXT NOT NULL, safe_data_json TEXT NOT NULL CHECK(json_valid(safe_data_json)),
 created_at TEXT NOT NULL, PRIMARY KEY(job_id,event_id)
);
CREATE TABLE source_policies(
 policy_id TEXT NOT NULL, version INTEGER NOT NULL, policy_json TEXT NOT NULL CHECK(json_valid(policy_json)),
 reviewed_at TEXT, expires_at TEXT, PRIMARY KEY(policy_id,version)
);
CREATE TABLE sources(
 source_id TEXT PRIMARY KEY, provider TEXT NOT NULL, account_scope TEXT NOT NULL,
 canonical_url TEXT, title TEXT, content_hash TEXT, duplicate_cluster TEXT,
 completeness TEXT NOT NULL, policy_id TEXT NOT NULL, policy_version INTEGER NOT NULL,
 fetched_at TEXT NOT NULL, published_at TEXT, travel_occurred_at TEXT, deleted_at TEXT,
 is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK(is_synthetic IN(0,1)),
 FOREIGN KEY(policy_id,policy_version) REFERENCES source_policies(policy_id,version)
);
CREATE TABLE claims(
 claim_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
 topic TEXT NOT NULL, text TEXT NOT NULL, kind TEXT NOT NULL, locator TEXT NOT NULL,
 support TEXT NOT NULL, valid_from TEXT, valid_until TEXT, deleted_at TEXT
);
CREATE TABLE chunks(
 chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
 parent_chunk_id TEXT REFERENCES chunks(chunk_id) ON DELETE CASCADE, text TEXT NOT NULL, pretokenized_text TEXT NOT NULL,
 metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)), content_hash TEXT NOT NULL,
 embedding BLOB, embedding_model TEXT, embedding_dim INTEGER CHECK(embedding_dim IS NULL OR embedding_dim>0),
 normalization TEXT, deleted_at TEXT,
 CHECK((embedding IS NULL AND embedding_model IS NULL AND embedding_dim IS NULL) OR
       (embedding IS NOT NULL AND embedding_model IS NOT NULL AND embedding_dim IS NOT NULL))
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id UNINDEXED, pretokenized_text);
-- Application must maintain FTS and tombstones in the same transaction as visible chunk updates.
-- These delete triggers prevent accidental orphaned searchable content on normal deletion.
CREATE TRIGGER chunks_after_delete AFTER DELETE ON chunks BEGIN
 DELETE FROM chunks_fts WHERE chunk_id=OLD.chunk_id;
END;
CREATE TABLE lineage(
 parent_source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE CASCADE,
 artifact_kind TEXT NOT NULL, artifact_id TEXT NOT NULL, PRIMARY KEY(parent_source_id,artifact_kind,artifact_id)
);
CREATE TABLE quotes(
 quote_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 provider TEXT NOT NULL, product_type TEXT NOT NULL, product_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN('AVAILABLE','SOLD_OUT','NOT_ON_SALE','UNKNOWN','UNSUPPORTED')),
 min_fen INTEGER CHECK(min_fen IS NULL OR min_fen>=0), max_fen INTEGER CHECK(max_fen IS NULL OR max_fen>=0),
 price_basis TEXT NOT NULL, queried_at TEXT NOT NULL, valid_for TEXT NOT NULL,
 allowed_payload_json TEXT NOT NULL CHECK(json_valid(allowed_payload_json)),
 is_synthetic INTEGER NOT NULL DEFAULT 0 CHECK(is_synthetic IN(0,1)),
 CHECK(min_fen IS NULL OR max_fen IS NULL OR min_fen<=max_fen)
);
CREATE TABLE budget_lines(
 line_id TEXT NOT NULL, trip_id TEXT NOT NULL, revision INTEGER NOT NULL,
 category TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity>=1), unit TEXT NOT NULL,
 min_fen INTEGER CHECK(min_fen IS NULL OR min_fen>=0), max_fen INTEGER CHECK(max_fen IS NULL OR max_fen>=0),
 status TEXT NOT NULL CHECK(status IN('QUOTED','ESTIMATED','HISTORICAL','PAID','UNKNOWN')),
 included_in_line_id TEXT, quote_id TEXT REFERENCES quotes(quote_id) ON DELETE SET NULL,
 PRIMARY KEY(trip_id,revision,line_id), FOREIGN KEY(trip_id,revision) REFERENCES trip_revisions(trip_id,revision) ON DELETE CASCADE,
 CHECK(min_fen IS NULL OR max_fen IS NULL OR min_fen<=max_fen)
);
CREATE TABLE api_idempotency(
 scope TEXT NOT NULL, route TEXT NOT NULL, key TEXT NOT NULL, body_hash TEXT NOT NULL,
 resource_type TEXT NOT NULL, resource_id TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT,
 PRIMARY KEY(scope,route,key)
 -- Reference a resource, not a cached raw response (which may contain restricted content).
);

-- Only persist overview content where the active SourcePolicy permits it.
CREATE TABLE overview_results(
 overview_id TEXT PRIMARY KEY, trip_id TEXT NOT NULL REFERENCES trips(trip_id) ON DELETE CASCADE,
 revision INTEGER NOT NULL, availability TEXT NOT NULL CHECK(availability IN('AVAILABLE','EPHEMERAL','EXPIRED')),
 safe_result_json TEXT CHECK(safe_result_json IS NULL OR json_valid(safe_result_json)),
 created_at TEXT NOT NULL, expires_at TEXT,
 CHECK(availability='AVAILABLE' OR safe_result_json IS NULL)
);
