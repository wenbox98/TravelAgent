-- Original v1 proposals/results and timestamps remain immutable.
ALTER TABLE context_review_runs ADD COLUMN review_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE context_review_runs ADD COLUMN rule_version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE review_revalidations (
 revalidation_id TEXT PRIMARY KEY,
 review_id TEXT NOT NULL REFERENCES context_review_runs(review_id),
 account_scope TEXT NOT NULL,
 rule_version INTEGER NOT NULL,
 code_sha TEXT NOT NULL,
 input_hash TEXT NOT NULL,
 binding_json TEXT NOT NULL,
 results_json TEXT NOT NULL,
 mode TEXT NOT NULL CHECK(mode IN ('EVALUATION','RUNTIME')),
 status TEXT NOT NULL CHECK(status IN ('VALIDATING','COMPLETED')),
 research_id TEXT REFERENCES research_questions(research_id),
 created_at TEXT NOT NULL,
 UNIQUE(review_id,rule_version,input_hash)
);
CREATE TABLE revalidation_claims (
 revalidation_id TEXT NOT NULL REFERENCES review_revalidations(revalidation_id),
 candidate_index INTEGER NOT NULL,
 claim_id TEXT NOT NULL REFERENCES claims(claim_id) DEFERRABLE INITIALLY DEFERRED,
 PRIMARY KEY(revalidation_id,candidate_index)
);
