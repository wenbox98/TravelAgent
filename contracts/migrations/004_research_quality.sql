-- Optional, schema-validated per-claim provenance. No source body or access locator.
ALTER TABLE sources ADD COLUMN claim_metadata_json TEXT
    CHECK(claim_metadata_json IS NULL OR
          (json_valid(claim_metadata_json) AND json_type(claim_metadata_json) = 'object'));

CREATE TABLE research_constraints (
    research_id TEXT NOT NULL REFERENCES research_questions(research_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    name TEXT NOT NULL,
    value_json TEXT NOT NULL CHECK(json_valid(value_json)),
    provenance TEXT NOT NULL CHECK(provenance = 'USER'),
    PRIMARY KEY(research_id, revision, name)
);

-- Report text is reconstructed from permitted Evidence, never duplicated here.
CREATE TABLE research_reports (
    run_id TEXT PRIMARY KEY REFERENCES research_runs(run_id) ON DELETE CASCADE,
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    source_handles_json TEXT NOT NULL CHECK(json_valid(source_handles_json)),
    claim_handles_json TEXT NOT NULL CHECK(json_valid(claim_handles_json)),
    created_at TEXT NOT NULL
);
