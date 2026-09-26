"""Private local Work-assisted context review. No model or browser operations."""

from copy import deepcopy
import json
from typing import Any

from travel_agent.domain.models import EvidenceBundle
from .canonical import canonicalize
from .content_store import audit_grounding
from .extractor import EvidenceExtractor, build_claim
from .grounding import CONTEXT_REASONS, REVIEW_DIMENSIONS, check_grounding, context_hazard
from .model_input import outbound_blocks
from .models import ResearchReport, ResearchRequest
from .planning import SufficiencyEvaluator
from .recovery import ExtractionRecovery
from .store import EvidenceStore


def review_candidates(store: EvidenceStore, *, attempt_id: str, account_scope: str,
                      decisions: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Accept only locator-valid, explicitly reviewed rows; transaction includes lineage."""
    con = store.db.connection
    with store.db.transaction():
        attempt = con.execute("SELECT a.*,b.account_scope,r.research_id,q.current_revision,q.request_json "
            "FROM extraction_attempts a JOIN extraction_batches b USING(batch_id) JOIN research_runs r USING(run_id) "
            "JOIN research_questions q USING(research_id) WHERE attempt_id=?", (attempt_id,)).fetchone()
        if (attempt is None or attempt["account_scope"] != account_scope
            or attempt["revision"] != attempt["current_revision"]
            or attempt["status"] not in {"PENDING_REVIEW", "PARTIAL_SUCCESS", "SUCCEEDED", "NO_ACCEPTED_EVIDENCE"}):
            raise ValueError("REVIEW_SCOPE_REVISION_OR_STATE_DENIED")
        source_row = con.execute("SELECT source_id FROM source_contents WHERE content_id=?", (attempt["content_id"],)).fetchone()
        content = next((c for c in store.contents.load(source_row[0], account_scope)
                        if c["content_id"] == attempt["content_id"]), None)
        if (content is None or content["content_hash"] != attempt["content_hash"]
            or content["normalization_version"] != attempt["normalization_version"]):
            raise ValueError("REVIEW_SNAPSHOT_MISMATCH")
        policy = store._latest_policy(content["policy_id"])
        source = store.repository.get(content["source_id"], account_scope)
        if policy is None or source is None:
            raise PermissionError("REVIEW_POLICY_DENIED")
        view = canonicalize(content["raw_text"], content["dom_text"], completeness=content["content_completeness"])
        sent_ids = {b.block_index for b in outbound_blocks(view.blocks)}
        rows = con.execute("SELECT * FROM extraction_candidates WHERE attempt_id=? ORDER BY candidate_index", (attempt_id,)).fetchall()
        if not set(decisions) <= {r["candidate_index"] for r in rows}:
            raise ValueError("UNKNOWN_REVIEW_CANDIDATE")
        rejected_conditions = {c["source_block_id"] for r in rows if r["context_status"] == "REJECTED"
                               or decisions.get(r["candidate_index"], {}).get("action") == "REJECT"
                               for c in json.loads(r["candidate_json"])["applicable_conditions"]}
        request = ResearchRequest(**json.loads(attempt["request_json"]))
        run = store.begin(attempt["research_id"], attempt["revision"], request.to_dict(), account_scope)
        store.register_policy(run, attempt["revision"], policy)
        con.execute("INSERT OR IGNORE INTO research_run_contents VALUES(?,?)", (run, content["content_id"]))
        for row in rows:
            index = row["candidate_index"]
            if index not in decisions:
                continue
            decision = decisions[index]
            if set(decision) - {"action", "reason_code", "dimension_checks", "context_conditions", "dependency_resolution",
                                "route_association", "reference_scope"}:
                raise ValueError("UNKNOWN_REVIEW_FIELD")
            if row["review_json"]:
                if json.loads(row["review_json"]) != decision:
                    raise ValueError("REVIEW_ALREADY_FINAL")
                continue
            action, reason = decision["action"], decision["reason_code"]
            if action not in {"ACCEPT", "REJECT"} or reason not in CONTEXT_REASONS:
                raise ValueError("INVALID_CONTEXT_DECISION")
            if action == "REJECT" and set(decision) != {"action", "reason_code"}:
                raise ValueError("REJECT_REVIEW_CONTAINS_UNNECESSARY_DATA")
            if action == "REJECT" and reason in {"WORK_CONTEXT_VERIFIED", "CONTEXT_REVIEW_REQUIRED", "DEPENDENCY_INDEPENDENT"}:
                raise ValueError("INVALID_REJECTION_REASON")
            if decision.get("dependency_resolution") not in {None, "INDEPENDENT"}:
                raise ValueError("INVALID_DEPENDENCY_RESOLUTION")
            if row["context_status"] != "PENDING":
                raise ValueError("REJECTED_LOCATOR_CANNOT_BE_APPROVED")
            claim_id = None
            if action == "ACCEPT":
                if reason != "WORK_CONTEXT_VERIFIED" or decision.get("dimension_checks") != {k: True for k in REVIEW_DIMENSIONS}:
                    raise ValueError("CONTEXT_REVIEW_INCOMPLETE")
                candidate = deepcopy(json.loads(row["candidate_json"]))
                if set(candidate["source_block_ids"]) & rejected_conditions and decision.get("dependency_resolution") != "INDEPENDENT":
                    raise ValueError("DEPENDENCY_UNRESOLVED")
                context_conditions = list(decision.get("context_conditions", []))
                association = decision.get("route_association")
                if association is not None:
                    if set(association) != {"object_quote", "object_block_id", "scope"}:
                        raise ValueError("INVALID_ROUTE_ASSOCIATION")
                    context_conditions.append({"text": association["object_quote"], "quote": association["object_quote"],
                                               "source_block_id": association["object_block_id"]})
                for condition in context_conditions:
                    if set(condition) != {"source_block_id", "text", "quote"}:
                        raise ValueError("INVALID_CONTEXT_ANCHOR")
                    if condition not in candidate["applicable_conditions"]:
                        candidate["applicable_conditions"].append(condition)
                    if condition["source_block_id"] not in candidate["source_block_ids"]:
                        candidate["source_block_ids"].append(condition["source_block_id"])
                checked = check_grounding(candidate, view.blocks, sent_ids)
                if not checked.passed or context_hazard(candidate, view.blocks):
                    raise ValueError("REVIEW_CONTEXT_NOT_GROUNDED")
                claim, metadata = build_claim(candidate, checked, view, content["source_id"], attempt["extraction_mode"])
                metadata.update(context_review_status="WORK_REVIEWED", grounding_rule_version=2,
                                audit_attempt_id=attempt_id, audit_candidate_index=index)
                if decision.get("reference_scope"):
                    metadata["reference_scope"] = decision["reference_scope"]
                if association is not None:
                    block = view.blocks[association["object_block_id"]]
                    low = block.start + block.text.index(association["object_quote"])
                    metadata["route_association"] = {**association, "source_id": content["source_id"],
                        "object_locator": block.locator.rsplit(":chars:", 1)[0] +
                        f":chars:{low}-{low + len(association['object_quote'])}"}
                data = source.to_dict() | {"claims": [claim], "claim_metadata": {claim["claim_id"]: metadata},
                    "missing_fields": [g for g in source["missing_fields"] if g not in {"NO_GROUNDED_CLAIMS", "LOCAL_EXTRACTIVE_ONLY"}]}
                bundle = EvidenceBundle(data)
                if audit_grounding(bundle, (content,))["unsupported"]:
                    raise ValueError("REVIEW_LINEAGE_INVALID")
                store.save_evidence(run, attempt["revision"], bundle, policy,
                                    {"identity_match": True}, merge_reviewed=True)
                claim_id = claim["claim_id"]
            con.execute("UPDATE extraction_candidates SET context_status=?,context_reason=?,review_json=?,claim_id=? "
                        "WHERE attempt_id=? AND candidate_index=?", ("ACCEPTED" if action == "ACCEPT" else "REJECTED",
                        reason, json.dumps(decision, ensure_ascii=False), claim_id, attempt_id, index))
        # Reject orphan links: an accepted ROUTE must attest the same source/object.
        reviewed_source = store.repository.get(content["source_id"], account_scope)
        if reviewed_source is not None:
            assessments = reviewed_source.get("claim_metadata", {})
            route_objects = {assessments[c["claim_id"]]["route_association"]["object_locator"]
                for c in reviewed_source["claims"] if c["topic"] == "ROUTE"
                and assessments.get(c["claim_id"], {}).get("route_association")}
            if any(m["route_association"]["object_locator"] not in route_objects
                   for m in assessments.values() if m.get("route_association")):
                raise ValueError("ROUTE_ASSOCIATION_WITHOUT_ACCEPTED_ROUTE")
        recovery = ExtractionRecovery(store, EvidenceExtractor())
        outcome = recovery.outcome(attempt_id)
        counts = outcome["counts"]
        status = ("PARTIAL_SUCCESS" if counts["persisted_evidence"] and
                  (counts["rejected_candidates"] or counts["context_review_pending"]) else
                  "SUCCEEDED" if counts["persisted_evidence"] else "PENDING_REVIEW" if
                  counts["context_review_pending"] else "NO_ACCEPTED_EVIDENCE")
        con.execute("UPDATE extraction_attempts SET status=?,finished_at=? WHERE attempt_id=?", (status, store.db.stamp(), attempt_id))
    # Rendering/presentation failure cannot roll back accepted evidence or its lineage.
    evidence = store.lookup(attempt["research_id"], request.destination, account_scope)
    gaps = SufficiencyEvaluator(clock=store.db.clock).gaps(request, evidence)
    report = ResearchReport(attempt["research_id"], attempt["revision"], run, request, evidence, gaps,
        "BUDGET_EXHAUSTED" if gaps else "EVIDENCE_SUFFICIENT", {"search": 0, "detail": 0}, len(evidence),
        assessed_at=store.db.stamp(), extraction_results=({"status": status, **counts},))
    store.finish(run, attempt["revision"], [g.to_dict() for g in gaps], report.safe_summary())
    return recovery.outcome(attempt_id) | {"summary": report.safe_summary()}
