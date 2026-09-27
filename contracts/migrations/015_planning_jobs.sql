-- Existing P02 grant still allows only one research job. Planning jobs use the
-- same job table and durable continuation counters, with their own fixed limit.
DROP INDEX one_live_preview_job;
CREATE UNIQUE INDEX one_live_preview_job ON preview_jobs(continuation_id)
    WHERE research_id NOT LIKE 'planning-%';
