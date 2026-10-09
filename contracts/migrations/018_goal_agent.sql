-- Preserve all old rows/usage. Legacy single research jobs retain their uniqueness;
-- versioned agent steps and one-call agent model jobs share the SAME grant ledger.
DROP INDEX one_live_preview_job;
CREATE UNIQUE INDEX one_live_preview_job ON preview_jobs(continuation_id)
    WHERE research_id NOT LIKE 'planning-%'
      AND research_id NOT LIKE 'agent-%'
      AND research_id NOT LIKE 'research-step-%';
CREATE UNIQUE INDEX one_active_agent_child ON preview_jobs(continuation_id)
    WHERE status IN ('QUEUED','RUNNING','WAITING_LOGIN')
      AND (research_id LIKE 'agent-%' OR research_id LIKE 'research-step-%');
