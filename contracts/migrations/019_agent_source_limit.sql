-- Executed in the database migration's atomic parent-rebuild transaction.
-- Existing batch values and all child attempts/authorizations stay unchanged.
-- This bounds distinct source analysis reservations, not total LLM calls.
CREATE TABLE extraction_batches_v19 (
    batch_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 20)
);
INSERT INTO extraction_batches_v19 SELECT * FROM extraction_batches;
DROP TABLE extraction_batches;
ALTER TABLE extraction_batches_v19 RENAME TO extraction_batches;
