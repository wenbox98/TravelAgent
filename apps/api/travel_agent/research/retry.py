"""Explicit model-only retry of one durable attempt. This module never imports XHS."""

import json
from typing import Any

from travel_agent.domain.models import SourcePolicy
from .extractor import EvidenceExtractor
from .models import ResearchReport, ResearchRequest
from .planning import SufficiencyEvaluator
from .recovery import ExtractionRecovery
from .store import EvidenceStore


def retry_saved(store: EvidenceStore, extractor: EvidenceExtractor, *, attempt_id: str,
                fix_commit: str) -> dict[str, Any]:
    con = store.db.connection
    row = con.execute("SELECT a.*,b.account_scope,b.max_attempts,r.research_id,q.current_revision,q.request_json "
                      "FROM extraction_attempts a JOIN extraction_batches b USING(batch_id) "
                      "JOIN research_runs r USING(run_id) JOIN research_questions q USING(research_id) "
                      "WHERE attempt_id=?", (attempt_id,)).fetchone()
    if row is None or row["revision"] != row["current_revision"]:
        raise ValueError("RECOVERY_ATTEMPT_MISSING_OR_OBSOLETE")
    source = con.execute("SELECT policy_id FROM source_contents WHERE content_id=?",
                         (row["content_id"],)).fetchone()
    if source is None:
        raise ValueError("SOURCE_NOT_RESTORED")
    policy = store._latest_policy(source[0])
    if not isinstance(policy, SourcePolicy):
        raise PermissionError("SOURCE_POLICY_MISSING")
    request = ResearchRequest(**json.loads(row["request_json"]))
    run = store.begin(row["research_id"], row["revision"], request.to_dict(), row["account_scope"])
    store.register_policy(run, row["revision"], policy)
    outcome = ExtractionRecovery(store, extractor).execute(
        run_id=run, revision=row["revision"], content_id=row["content_id"],
        account_scope=row["account_scope"], policy=policy, batch_id=row["batch_id"],
        max_attempts=row["max_attempts"], retry_fix_commit=fix_commit)
    evidence = store.lookup(row["research_id"], request.destination, row["account_scope"])
    gaps = SufficiencyEvaluator(clock=store.db.clock).gaps(request, evidence)
    report = ResearchReport(row["research_id"], row["revision"], run, request, evidence, gaps,
        "ERROR" if outcome["status"] != "SUCCEEDED" else "BUDGET_EXHAUSTED" if gaps else "EVIDENCE_SUFFICIENT",
        {"search": 0, "detail": 0}, len(evidence), assessed_at=store.db.stamp(),
        extraction_diagnostics=(outcome["diagnostic"],) if outcome.get("diagnostic") else ())
    store.finish(run, row["revision"], [g.to_dict() for g in gaps], report.safe_summary())
    return {k: v for k, v in outcome.items() if k != "result"} | {
        "summary": report.safe_summary(), "xhs_calls": {"connect": 0, "search": 0, "detail": 0},
        "browser_sessions": 0}
