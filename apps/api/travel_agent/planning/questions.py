"""One explicitly authorized cached-material answer; never research or plan adoption."""

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal
from uuid import uuid4
from pydantic import Field
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import fingerprint
from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider, validate_structured
from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT
from .flow_models import OperationAuthorization

CONSENT = "PRIVATE_CACHED_QUESTION_V1"


class Interpretation(StrictModel):
    days: int | None = Field(default=None, ge=1, le=90)
    driving: Literal["YES", "NO", "UNKNOWN"] | None = None
    pace: Literal["UNKNOWN", "RELAXED"] | None = None
    transport: (
        Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"] | None
    ) = None


class Answer(StrictModel):
    advice: str = Field(min_length=1, max_length=1800)
    citation_ids: list[str] = Field(default_factory=list, max_length=12)
    gaps: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        min_length=1, max_length=8
    )
    intent: Literal["QUESTION", "MIXED", "CONDITION_CHANGE"]
    proposed_conditions: Interpretation


def payload(db: Any, scope: str, sid: str, p: dict[str, Any], question: str) -> dict[str, Any]:
    from .conversation import model_context
    from .reference_overview import references, choices, project
    from travel_agent.research.canonical import body_blocks
    from travel_agent.research.model_input import outbound_blocks
    from travel_agent.research.extractor import policy_allows_model
    from travel_agent.research.store import EvidenceStore

    context = model_context(p)
    rows = references(db, scope, sid, p)
    context.update(choices(rows, p))
    chosen = context["selected_reference"]
    selected = set((chosen or {}).get("bindings", {})) | {
        cid for v in context["selected_points"] for cid in v["citation_ids"]
    }
    excluded = {
        cid
        for v in [*context["excluded_references"], *context["excluded_points"]]
        for cid in v["citation_ids"]
    }
    rows = [r for r in rows if r["claim_id"] not in excluded]
    rows.sort(key=lambda r: r["claim_id"] not in selected)
    totals: dict[str, int] = {}
    minimal = []
    for r in rows:
        source = db.connection.execute(
            "SELECT policy_id FROM sources WHERE source_id=? AND account_scope=?",
            (r["source_id"], scope),
        ).fetchone()
        policy = EvidenceStore(db)._latest_policy(source[0]) if source else None
        if not policy or not policy_allows_model(policy, external=True, now=db.clock()):
            continue
        relation = r.get("route_association")
        relationship = (
            dict(object_quote=relation["object_quote"], scope=relation["scope"])
            if relation and relation.get("object_quote")
            else None
        )
        texts = [r["text"], *r.get("conditions", [])]
        if relationship:
            texts.append(relationship["object_quote"])
        if any(
            "\n".join(b.text for b in outbound_blocks(body_blocks(text))) != text.strip()
            for text in texts
        ):
            continue
        size = sum(map(len, texts))
        if (r["source_id"] not in totals and len(totals) >= 2) or totals.get(
            r["source_id"], 0
        ) + size > 6000:
            continue
        totals[r["source_id"]] = totals.get(r["source_id"], 0) + size
        minimal.append(
            dict(
                citation_id=r["claim_id"],
                text=r["text"],
                conditions=r.get("conditions", []),
                role=r["reference_kind"],
                review=r["review_status"],
                topic=r["topic"],
                duration_scope=r.get("duration_scope", "UNKNOWN"),
                route_association=relationship,
            )
        )
    # Historical citations and route titles cannot bypass current policy filtering.
    # Only stable IDs and the independently filtered references carry source material.
    for name in ("selected", "excluded"):
        values = [context[name]] if name == "selected" else context[name]
        cleaned = [
            dict(option_id=v["option_id"], activity_ids=v["activity_ids"], order=v["order"])
            for v in values
            if v
        ]
        context[name] = (cleaned[0] if cleaned else None) if name == "selected" else cleaned
    context["material_coverage"] = dict(
        gap_keys=[g["key"] for g in (p.get("automatic_coverage") or {}).get("gaps", [])],
        meaning="仅为本机资料充分性提示，非现实可行性结论。",
    )
    # The same filter used for user input summaries removes unnecessary private locations.
    probe = deepcopy(p)
    probe["request"] = question
    safe_question = model_context(probe)["user_inputs"][-1]
    sent_ids = {r["citation_id"] for r in minimal}
    if any(not set(point["citation_ids"]) & sent_ids for point in context["selected_points"]):
        raise ValueError("QUESTION_SELECTED_MATERIAL_UNAVAILABLE")
    for point in context["selected_points"]:
        point["citation_ids"] = [cid for cid in point["citation_ids"] if cid in sent_ids]
    result = dict(
        protocol="CACHED_QUESTION_V1",
        question=safe_question,
        conditions={k: p["draft"][k] for k in ("days", "driving", "transport", "pace")},
        budget_conditions={
            k: p["draft"]["trip_budget"][k]
            for k in ("people", "rooms", "nights", "target_fen", "lodging_scope")
        },
        timing_conditions=dict(
            first_day=p["draft"]["first_day"],
            activity_start=p["draft"]["inputs"]["activity_start"],
            start_constraint=p["draft"]["start_constraint"],
            return_deadline=p["draft"]["return_deadline"],
        ),
        walking_conditions={k: p["draft"][k] for k in ("walking_allowed", "walking_origin")},
        conversation=context,
        references=minimal,
        route_options=[
            dict(option_id=c["option_id"], citation_ids=list(c["bindings"]))
            for c in project(rows, p)["cards"]
            if set(c["bindings"]) <= sent_ids
        ],
        content_points=[
            dict(option_id=c["option_id"], citation_ids=list(c["bindings"]))
            for c in project(rows, p)["points"]
            if set(c["bindings"]) <= sent_ids
        ],
        iteration_decision=p.get("conversation_iteration_decision"),
        instructions="回答用户本次问题，结合conversation中的当前路线选择与排除。selected_reference是暂定方向，selected_points是本次正文兴趣；excluded_references/excluded_points本轮不选，不照抄为推荐。route_options仅是有证明对象的备选，content_points是正文参考，不能凭ID推断活动或套用其他对象的时长。引用只来自references，条件和作者角色保留。advice是可修改建议，不生成新的来源事实，不保证开放、价格、班次或可行性。资料不足列入gaps，可提出后续研究建议但不能调用工具。proposed_conditions只解释本次意图，未经用户确认不改变行程。",
    )
    from travel_agent.research.reference_identity import aliases
    proven_aliases = aliases([r for r in rows if r["claim_id"] in sent_ids])
    if proven_aliases:
        result["reference_aliases"] = proven_aliases
    if SENSITIVE_RESEARCH_TEXT.search(json.dumps(result, ensure_ascii=False)):
        raise ValueError("QUESTION_SENSITIVE_INPUT")
    return result


