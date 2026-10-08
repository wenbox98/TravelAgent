-- One explicit user intent owns one durable orchestration and finite grant.
-- Old evidence, selections, grants and operation counts are unchanged.
CREATE TABLE planning_tasks (
    task_id TEXT PRIMARY KEY,
    account_scope TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES preview_sessions(session_id),
    request_revision INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    grant_id TEXT,
    research_job_id TEXT,
    planning_job_id TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(account_scope,idempotency_key)
);
CREATE UNIQUE INDEX one_active_planning_task ON planning_tasks(session_id)
    WHERE status IN ('QUEUED','RUNNING','WAITING_CONFIGURATION');
