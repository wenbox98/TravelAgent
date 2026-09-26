"""Deterministic, versioned local decisions over immutable saved model proposals.

No provider, budget reservation, source reader, or browser is constructed here.
"""

from copy import deepcopy
import json
import re
from typing import Any
from uuid import uuid4

from travel_agent.providers.llm import LLMError, validate_structured
from jsonschema import ValidationError  # type: ignore[import-untyped]
from .context_review import (
    RULE_VERSION,
    REASONS,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_V1,
    _digest,
    build_input,
    check_decision,
)
from .store import EvidenceStore

AMOUNT = re.compile(r"[\d一二三四五六七八九十两半]+\s*(?:天|小时|分钟|晚)|全程|整趟|总共|总计|一共")
DAY = re.compile(r"(?i)(?<![a-z0-9])(?:Day|D)\s*\d+|第[一二三四五六七八九十\d]+天")


def convert_legacy(
    p: dict[str, Any], data: dict[str, Any], ctx: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Only a provable ordinal representation difference; not a semantic approval."""
    out = deepcopy(p)
    raw = ctx["raw"].get(p["candidate_index"])
    if raw is None:
        raise ValueError("INVALID_REFERENCE")
    out["candidate_topic"] = raw["topic"]
    if (
        p["decision"] != "REFERENCE"
        or raw["topic"] == "DURATION"
        or p["duration_scope"] != "DAY_SEGMENT"
    ):
        return out, None
    sent = {s["span_id"]: s for s in data["spans"]}
    statement = raw["reference_selection"]["statement"]["span_id"]
    ids = [statement, *p["context_span_ids"]]
    if p["object_span_id"]:
        ids.append(p["object_span_id"])
    if any(i not in sent or i not in ctx["directory"]["spans"] for i in ids):
        raise ValueError("INVALID_REFERENCE")
    # An arbitrary day elsewhere in the article cannot assign this statement to it.
    explicit = [statement] + ([p["object_span_id"]] if p["object_span_id"] else [])
    anchors = [i for i in explicit if DAY.search(sent[i]["text"])]
    days = {
        m.group(0).lower().replace(" ", "") for i in anchors for m in DAY.finditer(sent[i]["text"])
    }
    if not anchors or len(days) != 1 or AMOUNT.search(DAY.sub("", raw["quote"])):
        raise ValueError("DURATION_SCOPE_MISMATCH")
    if p["object_span_id"] and statement not in anchors:
        # Require a preceding day header in the same section, with no intervening day header.
        positions = {s["span_id"]: n for n, s in enumerate(data["spans"])}
        low, high = positions[p["object_span_id"]], positions[statement]
        if low >= high or any(DAY.search(s["text"]) for s in data["spans"][low + 1 : high]):
            raise ValueError("INVALID_REFERENCE")
    out["duration_scope"] = "NONE"
    return out, {
        "rule": "V1_DAY_ORDINAL_TO_V2_NONE",
        "old": "DAY_SEGMENT",
        "new": "NONE",
        "anchor_span_ids": anchors,
    }


def binding(
    store: EvidenceStore, review_id: str, scope: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        return _binding(store, review_id, scope)
    except KeyError, TypeError, json.JSONDecodeError, ValidationError, LLMError:
        raise ValueError("REPLAY_UNAVAILABLE") from None


def _binding(
    store: EvidenceStore, review_id: str, scope: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    r = store.db.connection.execute(
        "SELECT * FROM context_review_runs WHERE review_id=? AND account_scope=? AND status='COMPLETED'",
        (review_id, scope),
    ).fetchone()
    if r is None or not r["results_json"] or r["review_version"] not in {1, 2}:
        raise ValueError("REPLAY_UNAVAILABLE")
    row = dict(r)
    data, ctx = build_input(
        store,
        r["attempt_id"],
        scope,
        json.loads(r["target_json"]),
        version=r["review_version"],
        local_read=True,
    )
    if _digest(data) != r["input_hash"]:
        raise ValueError("REVIEW_INPUT_CHANGED")
    original = json.loads(r["results_json"])
    validate_structured(
        {"reviews": [x["proposal"] for x in original if x.get("proposal")]},
        REVIEW_SCHEMA_V1 if r["review_version"] == 1 else REVIEW_SCHEMA,
    )
    if len({x["candidate_index"] for x in original}) != len(original):
        raise ValueError("REPLAY_UNAVAILABLE")
    policy = store._latest_policy(ctx["content"]["policy_id"])
    bound = {
        "review_id": review_id,
        "attempt_id": r["attempt_id"],
        "account_scope": scope,
        "source_id": ctx["content"]["source_id"],
        "content_id": ctx["content"]["content_id"],
        "content_hash": ctx["content"]["content_hash"],
        "normalization_version": ctx["content"]["normalization_version"],
        "review_version": r["review_version"],
        "original_rule_version": r["rule_version"],
        "input_hash": r["input_hash"],
        "candidate_hash": _digest(ctx["raw"]),
        "sent_spans_hash": _digest(data["spans"]),
        "results_hash": _digest(original),
        "policy_hash": _digest(policy.to_dict() if policy else None),
        "revision": ctx["attempt"]["revision"],
    }
    return row, data, ctx, bound


def verify_record(store: EvidenceStore, identifier: str, scope: str) -> dict[str, Any]:
    row = store.db.connection.execute(
        "SELECT * FROM review_revalidations WHERE revalidation_id=? AND account_scope=?",
        (identifier, scope),
    ).fetchone()
    if row is None:
        raise ValueError("REPLAY_UNAVAILABLE")
    _, _, _, current = binding(store, row["review_id"], scope)
    if current != json.loads(row["binding_json"]):
        raise ValueError("REPLAY_BINDING_CHANGED")
    return dict(row)


class _Rollback(Exception):
    def __init__(self, result: dict[str, Any]):
        self.result = result


def replay(
    store: EvidenceStore, review_id: str, scope: str, code_sha: str, *, dry_run: bool = True
) -> dict[str, Any]:
    """Same deterministic storage checks for dry-run/apply, serialized by SQLite."""
    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise ValueError("CODE_SHA_REQUIRED")
    try:
        with store.db.transaction() as con:
            r, data, ctx, bound = binding(store, review_id, scope)
            if r["review_version"] != 1:
                raise ValueError("REPLAY_UNAVAILABLE")
            old = con.execute(
                "SELECT revalidation_id FROM review_revalidations WHERE review_id=? AND rule_version=? AND input_hash=?",
                (review_id, RULE_VERSION, r["input_hash"]),
            ).fetchone()
            if old:
                record = verify_record(store, old[0], scope)
                return summary(record)
            results = []
            for item in json.loads(r["results_json"]):
                result = {
                    "candidate_index": item["candidate_index"],
                    "original": item["program"],
                    "conversion": None,
                    "program": item["program"],
                    "eligible": False,
                }
                p = item.get("proposal")
                if p is None:
                    result["program"] = {
                        "action": "NEEDS_REVIEW",
                        "reason_code": "REPLAY_UNAVAILABLE",
                    }
                elif p["decision"] != "REFERENCE":
                    # Model rejection/uncertainty is immutable; no normalization can promote it.
                    result["program"] = {
                        "action": "REJECT" if p["decision"] == "REJECT" else "NEEDS_REVIEW",
                        "reason_code": p["reason_code"],
                    }
                else:
                    try:
                        normalized, conversion = convert_legacy(p, data, ctx)
                        result["conversion"] = conversion
                        result["program"] = check_decision(
                            normalized, data | {"review_version": 2}, ctx
                        )
                        result["eligible"] = (
                            r["mode"] == "EVALUATION" or item["program"]["action"] == "NEEDS_REVIEW"
                        )
                    except (ValueError, LLMError) as error:
                        result["program"] = {
                            "action": "NEEDS_REVIEW",
                            "reason_code": str(error)
                            if str(error) in REASONS
                            else "INVALID_REFERENCE",
                        }
                results.append(result)
            identifier = "revalidation-" + uuid4().hex
            con.execute(
                "INSERT INTO review_revalidations VALUES(?,?,?,?,?,?,?,?,?,'VALIDATING',NULL,?)",
                (
                    identifier,
                    review_id,
                    scope,
                    RULE_VERSION,
                    code_sha,
                    r["input_hash"],
                    json.dumps(bound),
                    json.dumps(results),
                    r["mode"],
                    store.db.stamp(),
                ),
            )
            from .candidate_review import review_candidates

            # EVALUATION runs the same storage checks inside a savepoint that is always rolled back.
            con.execute("SAVEPOINT evaluation_storage")
            for item in sorted(
                results,
                key=lambda v: ctx["raw"].get(v["candidate_index"], {}).get("topic") != "ROUTE",
            ):
                if not item["eligible"] or item["program"]["action"] != "ACCEPT":
                    continue
                try:
                    review_candidates(
                        store,
                        attempt_id=r["attempt_id"],
                        account_scope=scope,
                        decisions={item["candidate_index"]: deepcopy(item["program"])},
                        revalidation_id=identifier,
                    )
                except ValueError, PermissionError:
                    item["program"] = {
                        "action": "NEEDS_REVIEW",
                        "reason_code": "DEPENDENCY_UNRESOLVED",
                    }
            if r["mode"] == "EVALUATION":
                con.execute("ROLLBACK TO evaluation_storage")
            con.execute("RELEASE evaluation_storage")
            con.execute(
                "UPDATE review_revalidations SET results_json=?,status='COMPLETED' WHERE revalidation_id=?",
                (json.dumps(results), identifier),
            )
            added = con.execute(
                "SELECT count(*) FROM revalidation_claims WHERE revalidation_id=?", (identifier,)
            ).fetchone()[0]
            if added and r["mode"] == "RUNTIME":
                _publish(store, identifier, ctx, scope)
            record = verify_record(store, identifier, scope)
            out = summary(record) | {"added": added}
            if dry_run:
                raise _Rollback(out)
            return out
    except _Rollback as result:
        return result.result


def _publish(store: EvidenceStore, identifier: str, ctx: dict[str, Any], scope: str) -> None:
    from .models import ResearchRequest, ResearchReport
    from .planning import SufficiencyEvaluator

    con = store.db.connection
    original = con.execute(
        "SELECT request_json FROM research_questions WHERE research_id=?",
        (ctx["attempt"]["research_id"],),
    ).fetchone()
    request = ResearchRequest(**json.loads(original[0]))
    research = "research-" + identifier
    run = store.begin(research, 0, request.to_dict(), scope)
    evidence = store.lookup(research, request.destination, scope)
    for bundle in evidence:
        policy = store._latest_policy(bundle["policy_id"])
        assert policy is not None
        store.save_evidence(run, 0, bundle, policy, {"identity_match": True})
    gaps = SufficiencyEvaluator(clock=store.db.clock).gaps(request, evidence)
    report = ResearchReport(
        research,
        0,
        run,
        request,
        evidence,
        gaps,
        "BUDGET_EXHAUSTED" if gaps else "EVIDENCE_SUFFICIENT",
        {"search": 0, "detail": 0},
        len(evidence),
        assessed_at=store.db.stamp(),
    )
    store.finish(run, 0, [g.to_dict() for g in gaps], report.safe_summary())
    con.execute(
        "UPDATE review_revalidations SET research_id=? WHERE revalidation_id=?",
        (research, identifier),
    )


def summary(record: dict[str, Any]) -> dict[str, Any]:
    rows = json.loads(record["results_json"])
    return {
        "revalidation_id": record["revalidation_id"],
        "mode": record["mode"],
        "rule_version": record["rule_version"],
        "accepted": sum(r["program"]["action"] == "ACCEPT" for r in rows),
        "pending": sum(r["program"]["action"] == "NEEDS_REVIEW" for r in rows),
        "rejected": sum(r["program"]["action"] == "REJECT" for r in rows),
        "converted": sum(r["conversion"] is not None for r in rows),
        "results": rows,
    }
