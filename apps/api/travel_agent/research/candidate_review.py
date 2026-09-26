"""Private local Work-assisted context review. No model or browser operations."""

from copy import deepcopy
import json
from typing import Any

from travel_agent.domain.models import EvidenceBundle
from .canonical import canonicalize, evidence_key
from .content_store import audit_grounding
from .extractor import EvidenceExtractor, build_claim
from .grounding import CONTEXT_REASONS, REVIEW_DIMENSIONS, check_grounding, context_hazard
from .model_input import outbound_blocks
from .models import ResearchReport, ResearchRequest
from .planning import SufficiencyEvaluator
from .recovery import ExtractionRecovery
from .store import EvidenceStore
from .references import catalog, materialize, validate_reference, REFERENCE_KINDS


def review_candidates(store: EvidenceStore, *, attempt_id: str, account_scope: str,
                      decisions: dict[int, dict[str, Any]], model_review_id: str | None = None,
                      revalidation_id: str | None = None) -> dict[str, Any]:
    """Accept only locator-valid, explicitly reviewed rows; transaction includes lineage."""
    con = store.db.connection
    with store.db.transaction():
        local = None
        if revalidation_id:
            from .review_replay import verify_record
            local = verify_record(store, revalidation_id, account_scope)
            if local['status'] != 'VALIDATING' or model_review_id:
                raise ValueError('LOCAL_REVALIDATION_STATE_DENIED')
            parent = con.execute('SELECT attempt_id FROM context_review_runs WHERE review_id=?', (local['review_id'],)).fetchone()
            approved = {i['candidate_index']: i for i in json.loads(local['results_json'])}
            if parent[0] != attempt_id or any(not approved.get(i, {}).get('eligible') or approved[i]['program'] != d for i, d in decisions.items()):
                raise ValueError('LOCAL_REVALIDATION_DECISION_MISMATCH')
        if model_review_id is not None:
            review = con.execute("SELECT * FROM context_review_runs WHERE review_id=? AND attempt_id=? AND account_scope=? "
                "AND mode='RUNTIME' AND status='COMPLETED'", (model_review_id,attempt_id,account_scope)).fetchone()
            if review is None:
                raise ValueError('MODEL_REVIEW_LINEAGE_REQUIRED')
            approved = {i['candidate_index']:i['program'] for i in json.loads(review['results_json'])}
            if any(approved.get(i) != d for i,d in decisions.items()):
                raise ValueError('MODEL_REVIEW_DECISION_MISMATCH')
        attempt = con.execute("SELECT a.*,b.account_scope,r.research_id,q.current_revision,q.request_json "
            "FROM extraction_attempts a JOIN extraction_batches b USING(batch_id) JOIN research_runs r USING(run_id) "
            "JOIN research_questions q USING(research_id) WHERE attempt_id=?", (attempt_id,)).fetchone()
        if (attempt is None or attempt["account_scope"] != account_scope
            or attempt["revision"] != attempt["current_revision"]
            or attempt["status"] not in {"PENDING_REVIEW", "PARTIAL_SUCCESS", "SUCCEEDED", "NO_ACCEPTED_EVIDENCE"}):
            raise ValueError("REVIEW_SCOPE_REVISION_OR_STATE_DENIED")
        source_row = con.execute("SELECT source_id FROM source_contents WHERE content_id=?", (attempt["content_id"],)).fetchone()
        content = next((c for c in store.contents.load(source_row[0], account_scope, purge=False)
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
        run_revision = 0 if local else attempt["revision"]
        run = store.begin("research-" + revalidation_id if revalidation_id else attempt["research_id"], run_revision, request.to_dict(), account_scope)
        store.register_policy(run, run_revision, policy)
        con.execute("INSERT OR IGNORE INTO research_run_contents VALUES(?,?)", (run, content["content_id"]))
        for row in rows:
            index = row["candidate_index"]
            if index not in decisions:
                continue
            decision = decisions[index]
            if set(decision) - {"action", "reason_code", "dimension_checks", "context_conditions", "dependency_resolution",
                                "route_association", "reference_scope", "context_span_ids", "duration_scope"}:
                raise ValueError("UNKNOWN_REVIEW_FIELD")
            if row["review_json"] and not local:
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
            if row["context_status"] != "PENDING" and not (local and local['mode'] == 'EVALUATION'):
                raise ValueError("REJECTED_LOCATOR_CANNOT_BE_APPROVED")
            claim_id = None
            if action == "ACCEPT":
                if reason != ("MODEL_CONTEXT_SUPPORTED" if model_review_id or local else "WORK_CONTEXT_VERIFIED") or decision.get("dimension_checks") != {k: True for k in REVIEW_DIMENSIONS}:
                    raise ValueError("CONTEXT_REVIEW_INCOMPLETE")
                candidate = deepcopy(json.loads(row["candidate_json"]))
                reference = candidate.get("reference_selection")
                directory = None
                if reference:
                    if (reference["content_id"] != content["content_id"] or
                        reference["content_hash"] != content["content_hash"]):
                        raise ValueError("REVIEW_REFERENCE_SNAPSHOT_MISMATCH")
                    validate_reference(candidate, view, content["source_id"])
                    if decision.get("reference_scope") not in REFERENCE_KINDS:
                        raise ValueError("REFERENCE_KIND_REVIEW_REQUIRED")
                    if candidate["topic"] == "DURATION" and decision.get("duration_scope") not in {"WHOLE_TRIP", "DAY_SEGMENT"}:
                        raise ValueError("DURATION_SCOPE_REVIEW_REQUIRED")
                    if decision.get("context_conditions"):
                        raise ValueError("REFERENCE_REVIEW_REQUIRES_SPAN_IDS")
                    directory = catalog(view, content["source_id"], content["content_id"], content["content_hash"])
                    condition_ids = [s["span_id"] for s in reference["conditions"]]
                    condition_ids += decision.get("context_span_ids", [])
                    association = decision.get("route_association")
                    if association:
                        if set(association) != {"object_span_id", "scope"}:
                            raise ValueError("REFERENCE_ASSOCIATION_REQUIRES_SPAN")
                        condition_ids.append(association["object_span_id"])
                    condition_ids = list(dict.fromkeys(condition_ids))
                    if len(condition_ids) > 8:
                        raise ValueError("REFERENCE_CONDITION_LIMIT")
                    candidate = materialize({"topic": candidate["topic"],
                        "statement_span_id": reference["statement"]["span_id"],
                        "condition_span_ids": condition_ids,
                        "proposed_reference_kind": reference["proposed_reference_kind"]}, directory, view)
                if set(candidate["source_block_ids"]) & rejected_conditions and decision.get("dependency_resolution") != "INDEPENDENT":
                    raise ValueError("DEPENDENCY_UNRESOLVED")
                context_conditions = list(decision.get("context_conditions", []))
                association = decision.get("route_association")
                association_span = None
                if association is not None and directory:
                    association_span = directory["spans"][association["object_span_id"]]
                    association = {"object_quote": view.text[association_span["start"]:association_span["end"]],
                        "object_block_id": association_span["block_index"], "scope": association["scope"]}
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
                metadata.update(context_review_status="MODEL_CONTEXT_REVIEWED" if model_review_id else "WORK_REVIEWED", grounding_rule_version=2,
                                audit_attempt_id=attempt_id, audit_candidate_index=index)
                if model_review_id:
                    metadata['context_review_id'] = model_review_id
                if local:
                    metadata.update(context_review_status='LOCAL_REVALIDATION', context_review_id=local['review_id'],
                                    local_revalidation_id=revalidation_id)
                if decision.get("reference_scope"):
                    metadata["reference_scope"] = decision["reference_scope"]
                if decision.get("duration_scope"):
                    if candidate["topic"] != "DURATION":
                        raise ValueError("DURATION_SCOPE_TOPIC_MISMATCH")
                    metadata["duration_scope"] = decision["duration_scope"]
                if association is not None:
                    block = view.blocks[association["object_block_id"]]
                    low = association_span["start"] if association_span else block.start + block.text.index(association["object_quote"])
                    metadata["route_association"] = {**association, "source_id": content["source_id"],
                        "object_locator": block.locator.rsplit(":chars:", 1)[0] +
                        f":chars:{low}-{low + len(association['object_quote'])}"}
                # Exact within-source semantic identity only. Keep an existing object
                # and its review untouched; the new attempt still retains its own spans.
                existing = store.repository.get(content["source_id"], account_scope)
                if reference and existing is not None:
                    for prior in existing["claims"]:
                        prior_meta = existing.get("claim_metadata", {}).get(prior["claim_id"], {})
                        if (prior["topic"] == claim["topic"] and prior["locator"] == claim["locator"]
                            and evidence_key(prior["text"]) == evidence_key(claim["text"])
                            and {evidence_key(v) for v in prior_meta.get("applicable_conditions", [])} ==
                                {evidence_key(v) for v in metadata["applicable_conditions"]}
                            and prior_meta.get("reference_scope") == metadata.get("reference_scope")
                            and prior_meta.get("duration_scope") == metadata.get("duration_scope")
                            and prior_meta.get("route_association") == metadata.get("route_association")):
                            claim, metadata = prior, prior_meta
                            break
                data = source.to_dict() | {"claims": [claim], "claim_metadata": {claim["claim_id"]: metadata},
                    "missing_fields": [g for g in source["missing_fields"] if g not in {"NO_GROUNDED_CLAIMS", "LOCAL_EXTRACTIVE_ONLY"}]}
                bundle = EvidenceBundle(data)
                if audit_grounding(bundle, (content,))["unsupported"]:
                    raise ValueError("REVIEW_LINEAGE_INVALID")
                if local:
                    con.execute('INSERT INTO revalidation_claims VALUES(?,?,?)', (revalidation_id, index, claim['claim_id']))
                store.save_evidence(run, run_revision, bundle, policy,
                                    {"identity_match": True}, merge_reviewed=True)
                claim_id = claim["claim_id"]
            if local:
                continue
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
        if local:
            # The replay publisher creates a separate report. Never mutate old attempt/candidate state.
            con.execute("UPDATE research_runs SET status='FINISHED',finished_at=? WHERE run_id=?", (store.db.stamp(), run))
            return {'local_revalidation_id': revalidation_id}
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
