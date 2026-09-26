"""One article-level model review; program-owned lineage, guards and partial retention."""

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any
from uuid import uuid4

from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT
from travel_agent.domain.models import validator
from travel_agent.providers.llm import (
    LLMError,
    LLMProvider,
    OpenAICompatibleProvider,
    validate_structured,
)
from .bounded import BoundedBudget
from .canonical import canonicalize
from .extractor import policy_allows_model
from .grounding import CONTEXT_REASONS, REVIEW_DIMENSIONS, check_grounding, context_hazard
from .references import REFERENCE_KINDS, catalog, materialize, payload, validate_reference
from .store import EvidenceStore

TASK = "review_evidence_context_v2"
REVIEW_VERSION = 2
RULE_VERSION = 3
REASONS = sorted(
    (CONTEXT_REASONS - {"WORK_CONTEXT_VERIFIED", "DEPENDENCY_INDEPENDENT"})
    | {
        "CONTEXT_SUPPORTED",
        "INSUFFICIENT_CONTEXT",
        "INVALID_REFERENCE",
        "ROLE_MISMATCH",
        "DURATION_SCOPE_MISMATCH",
    }
)
PROPERTIES: dict[str, Any] = {
    "candidate_index": {"type": "integer", "minimum": 0, "maximum": 11},
    "decision": {"enum": ["REFERENCE", "REJECT", "NEEDS_REVIEW"]},
    "reason_code": {"enum": REASONS},
    "dimension_checks": {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(REVIEW_DIMENSIONS),
        "properties": {k: {"type": "boolean"} for k in sorted(REVIEW_DIMENSIONS)},
    },
    "context_span_ids": {
        "type": "array",
        "maxItems": 8,
        "uniqueItems": True,
        "items": {"type": "string", "maxLength": 100},
    },
    "reference_scope": {"enum": list(REFERENCE_KINDS)},
    "duration_scope": {"enum": ["NONE", "WHOLE_TRIP", "DAY_SEGMENT"]},
    "object_span_id": {"type": ["string", "null"], "maxLength": 100},
    "object_scope": {"enum": ["WHOLE_TRIP", "SEGMENT"]},
    "dependency_resolution": {"enum": ["INDEPENDENT", "UNRESOLVED"]},
    "explanation": {"type": "string", "minLength": 1, "maxLength": 200},
}
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["reviews"],
    "properties": {
        "reviews": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(PROPERTIES),
                "properties": PROPERTIES,
            },
        }
    },
}
REVIEW_SCHEMA_V1 = deepcopy(REVIEW_SCHEMA)
PROPERTIES["candidate_topic"] = {"enum": validator("EvidenceClaim").schema["$defs"]["EvidenceClaim"]["properties"]["topic"]["enum"]}
REVIEW_SCHEMA["properties"]["reviews"]["items"]["required"] = list(PROPERTIES)
REVIEW_SCHEMA["properties"]["reviews"]["items"]["allOf"] = [{
    "if": {"properties": {"candidate_topic": {"not": {"const": "DURATION"}}}},
    "then": {"properties": {"duration_scope": {"const": "NONE"}}},
}]

# Guardrails target categories, never source IDs, locations or sample ordinals.
PLAN = re.compile(r"计划|打算|准备|还没出发|尚未出发|还未出发|想.*(?:去|走|自驾)|求建议")
PAST = re.compile(r"去年|前年|上次|曾经|曾到|去过|走过|游过|已经.*(?:走|去)|实际.*(?:用|走)")
QUESTION = re.compile(r"[？?]|是否|会不会|求问|请问|不知道|不确定|听说|据说")
DAY = re.compile(r"(?i)Day\s*\d|D\s*\d|第[一二三四五六七八九十\d]+天")
IMPORTANT = re.compile(
    r"高反|高原反应|吸氧|药物|服药|医院|医疗|保证|绝对|一定不会|肯定不会|"
    r"发车|班次|末班|首班|门票|票价|开放时间|营业时间|封路|路况|通行|"
    r"(?:坐|乘|换乘).{0,8}(?:观光车|摆渡车|景交|电瓶车)|全(?:程|区|域).*(?:金黄|最美|晴|雪)"
)


