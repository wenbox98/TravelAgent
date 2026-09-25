"""Source-first extraction and explicit, budgeted model-only recovery. No XHS imports."""

import json
import re
from asyncio import CancelledError
from typing import Any
from uuid import uuid4

from travel_agent.domain.models import SourcePolicy, validator
from travel_agent.providers.diagnostics import Diagnostic
from .content_store import audit_grounding
from .extractor import EvidenceExtractor, ExtractionResult
from .store import EvidenceStore

EXTRACTION_VERSION = 1


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
            con.execute("INSERT OR IGNORE INTO extraction_batches VALUES(?,?,?)", (batch_id, account_scope, max_attempts))
            batch = con.execute("SELECT * FROM extraction_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch["account_scope"] != account_scope or batch["max_attempts"] != max_attempts:
                raise ValueError("BATCH_BUDGET_IMMUTABLE")
            prior = con.execute("SELECT * FROM extraction_attempts WHERE batch_id=? AND content_id=? "
                                "AND extraction_version=? ORDER BY attempt_number DESC LIMIT 1",
                                (batch_id, content_id, EXTRACTION_VERSION)).fetchone()
            if prior is not None and prior["status"] == "SUCCEEDED":
                return {"status": "SUCCEEDED", "cache_hit": True, "attempt_id": prior["attempt_id"],
                        "diagnostic": json.loads(prior["diagnostic_json"]), "result": None}
            total = con.execute("SELECT count(*) FROM extraction_attempts WHERE batch_id=?", (batch_id,)).fetchone()[0]
            retried = con.execute("SELECT count(*) FROM extraction_attempts WHERE batch_id=? AND attempt_number=2",
                                  (batch_id,)).fetchone()[0]
            if total >= max_attempts or prior is not None and (retry_fix_commit is None or retried or prior["attempt_number"] >= 2):
                raise ValueError("MODEL_ATTEMPT_BUDGET_OR_RETRY_DENIED")
            attempt_id = "extract-" + uuid4().hex
            con.execute("INSERT INTO extraction_attempts VALUES(?,?,?,?,?,?,?,?,'PENDING',NULL,?,?,NULL)",
                        (attempt_id, batch_id, run_id, revision, content_id, content["normalization_version"],
                         EXTRACTION_VERSION, 1 if prior is None else 2, retry_fix_commit, db.stamp()))
            con.execute("INSERT OR IGNORE INTO research_run_contents VALUES(?,?)", (run_id, content_id))
        # PENDING and the source transaction are durable before dispatch.
        with db.transaction() as con:
            if not self.store.is_current(run_id, revision):
                con.execute("UPDATE extraction_attempts SET status='OBSOLETE',finished_at=? WHERE attempt_id=?",
                            (db.stamp(), attempt_id))
                return {"status": "OBSOLETE", "attempt_id": attempt_id, "result": None}
            con.execute("UPDATE extraction_attempts SET status='RUNNING' WHERE attempt_id=?", (attempt_id,))
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
            diagnostic.retry_count = 0 if prior is None else 1
            validator("LLMDiagnostic").validate(diagnostic.safe_dict())
            audited = audit_grounding(result.bundle, (content,))
            success = (result.mode in {"LLM", "MOCK"} and bool(result.bundle["claims"])
                       and result.rejected_claims == 0 and audited["unsupported"] == 0)
            with db.transaction() as con:
                if not self.store.is_current(run_id, revision):
                    status = "OBSOLETE"
                elif success:
                    self.store.save_evidence(run_id, revision, result.bundle, policy, {"identity_match": True,
                        "extraction_mode": result.mode, "evidence_count": len(result.bundle["claims"])})
                    status = "SUCCEEDED"
                con.execute("UPDATE extraction_attempts SET status=?,diagnostic_json=?,finished_at=? WHERE attempt_id=?",
                            (status, json.dumps(diagnostic.safe_dict()), db.stamp(), attempt_id))
        except BaseException as error:
            status = "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit, CancelledError)) else "FAILED"
            with db.transaction() as con:
                con.execute("UPDATE extraction_attempts SET status=?,diagnostic_json=?,finished_at=? WHERE attempt_id=?",
                            (status, json.dumps(Diagnostic().safe_dict()), db.stamp(), attempt_id))
            if not isinstance(error, Exception):
                raise
            result = None
            diagnostic = Diagnostic()
        return {"status": status, "cache_hit": False, "attempt_id": attempt_id,
                "diagnostic": diagnostic.safe_dict(), "result": result}
