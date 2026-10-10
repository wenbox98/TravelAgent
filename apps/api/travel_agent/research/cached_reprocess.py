"""Explicit, trip-bound cached-body analysis. No site reader or provider dispatch here."""

import json
import re
from typing import Any

from travel_agent.domain.models import SourcePolicy
from .extractor import REFERENCE_PROMPT_VERSION, policy_allows_model
from .store import EvidenceStore

VERSION = "cached-body-analysis-v1"
BINDING_FIELDS = ("content_id", "source_id", "content_hash", "normalization_version",
                  "policy_id", "policy_version", "content_completeness")
GAP_TERMS = {
    "LODGING": r"住宿|落脚|住哪|酒店|民宿|搬行李",
    "PLAY": r"玩法|体验|看点|游玩", "TRANSPORT": r"交通|接驳|公交|地铁",
    "DURATION": r"停留|时长|天数", "ROUTES": r"路线|顺序|区域组合",
    "SEASON": r"季节|时令|月份",
}


def gap_keys(text: str, gaps: list[dict[str, Any]]) -> tuple[str, ...]:
    available = {g["key"] for g in gaps}
    requested = {key for key, pattern in GAP_TERMS.items() if re.search(pattern, text)}
    return tuple(sorted(requested & available if requested else available))


def binding(content: dict[str, Any]) -> dict[str, Any]:
    return {key: content[key] for key in BINDING_FIELDS}


def external_allowed(db: Any, content: dict[str, Any]) -> bool:
    """Local cache access alone never authorizes external inference."""
    captured = db.connection.execute(
        "SELECT policy_json FROM source_policies WHERE policy_id=? AND version=?",
        (content["policy_id"], content["policy_version"]),
    ).fetchone()
    latest = db.connection.execute(
        "SELECT policy_json FROM source_policies WHERE policy_id=? ORDER BY version DESC LIMIT 1",
        (content["policy_id"],),
    ).fetchone()
    return bool(captured and latest and all(
        policy_allows_model(SourcePolicy(json.loads(row[0])), external=True, now=db.clock())
        for row in (captured, latest)
    ))


def prepare(db: Any, scope: str, sid: str, p: dict[str, Any], text: str,
            gaps: list[dict[str, Any]]) -> dict[str, Any]:
    from travel_agent.planning.agent_contract import cached_body_reprocess_requested
    from travel_agent.planning.workbench import local_contents

    if not cached_body_reprocess_requested(text):
        raise ValueError("CACHE_BODY_EXPLICIT_REQUEST_REQUIRED")
    keys = gap_keys(text, gaps)
    if not keys:
        raise ValueError("CACHE_BODY_NO_CURRENT_GAP")
    # Version + gap + exact immutable snapshot is the recipe. Old failures remain
    # terminal even when a later task has another allowance.
    old = []
    for row in db.connection.execute(
        "SELECT request_json,continuation_id FROM preview_jobs WHERE session_id=? AND account_scope=?",
        (sid, scope),
    ):
        step = json.loads(row[0]).get("cached_body_step")
        if step and step.get("prompt_version") == REFERENCE_PROMPT_VERSION and step.get("gaps") == list(keys):
            attempted = {r[0] for r in db.connection.execute(
                "SELECT content_id FROM extraction_attempts WHERE batch_id=?", (row[1],))}
            old.extend(s for s in step["snapshots"] if s["content_id"] in attempted)
    candidates = []
    try:
        contents = local_contents(db, scope, sid, p)
    except (ValueError, PermissionError):
        raise ValueError("CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED") from None
    denied = False
    for content in contents:
        if (content["normalization_version"] != 1
            or content["content_completeness"] not in {"FULL_TEXT", "PARTIAL_TEXT"}
            or not content["normalized_text"].strip() or binding(content) in old):
            continue
        if not external_allowed(db, content):
            denied = True
            continue
        score = sum(bool(re.search(GAP_TERMS[key], content["normalized_text"])) for key in keys if key in GAP_TERMS)
        candidates.append((score, content["retrieved_at"], binding(content)))
    if not candidates:
        if denied:
            raise ValueError("CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED")
        raise ValueError("CACHE_BODY_NO_ELIGIBLE_OR_NEW_SNAPSHOT")
    candidates.sort(key=lambda item: (item[0], item[1], item[2]["content_id"]), reverse=True)
    return dict(version=VERSION, prompt_version=REFERENCE_PROMPT_VERSION, gaps=list(keys),
                origin_job_id=p.get("research_job_id"),
                snapshots=[item[2] for item in candidates[:2]])