def _digest(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build_input(
    store: EvidenceStore, attempt_id: str, scope: str, target: dict[str, Any], *, version: int = REVIEW_VERSION,
    local_read: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reconstruct from immutable extraction snapshot, ignoring ALL historic review fields."""
    a = store.db.connection.execute(
        "SELECT a.*,b.account_scope,r.research_id,q.current_revision FROM extraction_attempts a "
        "JOIN extraction_batches b USING(batch_id) JOIN research_runs r USING(run_id) "
        "JOIN research_questions q USING(research_id) WHERE attempt_id=?",
        (attempt_id,),
    ).fetchone()
    if (
        not a
        or a["account_scope"] != scope
        or a["extraction_version"] != 3
        or a["revision"] != a["current_revision"]
    ):
        raise ValueError("REVIEW_IDENTITY_OR_VERSION_DENIED")
    r = store.db.connection.execute(
        "SELECT source_id FROM source_contents WHERE content_id=?", (a["content_id"],)
    ).fetchone()
    content = (
        next(
            (
                c
                for c in store.contents.load(r[0], scope, purge=False)
                if c["content_id"] == a["content_id"]
            ),
            None,
        )
        if r
        else None
    )
    if (
        not content
        or content["content_hash"] != a["content_hash"]
        or content["normalization_version"] != a["normalization_version"]
    ):
        raise ValueError("REVIEW_SNAPSHOT_MISMATCH")
    policy = store._latest_policy(content["policy_id"])
    from travel_agent.domain.source_policy import scope_allowed
    if policy is None or not scope_allowed(policy, scope) or not (
        store.repository.permitted(policy) if local_read else policy_allows_model(policy, external=True, now=store.db.clock())
    ):
        raise ValueError("REVIEW_POLICY_DENIED")
    view = canonicalize(
        content["raw_text"], content["dom_text"], completeness=content["content_completeness"]
    )
    directory = catalog(view, content["source_id"], content["content_id"], content["content_hash"])
    candidates, raw = [], {}
    for r in store.db.connection.execute(
        "SELECT candidate_index,candidate_json,locator_json FROM extraction_candidates "
        "WHERE attempt_id=? ORDER BY candidate_index",
        (attempt_id,),
    ):
        if not json.loads(r["locator_json"])["passed"]:
            continue
        c = json.loads(r["candidate_json"])
        validate_reference(c, view, content["source_id"])
        ref = c["reference_selection"]
        if (
            ref["content_hash"] != content["content_hash"]
            or ref["content_id"] != content["content_id"]
        ):
            raise ValueError("REVIEW_REFERENCE_SNAPSHOT_MISMATCH")
        raw[r[0]] = c
        candidates.append(
            {
                "candidate_index": r[0],
                "topic": c["topic"],
                "statement_span_id": ref["statement"]["span_id"],
                "condition_span_ids": [s["span_id"] for s in ref["conditions"]],
            }
        )
    spans = payload(directory, view)
    for i, s in enumerate(spans):
        p = directory["spans"][s["span_id"]]
        s["parent_range"] = [p["parent_start"], p["parent_end"]]
        s["previous_span_id"] = spans[i - 1]["span_id"] if i else None
        s["next_span_id"] = spans[i + 1]["span_id"] if i + 1 < len(spans) else None
    source_chars = sum(len(s["text"]) for s in spans)
    if source_chars > 6000 or not spans or not candidates:
        raise ValueError("REVIEW_INPUT_EMPTY_OR_LIMIT")
    # Only fixed user preference fields; never send request IDs or free-form commands.
    data = {
        "spans": spans,
        "candidates": candidates,
        "completeness": content["content_completeness"],
        "context_may_be_missing": source_chars < sum(len(b.text) for b in view.blocks),
        "target_preferences": {k: target[k] for k in ("days", "driving") if k in target},
        "review_version": version,
        "purpose": "CONDITIONAL_REFERENCE_NOT_VERIFIED_FACT",
    }
    if SENSITIVE_RESEARCH_TEXT.search(json.dumps(data, ensure_ascii=False)):
        raise ValueError("REVIEW_SENSITIVE_INPUT")
    return data, {
        "attempt": dict(a),
        "content": content,
        "view": view,
        "directory": directory,
        "raw": raw,
    }


def check_decision(
    p: dict[str, Any], data: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """No model label can manufacture exact anchors, dependencies or current facts."""
    validate_structured({"reviews": [p]}, REVIEW_SCHEMA_V1 if data["review_version"] == 1 else REVIEW_SCHEMA)
    i = p["candidate_index"]
    if i not in context["raw"]:
        raise ValueError("INVALID_REFERENCE")
    if data["review_version"] != 1 and p["candidate_topic"] != context["raw"][i]["topic"]:
        raise ValueError("INVALID_REFERENCE")
    if SENSITIVE_RESEARCH_TEXT.search(p["explanation"]) or re.search(
        r"https?://|[A-Za-z]:[\\/]", p["explanation"]
    ):
        raise ValueError("INVALID_REFERENCE")
    if p["decision"] != "REFERENCE":
        if p["reason_code"] == "CONTEXT_SUPPORTED":
            raise ValueError("CONTEXT_UNCERTAIN")
        return {
            "action": "REJECT" if p["decision"] == "REJECT" else "NEEDS_REVIEW",
            "reason_code": p["reason_code"],
        }
    if p["reason_code"] != "CONTEXT_SUPPORTED" or p["dimension_checks"] != {
        k: True for k in REVIEW_DIMENSIONS
    }:
        raise ValueError("CONTEXT_UNCERTAIN")
    raw = context["raw"][i]
    ref = raw["reference_selection"]
    ids = list(p["context_span_ids"])
    if p["object_span_id"] is not None:
        ids.append(p["object_span_id"])
    ids = list(dict.fromkeys(ids))
    if any(s not in context["directory"]["spans"] for s in ids):
        raise ValueError("INVALID_REFERENCE")
    if not {s["span_id"] for s in ref["conditions"]} <= set(ids):
        raise ValueError("CONTEXT_CONDITION_OMITTED")
    if not ids or len(ids) > 8 or p["dependency_resolution"] != "INDEPENDENT":
        raise ValueError("DEPENDENCY_UNRESOLVED")
    text = raw["quote"]
    alltext = "\n".join(s["text"] for s in data["spans"])
    selected = "\n".join(
        context["view"].text[
            context["directory"]["spans"][s]["start"] : context["directory"]["spans"][s]["end"]
        ]
        for s in ids
    )
    parent = ref["statement"]
    siblings = [
        s
        for s in data["spans"]
        if s["parent_range"] == [parent["parent_start"], parent["parent_end"]]
    ]
    if any(
        s["span_id"] not in ids
        and s["span_id"] != parent["span_id"]
        and (
            PLAN.search(s["text"])
            or QUESTION.search(s["text"])
            or re.search(r"不|没|仅|如果|但是", s["text"])
        )
        for s in siblings
    ):
        raise ValueError("CONTEXT_CONDITION_OMITTED")
    if QUESTION.search(text):
        raise ValueError("CONTEXT_UNCERTAIN")
    if IMPORTANT.search(text) or raw["topic"] in {"PRICE", "OPENING", "RESERVATION"}:
        raise ValueError("UNVERIFIED_IMPORTANT_FACT")
    if p["reference_scope"] == "UNKNOWN":
        raise ValueError("CONTEXT_UNCERTAIN")
    if PLAN.search(text) and PAST.search(text):
        raise ValueError("CONTEXT_TRANSPORT_MISMATCH")
    if p["reference_scope"] == "AUTHOR_RECORDED_TRIP" and (
        not PAST.search(text + "\n" + selected)
        or PLAN.search(text + "\n" + selected)
        or re.search(r"没(?:有)?(?:去|走|到)|未亲历", text + "\n" + selected)
    ):
        raise ValueError("ROLE_MISMATCH")
    if p["reference_scope"] == "AUTHOR_PROPOSED_PLAN" and (
        not PLAN.search(selected + "\n" + text) or PAST.search(text)
    ):
        raise ValueError("ROLE_MISMATCH")
    # An article preamble's explicit plan cannot be relabelled as completed travel.
    preamble = alltext.split(
        next((s["text"] for s in data["spans"] if DAY.search(s["text"])), "\0")
    )[0]
    if (
        PLAN.search(preamble)
        and raw["topic"] in {"ROUTE", "DURATION", "TRANSPORT"}
        and not PAST.search(text)
    ):
        if p["reference_scope"] != "AUTHOR_PROPOSED_PLAN" or not PLAN.search(
            selected + "\n" + text
        ):
            raise ValueError("ROLE_MISMATCH")
    if raw["topic"] == "DURATION":
        if data["review_version"] != 1 and not re.search(r"[\d一二三四五六七八九十两半]+\s*(?:天|小时|分钟|晚)", DAY.sub("", text)):
            raise ValueError("DURATION_SCOPE_MISMATCH")
        if p["duration_scope"] == "NONE" or (
            DAY.search(text) and p["duration_scope"] == "WHOLE_TRIP"
        ):
            raise ValueError("DURATION_SCOPE_MISMATCH")
        if p["duration_scope"] == "WHOLE_TRIP" and not re.search(
            r"(?:全程|整趟|总共|总计|用了|一共).{0,8}[\d一二三四五六七八九十]+天", text
        ):
            raise ValueError("DURATION_SCOPE_MISMATCH")
    elif p["duration_scope"] != "NONE":
        raise ValueError("DURATION_SCOPE_MISMATCH")
    row = materialize(
        {
            "topic": raw["topic"],
            "statement_span_id": ref["statement"]["span_id"],
            "condition_span_ids": ids,
            "proposed_reference_kind": ref["proposed_reference_kind"],
        },
        context["directory"],
        context["view"],
    )
    if not check_grounding(row, context["view"].blocks).passed or context_hazard(
        row, context["view"].blocks
    ):
        raise ValueError("INVALID_REFERENCE")
    d = {
        "action": "ACCEPT",
        "reason_code": "MODEL_CONTEXT_SUPPORTED",
        "dimension_checks": p["dimension_checks"],
        "context_span_ids": ids,
        "reference_scope": p["reference_scope"],
        "dependency_resolution": "INDEPENDENT",
    }
    if raw["topic"] == "DURATION":
        d["duration_scope"] = p["duration_scope"]
    if p["object_span_id"]:
        d["route_association"] = {"object_span_id": p["object_span_id"], "scope": p["object_scope"]}
    return d


def reserve_review(
    store: EvidenceStore,
    budget: BoundedBudget,
    attempt: str,
    scope: str,
    target: dict[str, Any],
    *,
    evaluation: bool = False,
) -> str:
    data, ctx = build_input(store, attempt, scope, target)
    with store.db.transaction() as con:
        state = budget.state()
        if state["account_scope"] != scope:
            raise ValueError("REVIEW_SCOPE_DENIED")
        if evaluation:
            if (
                attempt not in state["gate"]["evaluation_attempts"]
                or state["gate"]["status"] != "PENDING"
            ):
                raise ValueError("EVALUATION_NOT_AUTHORIZED")
        elif state["gate"]["status"] != "PASS" or ctx["attempt"]["batch_id"] != budget.identifier:
            raise ValueError("RUNTIME_REVIEW_NOT_AUTHORIZED")
        budget.reserve("MODEL", "review:" + ctx["content"]["source_id"])
        rid = "review-" + uuid4().hex
        con.execute(
            "INSERT INTO context_review_runs VALUES(?,?,?,?,?,?,?,?,?,NULL,NULL,?,NULL,2,3)",
            (
                rid,
                budget.identifier,
                attempt,
                scope,
                "EVALUATION" if evaluation else "RUNTIME",
                ctx["attempt"]["revision"],
                _digest(data),
                json.dumps(target),
                "PENDING",
                store.db.stamp(),
            ),
        )
    return rid


def run_review(store: EvidenceStore, provider: LLMProvider, review_id: str) -> dict[str, Any]:
    con = store.db.connection
    r = con.execute("SELECT * FROM context_review_runs WHERE review_id=?", (review_id,)).fetchone()
    if r is None:
        raise ValueError("REVIEW_RESERVATION_MISSING")
    budget = BoundedBudget(store, r["continuation_id"])
    if isinstance(provider, OpenAICompatibleProvider):
        budget.check_provider(provider)
    data, ctx = build_input(
        store, r["attempt_id"], r["account_scope"], json.loads(r["target_json"]), version=r["review_version"]
    )
    budget.check_permit("MODEL", "review:" + ctx["content"]["source_id"])
    if _digest(data) != r["input_hash"]:
        raise ValueError("REVIEW_INPUT_CHANGED")
    with store.db.transaction():
        if (
            con.execute(
                "UPDATE context_review_runs SET status='RUNNING' WHERE review_id=? AND status='PENDING'",
                (review_id,),
            ).rowcount
            != 1
        ):
            raise ValueError("REVIEW_ALREADY_CLAIMED")

    def checkpoint(safe: dict[str, Any]) -> None:
        if r['mode']=='RUNTIME' and safe.get('transport_phase')=='OPENING':
            budget.check_job_active(ctx['attempt']['research_id'])
        with store.db.transaction():
            con.execute(
                "UPDATE context_review_runs SET diagnostic_json=? WHERE review_id=? AND status='RUNNING'",
                (json.dumps(safe), review_id),
            )

    if isinstance(provider, OpenAICompatibleProvider):
        provider.diagnostic_observer = checkpoint
    try:
        if r['mode']=='RUNTIME':
            budget.check_job_active(ctx['attempt']['research_id'])
        schema = REVIEW_SCHEMA_V1 if r["review_version"] == 1 else REVIEW_SCHEMA
        output = validate_structured(provider.structured(f"review_evidence_context_v{r['review_version']}", data, schema), schema)
        if isinstance(provider, OpenAICompatibleProvider) and provider.last_diagnostic is not None:
            # Transport checkpoints precede envelope/schema parsing and its final elapsed time.
            checkpoint(provider.last_diagnostic.safe_dict())
        # No raw response or hidden reasoning retained. Store bounded, validated proposals only.
        if SENSITIVE_RESEARCH_TEXT.search(json.dumps(output, ensure_ascii=False)):
            raise ValueError("REVIEW_SENSITIVE_OUTPUT")
        results = []
        seen = set()
        proposals = output["reviews"]
        if len({p["candidate_index"] for p in proposals}) != len(proposals):
            raise ValueError("DUPLICATE_REVIEW_CANDIDATE")
        for p in proposals:
            seen.add(p["candidate_index"])
            try:
                d = check_decision(p, data, ctx)
            except (ValueError, LLMError) as error:
                reason = str(error) if str(error) in REASONS else "INVALID_REFERENCE"
                d = {"action": "NEEDS_REVIEW", "reason_code": reason}
            results.append({"candidate_index": p["candidate_index"], "proposal": p, "program": d})
        for i in ctx["raw"].keys() - seen:
            results.append(
                {
                    "candidate_index": i,
                    "proposal": None,
                    "program": {"action": "NEEDS_REVIEW", "reason_code": "INSUFFICIENT_CONTEXT"},
                }
            )
        with store.db.transaction():
            # Revalidate current snapshot/revision/policy after a potentially long response.
            fresh, _ = build_input(
                store, r["attempt_id"], r["account_scope"], json.loads(r["target_json"]), version=r["review_version"]
            )
            if _digest(fresh) != r["input_hash"]:
                raise ValueError("REVIEW_INPUT_CHANGED")
            con.execute(
                "UPDATE context_review_runs SET results_json=?,status='COMPLETED',finished_at=? WHERE review_id=?",
                (json.dumps(results, ensure_ascii=False), store.db.stamp(), review_id),
            )
        if r["mode"] == "RUNTIME":
            from .candidate_review import review_candidates

            # ROUTE objects precede their dependent facts. Each candidate commits independently.
            ordered = sorted(
                results,
                key=lambda x: ctx["raw"].get(x["candidate_index"], {}).get("topic") != "ROUTE",
            )
            for item in ordered:
                i, d = item["candidate_index"], item["program"]
                if d["action"] == "NEEDS_REVIEW" or i not in ctx["raw"]:
                    continue
                try:
                    review_candidates(
                        store,
                        attempt_id=r["attempt_id"],
                        account_scope=r["account_scope"],
                        decisions={i: deepcopy(d)},
                        model_review_id=review_id,
                    )
                except ValueError:
                    item["program"] = {
                        "action": "NEEDS_REVIEW",
                        "reason_code": "DEPENDENCY_UNRESOLVED",
                    }
                with store.db.transaction():
                    con.execute(
                        "UPDATE context_review_runs SET results_json=? WHERE review_id=?",
                        (json.dumps(results, ensure_ascii=False), review_id),
                    )
        return review_summary(store, review_id)
    except Exception as error:
        diagnostic = (
            error.diagnostic.safe_dict()
            if isinstance(error, LLMError)
            else {"category": "REVIEW_VALIDATION_FAILED", "http_attempts": 0}
        )
        with store.db.transaction():
            # Preserve any earlier transport checkpoint when structural validation fails.
            if isinstance(error, LLMError):
                con.execute(
                    "UPDATE context_review_runs SET diagnostic_json=? WHERE review_id=?",
                    (json.dumps(diagnostic), review_id),
                )
            con.execute(
                "UPDATE context_review_runs SET status='FAILED',finished_at=? WHERE review_id=?",
                (store.db.stamp(), review_id),
            )
        return review_summary(store, review_id)


def review_summary(store: EvidenceStore, review_id: str) -> dict[str, Any]:
    r = store.db.connection.execute(
        "SELECT * FROM context_review_runs WHERE review_id=?", (review_id,)
    ).fetchone()
    results = json.loads(r["results_json"] or "[]")
    return {
        "review_id": review_id,
        "status": r["status"],
        "mode": r["mode"],
        "accepted": sum(i["program"]["action"] == "ACCEPT" for i in results),
        "rejected": sum(i["program"]["action"] == "REJECT" for i in results),
        "pending": sum(i["program"]["action"] == "NEEDS_REVIEW" for i in results),
        "diagnostic": json.loads(r["diagnostic_json"]) if r["diagnostic_json"] else None,
    }