def create(
    db: Any,
    scope: str,
    sid: str,
    p: dict[str, Any],
    revision: int,
    question: str,
    key: str,
    *,
    consent: str = CONSENT,
) -> str:
    from .workbench import authorize

    if (
        db.connection.execute(
            "SELECT 1 FROM planning_tasks WHERE session_id=? AND status IN ('QUEUED','RUNNING')",
            (sid,),
        ).fetchone()
        or db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE session_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (sid,),
        ).fetchone()
    ):
        raise ValueError("RUNNING")
    data = payload(db, scope, sid, p, question)
    if not data["references"]:
        # Reject before granting or reserving a request; startup failure is not a question.
        raise ValueError("QUESTION_MATERIAL_REQUIRED")
    authorize(
        db,
        scope,
        sid,
        p,
        OperationAuthorization(confirm=True, tasks=["QUESTION"], model=1, hours=1),
    )
    jid = "question-" + uuid4().hex
    request = dict(
        task="cached_travel_question_v1", payload=data, question=question, consent=consent
    )
    db.connection.execute(
        "INSERT INTO preview_jobs VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL,?,NULL)",
        (
            jid,
            p["operation_grant"],
            sid,
            scope,
            revision,
            jid,
            json.dumps(request, ensure_ascii=False),
            key,
            fingerprint(data),
            "QUEUED",
            db.stamp(),
        ),
    )
    p["answer_job_id"] = jid
    return jid


def view(db: Any, scope: str, p: dict[str, Any]) -> dict[str, Any] | None:
    row = db.connection.execute(
        "SELECT job_id,status,summary_json FROM preview_jobs WHERE job_id=? AND account_scope=? AND research_id LIKE 'question-%'",
        (p.get("answer_job_id"), scope),
    ).fetchone()
    if not row:
        return None
    return dict(
        job_id=row["job_id"], status=row["status"], **json.loads(row["summary_json"] or "{}")
    )


