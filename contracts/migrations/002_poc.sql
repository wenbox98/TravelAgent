-- v2: preserve v1 data; extend evidence for v1.1 without storing locators/tokens.
ALTER TABLE sources ADD COLUMN source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('UNKNOWN','XHS','OFFICIAL','USER','SYNTHETIC'));
ALTER TABLE sources ADD COLUMN destination TEXT;
ALTER TABLE sources ADD COLUMN applicable_conditions_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(applicable_conditions_json));
ALTER TABLE sources ADD COLUMN missing_fields_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(missing_fields_json));
ALTER TABLE claims ADD COLUMN confidence REAL CHECK(confidence IS NULL OR (confidence>=0 AND confidence<=1));
UPDATE sources SET source_type='SYNTHETIC' WHERE is_synthetic=1;
UPDATE sources SET completeness=CASE completeness WHEN 'FULL' THEN 'FULL_TEXT' WHEN 'PARTIAL' THEN 'PARTIAL_TEXT' WHEN 'SUMMARY' THEN 'SUMMARY_ONLY' WHEN 'METADATA' THEN 'METADATA_ONLY' ELSE completeness END;
CREATE TRIGGER sources_completeness_insert BEFORE INSERT ON sources WHEN NEW.completeness NOT IN ('FULL_TEXT','PARTIAL_TEXT','SUMMARY_ONLY','METADATA_ONLY') BEGIN SELECT RAISE(ABORT,'invalid completeness'); END;
CREATE TRIGGER sources_completeness_update BEFORE UPDATE OF completeness ON sources WHEN NEW.completeness NOT IN ('FULL_TEXT','PARTIAL_TEXT','SUMMARY_ONLY','METADATA_ONLY') BEGIN SELECT RAISE(ABORT,'invalid completeness'); END;