def validate(store: EvidenceStore, job: Any, step: dict[str, Any]) -> list[dict[str, Any]]:
    """Recheck the same trip, grant, task and snapshots before every dispatch."""
    from .bounded import BoundedBudget
    from travel_agent.planning.flow import PlanningService
    from travel_agent.planning.workbench import local_contents

    budget = BoundedBudget(store, job["continuation_id"])
    budget.check_job_active(job["research_id"])
    gate = budget.state()["gate"]
    if (gate.get("cached_body_request") != step or step.get("version") != VERSION
        or step.get("prompt_version") != REFERENCE_PROMPT_VERSION
        or not 1 <= len(step.get("snapshots", [])) <= 2
        or not step.get("gaps") or len(step["gaps"]) > 32
        or any(not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", key) for key in step["gaps"])
        or any(budget.state()["limits"].get(key, 0) for key in ("CONNECT", "SEARCH", "DETAIL", "MAP_PLACE", "MAP_ROUTE"))):
        raise ValueError("CACHE_BODY_TASK_BINDING_DENIED")
    _, state = PlanningService(store.db, job["account_scope"]).load(job["session_id"])
    original = dict(state["planning"], research_job_id=step.get("origin_job_id"))
    try:
        current = {c["content_id"]: c for c in local_contents(store.db, job["account_scope"], job["session_id"], original)}
    except (ValueError, PermissionError):
        raise ValueError("CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED") from None
    result = []
    for expected in step["snapshots"]:
        content = current.get(expected["content_id"])
        if (not content or binding(content) != expected or content["normalization_version"] != 1
            or content["content_completeness"] not in {"FULL_TEXT", "PARTIAL_TEXT"}
            or not content["normalized_text"].strip() or not external_allowed(store.db, content)):
            raise ValueError("CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED")
        result.append(content)
    return result


def validate_attempt(store: EvidenceStore, attempt_id: str) -> None:
    """Recheck cached-job bindings at child entry, transport and late-result commit."""
    job = store.db.connection.execute(
        "SELECT j.* FROM preview_jobs j JOIN research_runs r USING(research_id) "
        "JOIN extraction_attempts a USING(run_id) WHERE a.attempt_id=? AND j.continuation_id=a.batch_id",
        (attempt_id,),
    ).fetchone()
    if job and (step := json.loads(job["request_json"]).get("cached_body_step")):
        validate(store, job, step)


def permits_new_batch(store: EvidenceStore, *, batch_id: str, run_id: str,
                      content: dict[str, Any], research_gaps: tuple[str, ...]) -> bool:
    """Called only by Recovery; a UI flag alone never relaxes batch immutability."""
    row = store.db.connection.execute(
        "SELECT j.* FROM preview_jobs j JOIN research_runs r USING(research_id) "
        "WHERE j.continuation_id=? AND r.run_id=?", (batch_id, run_id),
    ).fetchone()
    if not row:
        raise ValueError("CACHE_BODY_TASK_BINDING_DENIED")
    step = json.loads(row["request_json"]).get("cached_body_step")
    if not step or tuple(step["gaps"]) != research_gaps:
        raise ValueError("CACHE_BODY_TASK_BINDING_DENIED")
    valid = validate(store, row, step)
    if binding(content) not in [binding(c) for c in valid]:
        raise ValueError("CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED")
    return True


def analyze(store: EvidenceStore, job: Any, data: dict[str, Any], recovery: Any,
            budget: Any, dispatch: Any, after: Any, active: Any) -> tuple[str, dict[str, Any]]:
    step = data["cached_body_step"]
    contents = validate(store, job, step)
    run_id = store.begin(job["research_id"], 0, data["request"], job["account_scope"])
    before = {r[0] for r in store.db.connection.execute("SELECT claim_id FROM claims")}
    attempts = []
    stopped = None
    for content in contents:
        try:
            active()
            validate(store, job, step)
            # Keep a decision + useful advisory generation available after strict review.
            if budget.summary()["remaining"]["model"] < 4:
                break
            policy = store._latest_policy(content["policy_id"])
            store.register_policy(run_id, 0, policy)
            out = recovery.execute(run_id=run_id, revision=0, content_id=content["content_id"],
                account_scope=job["account_scope"], policy=policy, batch_id=job["continuation_id"],
                max_attempts=2, research_gaps=tuple(step["gaps"]), dispatch=dispatch,
                cached_reprocess=True)
            attempts.append(out["attempt_id"])
            if out["status"] not in {"PENDING_REVIEW", "NO_ACCEPTED_EVIDENCE"}:
                raise ValueError("CACHE_BODY_EXTRACTION_NOT_COMPLETED")
            active()
            after(out)
            active()
        except Exception as exc:
            active()  # cancellation/obsolete generation must still escape
            stopped = str(exc) if re.fullmatch(r"CACHE_BODY_[A-Z_]+", str(exc)) else "CACHE_BODY_ANALYSIS_STOPPED"
            break
    accepted = {r[0] for r in store.db.connection.execute(
        "SELECT DISTINCT c.claim_id FROM extraction_candidates c JOIN extraction_attempts a USING(attempt_id) "
        "WHERE a.run_id=? AND c.context_status='ACCEPTED' AND c.claim_id IS NOT NULL", (run_id,),
    )}
    evidence = store.lookup(job["research_id"], data["request"].get("destination"), job["account_scope"])
    reviewed = sum(len(bundle["claims"]) for bundle in evidence)
    gaps = [dict(gap_id=key, description="缓存正文分析结束，覆盖由当前选择重新评估", status="UNKNOWN") for key in step["gaps"]]
    store.finish(run_id, 0, gaps, dict(query_count=0, operations=dict(search=0, detail=0),
                                   source_count=len(evidence), evidence_count=reviewed,
                                   stop_reason="CACHE_BODY_ANALYSIS_STOPPED" if stopped else "CACHE_BODY_ANALYSIS_COMPLETED"))
    return ("PARTIAL" if reviewed else "NEEDS_REVIEW", dict(
        origin="CACHED_BODY_NEW_MODEL_ANALYSIS", new_evidence_count=len(accepted - before),
        analysis_accepted_evidence_count=len(accepted), existing_evidence_count=reviewed - len(accepted - before),
        analysis_stopped=bool(stopped), reason=stopped,
        reviewed_evidence_count=reviewed,
        cached_body_count=len(attempts), extraction_attempts=attempts, prompt_version=REFERENCE_PROMPT_VERSION,
        report=dict(query_count=0, operations=dict(search=0, detail=0)),
        research_stop="CACHE_BODY_ANALYSIS_STOPPED" if stopped else "CACHE_BODY_ANALYSIS_COMPLETED", browser_sessions=0))
