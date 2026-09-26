"""Source-first extraction and explicit, budgeted model-only recovery. No XHS imports."""

import json
import re
from asyncio import CancelledError
from typing import Any
from uuid import uuid4

from travel_agent.domain.models import SourcePolicy, validator
from travel_agent.providers.diagnostics import Diagnostic
from travel_agent.providers.llm import OpenAICompatibleProvider
from .content_store import audit_grounding
from .extractor import EvidenceExtractor, ExtractionResult
from .store import EvidenceStore
from .grounding import context_hazard

EXTRACTION_VERSION = 2


class ExtractionRecovery:
    def __init__(self, store: EvidenceStore, extractor: EvidenceExtractor) -> None:
        self.store, self.extractor = store, extractor

    def execute(self, *, run_id: str, revision: int, content_id: str, account_scope: str,
                policy: SourcePolicy, batch_id: str, max_attempts: int,
                research_gaps: tuple[str, ...] = (), retry_fix_commit: str | None = None) -> dict[str, Any]:
        db = self.store.db
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", batch_id) or not 1 <= max_attempts <= 12:
            raise ValueError("INVALID_EXTRACTION_BATCH")
        if retry_fix_commit is not None and re.fullmatch(r"[a-f0-9]{40}", retry_fix_commit) is None:
            raise ValueError("RETRY_REQUIRES_FIX_COMMIT")
        row = db.connection.execute("SELECT source_id FROM source_contents WHERE content_id=? AND account_scope=?",
                                    (content_id, account_scope)).fetchone()
        if row is None:
            raise ValueError("SOURCE_NOT_RESTORED")
        source_id = row[0]
        content = next((c for c in self.store.contents.load(source_id, account_scope)
                        if c["content_id"] == content_id), None)
        source = self.store.repository.get(source_id, account_scope)
        if content is None or source is None or content["policy_id"] != policy["policy_id"]:
            raise PermissionError("SOURCE_RESTORE_POLICY_DENIED")
        with db.transaction() as con:
            if not self.store.is_current(run_id, revision):
                raise ValueError("STALE_REVISION")
            owner = con.execute("SELECT q.account_scope FROM research_runs r JOIN research_questions q "
                                "ON q.research_id=r.research_id WHERE r.run_id=?", (run_id,)).fetchone()
            if owner[0] != account_scope:
                raise PermissionError("SCOPE_MISMATCH")
            previous_batch = con.execute("SELECT batch_id FROM extraction_attempts WHERE content_id=? LIMIT 1", (content_id,)).fetchone()
            if previous_batch is not None and previous_batch[0] != batch_id:
                raise ValueError("CONTENT_BATCH_IMMUTABLE")
            con.execute("INSERT OR IGNORE INTO extraction_batches VALUES(?,?,?)", (batch_id, account_scope, max_attempts))
            batch = con.execute("SELECT * FROM extraction_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch["account_scope"] != account_scope or batch["max_attempts"] != max_attempts:
                raise ValueError("BATCH_BUDGET_IMMUTABLE")
            prior = con.execute("SELECT * FROM extraction_attempts WHERE batch_id=? AND content_id=? "
                                "AND authorization_id IS NULL "
                                "ORDER BY attempt_number DESC LIMIT 1",
                                (batch_id, content_id)).fetchone()
            if prior is not None and prior["content_hash"] != content["content_hash"]:
                raise ValueError("SNAPSHOT_IDENTITY_MISMATCH")
            if prior is not None and prior["status"] in {"SUCCEEDED", "PARTIAL_SUCCESS", "PENDING_REVIEW", "NO_ACCEPTED_EVIDENCE"}:
                return self.outcome(prior["attempt_id"], cache_hit=True)
            total = con.execute("SELECT count(*) FROM extraction_attempts WHERE batch_id=? AND authorization_id IS NULL", (batch_id,)).fetchone()[0]
            retried = con.execute("SELECT count(*) FROM extraction_attempts WHERE batch_id=? AND attempt_number=2",
                                  (batch_id,)).fetchone()[0]
            if total >= max_attempts or prior is not None and (retry_fix_commit is None or retried or prior["attempt_number"] >= 2):
                raise ValueError("MODEL_ATTEMPT_BUDGET_OR_RETRY_DENIED")
            attempt_id = "extract-" + uuid4().hex
            con.execute("INSERT INTO extraction_attempts VALUES(?,?,?,?,?,?,?,?,'PENDING',NULL,?,?,NULL,?,NULL,NULL)",
                        (attempt_id, batch_id, run_id, revision, content_id, content["normalization_version"],
                         EXTRACTION_VERSION, 1 if prior is None else 2, retry_fix_commit, db.stamp(), content["content_hash"]))
            con.execute("INSERT OR IGNORE INTO research_run_contents VALUES(?,?)", (run_id, content_id))
        # PENDING and the source transaction are durable before dispatch.
        return self.run_reserved(attempt_id, research_gaps=research_gaps)

    def run_reserved(self, attempt_id: str, *, research_gaps: tuple[str, ...] = ()) -> dict[str, Any]:
        """Only one process may transition a durable reservation to RUNNING."""
        db = self.store.db
        attempt = db.connection.execute("SELECT a.*,b.account_scope FROM extraction_attempts a "
            "JOIN extraction_batches b USING(batch_id) WHERE attempt_id=?", (attempt_id,)).fetchone()
        if attempt is None:
            raise ValueError("MISSING_RESERVED_ATTEMPT")
        run_id, revision = attempt["run_id"], attempt["revision"]
        source_row = db.connection.execute("SELECT source_id,policy_id FROM source_contents WHERE content_id=?",
                                           (attempt["content_id"],)).fetchone()
        if source_row is None:
            raise ValueError("RESERVED_SOURCE_MISSING")
        source_id = source_row["source_id"]
        content = next((c for c in self.store.contents.load(source_id, attempt["account_scope"])
                        if c["content_id"] == attempt["content_id"]), None)
        source = self.store.repository.get(source_id, attempt["account_scope"])
        policy = self.store._latest_policy(source_row["policy_id"])
        if (content is None or source is None or policy is None
            or content["content_hash"] != attempt["content_hash"]
            or content["normalization_version"] != attempt["normalization_version"]):
            raise ValueError("RESERVED_SNAPSHOT_OR_POLICY_MISMATCH")
        with db.transaction() as con:
            current = con.execute("SELECT status FROM extraction_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            if current[0] != "PENDING":
                raise ValueError("RESERVATION_ALREADY_CLAIMED")
            if not self.store.is_current(run_id, revision):
                con.execute("UPDATE extraction_attempts SET status='OBSOLETE',finished_at=? WHERE attempt_id=?",
                            (db.stamp(), attempt_id))
                return self.outcome(attempt_id)
            con.execute("UPDATE extraction_attempts SET status='RUNNING' WHERE attempt_id=?", (attempt_id,))
        provider = self.extractor.provider
        def checkpoint(safe: dict[str, Any]) -> None:
            validator("LLMDiagnostic").validate(safe)
            with db.transaction() as con:
                updated = con.execute("UPDATE extraction_attempts SET diagnostic_json=? WHERE attempt_id=? AND status='RUNNING'",
                                      (json.dumps(safe), attempt_id)).rowcount
                if updated != 1:
                    raise ValueError("ATTEMPT_NO_LONGER_RUNNING")
                if attempt["authorization_id"] and safe["http_attempts"]:
                    con.execute("UPDATE extraction_authorizations SET dispatch_started_at=coalesce(dispatch_started_at,?) "
                                "WHERE authorization_id=?", (db.stamp(), attempt["authorization_id"]))
        if isinstance(provider, OpenAICompatibleProvider):
            provider.diagnostic_observer = checkpoint
        result: ExtractionResult | None = None
        diagnostic = Diagnostic()
        status = "FAILED"
        try:
            result = self.extractor.extract(source_id=source_id, source_title=source["source_title"],
                body=content["raw_text"], dom_body=content["dom_text"], completeness=content["content_completeness"],
                fetched_at=content["retrieved_at"], source_published_at=content["published_at"],
                source_type=source["source_type"], destination=source["destination"], policy=policy,
                image_count=content["image_count"], research_gaps=research_gaps, allow_fallback=False)
            diagnostic = result.diagnostic or Diagnostic(stage="POLICY", category="POLICY_BLOCKED")
            diagnostic.retry_count = int(attempt["attempt_number"] == 2)
            validator("LLMDiagnostic").validate(diagnostic.safe_dict())
            valid_response = result.mode in {"LLM", "MOCK"}
            if valid_response and audit_grounding(result.bundle, (content,))["unsupported"]:
                raise ValueError("SNAPSHOT_GROUNDING_MISMATCH")
            with db.transaction() as con:
                if not self.store.is_current(run_id, revision):
                    status = "OBSOLETE"
                elif valid_response:
                    for row, check in zip(result.candidate_rows, result.candidate_checks, strict=True):
                        hazard = context_hazard(row, result.blocks) if check["passed"] else None
                        rejected = not check["passed"] or hazard is not None
                        con.execute("INSERT INTO extraction_candidates VALUES(?,?,?,?,?,?,NULL,NULL)",
                            (attempt_id, check["candidate_index"], json.dumps(row, ensure_ascii=False),
                             json.dumps(check), "REJECTED" if rejected else "PENDING",
                             hazard or ("CONTEXT_REVIEW_REQUIRED" if check["passed"] else check["reason_code"])))
                    pending = con.execute("SELECT count(*) FROM extraction_candidates WHERE attempt_id=? "
                                          "AND context_status='PENDING'", (attempt_id,)).fetchone()[0]
                    status = "PENDING_REVIEW" if pending else "NO_ACCEPTED_EVIDENCE"
                con.execute("UPDATE extraction_attempts SET status=?,diagnostic_json=?,finished_at=?,extraction_mode=? "
                            "WHERE attempt_id=?", (status, json.dumps(diagnostic.safe_dict()), db.stamp(), result.mode, attempt_id))
        except BaseException as error:
            status = "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit, CancelledError)) else "FAILED"
            with db.transaction() as con:
                con.execute("UPDATE extraction_attempts SET status=?,diagnostic_json=?,finished_at=? WHERE attempt_id=?",
                            (status, json.dumps(Diagnostic().safe_dict()), db.stamp(), attempt_id))
            if not isinstance(error, Exception):
                raise
            result = None
            diagnostic = Diagnostic()
        return self.outcome(attempt_id) | {"result": result}

    def outcome(self, attempt_id: str, *, cache_hit: bool = False) -> dict[str, Any]:
        row = self.store.db.connection.execute("SELECT * FROM extraction_attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
        candidates = self.store.db.connection.execute("SELECT * FROM extraction_candidates WHERE attempt_id=? "
                                                       "ORDER BY candidate_index", (attempt_id,)).fetchall()
        checks = [{**json.loads(c["locator_json"]), "context_status": c["context_status"],
                   "context_reason": c["context_reason"]} for c in candidates]
        diagnostic = json.loads(row["diagnostic_json"]) if row["diagnostic_json"] else None
        diagnostic_counts = diagnostic or {}
        contaminated = bool(diagnostic and diagnostic["category"] == "POLICY_BLOCKED")
        return {"status": row["status"], "cache_hit": cache_hit, "attempt_id": attempt_id,
                "diagnostic": diagnostic,
                "candidate_checks": checks, "counts": {
                    "generated_candidates": (diagnostic_counts.get("generated_claims") or 0) if contaminated else len(candidates),
                    "locator_passed_candidates": sum(c["passed"] for c in checks),
                    "rejected_candidates": (diagnostic_counts.get("rejected_claims") or 0) if contaminated else sum(c["context_status"] == "REJECTED" for c in checks),
                    "context_review_pending": sum(c["context_status"] == "PENDING" for c in checks),
                    "persisted_evidence": len({c["claim_id"] for c in candidates if c["claim_id"]}),
                }, "result": None}