def validate(raw: Any, data: dict[str, Any]) -> Answer:
    value = Answer.model_validate(validate_structured(raw, Answer.model_json_schema()))
    if not set(value.citation_ids) <= {r["citation_id"] for r in data["references"]}:
        raise ValueError("QUESTION_UNKNOWN_REFERENCE")
    if SENSITIVE_RESEARCH_TEXT.search(value.model_dump_json()) or re.search(
        r"https?://|(?<!不)(?<!不能)(?<!无法)保证|一定不会|肯定不会|[路街巷]\s*\d+号",
        value.model_dump_json(),
    ):
        raise ValueError("QUESTION_UNSUPPORTED_OR_SENSITIVE_OUTPUT")
    return value


def run(database: Path, jid: str, provider: Any = None) -> None:
    from .flow import PlanningService
    from .workbench import DailyBudget
    from .conversation import message
    from .automatic import save
    from travel_agent.preview.worker import configured_provider

    with Database(database) as db:
        with db.transaction():
            row = db.connection.execute(
                "SELECT * FROM preview_jobs WHERE job_id=? AND research_id LIKE 'question-%'",
                (jid,),
            ).fetchone()
            if (
                not row
                or db.connection.execute(
                    "UPDATE preview_jobs SET status='RUNNING' WHERE job_id=? AND status='QUEUED' AND cancel_requested=0",
                    (jid,),
                ).rowcount
                != 1
            ):
                return
        request = json.loads(row["request_json"])
        budget = DailyBudget(db, row["continuation_id"])
        try:

            def current() -> tuple[Any, dict[str, Any]]:
                budget.check_trip(row["account_scope"], row["session_id"])
                budget.task("QUESTION")
                budget.check_permit("MODEL", jid)
                budget.check_job_active(jid)
                live, state = PlanningService(db, row["account_scope"]).load(row["session_id"])
                if (
                    live["revision"] != row["request_revision"]
                    or state["planning"].get("answer_job_id") != jid
                    or payload(
                        db,
                        row["account_scope"],
                        row["session_id"],
                        state["planning"],
                        request["question"],
                    )
                    != request["payload"]
                ):
                    raise ValueError("STALE_QUESTION")
                return live, state

            current()
            provider = provider or configured_provider()
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            answer = validate(
                provider.structured(
                    "cached_travel_question_v1", request["payload"], Answer.model_json_schema()
                ),
                request["payload"],
            )
            with db.transaction():
                _, state = current()
                p = state["planning"]
                citations = [
                    r
                    for r in request["payload"]["references"]
                    if r["citation_id"] in answer.citation_ids
                ]
                message(
                    p,
                    "ASSISTANT",
                    answer.advice,
                    origin="AI_CACHED_ADVICE",
                    citations=citations,
                    gaps=answer.gaps,
                    intent=answer.intent,
                    proposed_conditions={
                        k: v
                        for k, v in answer.proposed_conditions.model_dump(exclude_none=True).items()
                        if p["draft"].get(k) != v
                    },
                )
                p.pop("pending_ai_question", None)
                p["proposed_conversation_conditions"] = dict(
                    values={
                        k: v
                        for k, v in answer.proposed_conditions.model_dump(exclude_none=True).items()
                        if p["draft"].get(k) != v
                    },
                    draft_hash=fingerprint(p["draft"]),
                    answer_job_id=jid,
                )
                save(db, row["session_id"], state, bump=False)
                db.connection.execute(
                    "UPDATE preview_jobs SET status='COMPLETED',summary_json=?,finished_at=? WHERE job_id=?",
                    (json.dumps(dict(origin="AI_CACHED_ADVICE", answered=True)), db.stamp(), jid),
                )
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z0-9_]+", str(exc))
                else "QUESTION_FAILED"
            )
            db.connection.execute(
                "UPDATE preview_jobs SET status='FAILED',summary_json=?,finished_at=? WHERE job_id=? AND status='RUNNING'",
                (json.dumps(dict(reason=reason)), db.stamp(), jid),
            )
        finally:
            db.connection.execute(
                "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
                (db.stamp(), row["continuation_id"]),
            )
