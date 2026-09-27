-- Versioned derived knowledge; source identity survives explicit raw cleanup.
CREATE TABLE knowledge_cards (
 card_id TEXT NOT NULL, version INTEGER NOT NULL, account_scope TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('SOURCE_REFERENCE','PLACE_LEAD','PLAN_PATTERN')),
 status TEXT NOT NULL CHECK(status IN ('ACTIVE','DELETED')), destination TEXT NOT NULL,
 test_input INTEGER NOT NULL, created_at TEXT NOT NULL, card_hash TEXT NOT NULL,
 data_json TEXT NOT NULL, PRIMARY KEY(card_id,version)
);
CREATE TABLE knowledge_terms (
 term TEXT NOT NULL, card_id TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(term,card_id,version),
 FOREIGN KEY(card_id,version) REFERENCES knowledge_cards(card_id,version) ON DELETE CASCADE
);
CREATE INDEX knowledge_terms_card ON knowledge_terms(card_id,version);
CREATE INDEX knowledge_scope ON knowledge_cards(account_scope,destination,status);
CREATE TABLE knowledge_raw_state (
 content_id TEXT PRIMARY KEY, state TEXT NOT NULL CHECK(state IN ('AVAILABLE','USER_CLEARED','UNEXPECTED_CHANGE')),
 cleanup_policy TEXT NOT NULL DEFAULT 'PERSISTENT', changed_at TEXT NOT NULL
);
CREATE TABLE knowledge_withdrawals (
 account_scope TEXT NOT NULL, source_id TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(account_scope,source_id)
);
CREATE TRIGGER knowledge_raw_changed AFTER UPDATE OF raw_text,dom_text,normalized_text,content_hash ON source_contents
WHEN EXISTS(SELECT 1 FROM knowledge_raw_state WHERE content_id=OLD.content_id AND state='AVAILABLE')
BEGIN
 UPDATE knowledge_raw_state SET state='UNEXPECTED_CHANGE' WHERE content_id=OLD.content_id;
END;
CREATE TRIGGER knowledge_blocks_deleted AFTER DELETE ON source_body_blocks
BEGIN
 UPDATE knowledge_raw_state SET state='UNEXPECTED_CHANGE' WHERE content_id=OLD.content_id AND state='AVAILABLE';
END;
CREATE TRIGGER knowledge_blocks_changed AFTER UPDATE ON source_body_blocks
BEGIN
 UPDATE knowledge_raw_state SET state='UNEXPECTED_CHANGE' WHERE content_id=OLD.content_id AND state='AVAILABLE';
END;
CREATE TRIGGER knowledge_blocks_added AFTER INSERT ON source_body_blocks
BEGIN
 UPDATE knowledge_raw_state SET state='UNEXPECTED_CHANGE' WHERE content_id=NEW.content_id AND state='AVAILABLE';
END;
