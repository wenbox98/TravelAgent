"""One reserved agent model call per child, with durable dispatch and late-result fences."""

import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4
from travel_agent.persistence.database import Database
from travel_agent.preview.projection import fingerprint
from travel_agent.providers.llm import OpenAICompatibleProvider, validate_structured
from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT
from .agent_contract import Understanding, Decision
from .flow import PlanningService
from .workbench import DailyBudget


def binding(p: dict[str, Any]) -> str:
    from .conversation import model_context

    return fingerprint([p["destination"], p["draft"], model_context(p)])


def create(
    db: Any,
    scope: str,
    sid: str,
    revision: int,
    p: dict[str, Any],
    purpose: str,
    payload: dict[str, Any],
    key: str,
) -> str:
    if purpose not in {"travel_intake_v1", "travel_supervisor_v1", "cached_travel_question_v1"}:
        raise ValueError("AGENT_MODEL_PURPOSE_DENIED")
    jid = "agent-" + uuid4().hex
    DailyBudget(db, p["operation_grant"]).reserve("MODEL", jid)
    p["agent_model_job_id"] = jid
    request = dict(task=purpose, payload=payload, binding=binding(p))
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
            fingerprint(request),
            "QUEUED",
            db.stamp(),
        ),
    )
    return jid


def run(database: Path, jid: str, provider: Any = None) -> None:
    from travel_agent.preview.worker import configured_provider
    from .agent_contract import understanding, decision

    with Database(database) as db:
        with db.transaction():
            row = db.connection.execute(
                "SELECT * FROM preview_jobs WHERE job_id=? AND research_id LIKE 'agent-%'", (jid,)
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
        response_received = False
        normalizations: list[dict[str, Any]] = []

        def current() -> None:
            budget.check_trip(row["account_scope"], row["session_id"])
            budget.task("PLANNING")
            budget.check_permit("MODEL", jid)
            budget.check_job_active(jid)
            live, state = PlanningService(db, row["account_scope"]).load(row["session_id"])
            p = state["planning"]
            if live["revision"] != row["request_revision"] or binding(p) != request["binding"]:
                raise ValueError("STALE_PROPOSAL")
            if "references" in request["payload"]:
                from .questions import payload

                from .agent_contract import CONSENT, CURRENT_CONSENT
                v4 = request["task"] == "travel_supervisor_v1" and budget.state()["gate"].get("consent") in {CONSENT, CURRENT_CONSENT}
                fresh = payload(db, row["account_scope"], row["session_id"], p, p["agent_input"],
                                source_limit=20 if budget.state()["gate"].get("consent") == CURRENT_CONSENT else 6 if v4 else 2, prefer_new=v4)
                if fresh["references"] != request["payload"]["references"]:
                    raise ValueError("AGENT_MATERIAL_CHANGED")

        try:
            current()
            provider = provider or configured_provider()
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            purpose = request["task"]
            from .questions import Answer, validate as validate_answer

            schemas = dict(
                travel_intake_v1=Understanding.model_json_schema(),
                travel_supervisor_v1=Decision.model_json_schema(),
                cached_travel_question_v1=Answer.model_json_schema(),
            )
            raw = provider.structured(purpose, request["payload"], schemas[purpose])
            response_received = True
            if purpose == "travel_intake_v1":
                parsed = understanding(raw, request["payload"]["user_text"])
                result = parsed.model_dump()
                normalizations = parsed._normalizations
            elif purpose == "travel_supervisor_v1":
                result = decision(raw).model_dump()
            else:
                validate_structured(raw, schemas[purpose])
                result = validate_answer(raw, request["payload"]).model_dump()
            serialized = json.dumps(result, ensure_ascii=False)
            if SENSITIVE_RESEARCH_TEXT.search(serialized) or re.search(
                r"https?://|小区|单元|门牌|楼栋|[路街巷]\s*\d+号", serialized, re.I
            ):
                raise ValueError("AGENT_UNSAFE_RESPONSE")
            with db.transaction():
                current()
                summary = dict(
                    result=result,
                    model_executed=True,
                    purpose=purpose,
                    input_hash=fingerprint(request["payload"]),
                    normalizations=normalizations,
                )
                if isinstance(provider, OpenAICompatibleProvider) and provider.last_diagnostic:
                    summary["diagnostic"] = provider.last_diagnostic.safe_dict()
                db.connection.execute(
                    "UPDATE preview_jobs SET status='COMPLETED',summary_json=?,finished_at=? WHERE job_id=? AND status='RUNNING'",
                    (json.dumps(summary, ensure_ascii=False), db.stamp(), jid),
                )
        except Exception as exc:
            code = str(exc) if re.fullmatch(r"[A-Z0-9_]+", str(exc)) else "AGENT_MODEL_FAILED"
            from .intake_values import IntakeError
            summary = dict(reason=code, purpose=request["task"], model_executed=response_received)
            if isinstance(exc, IntakeError):
                summary["failure"] = exc.failure
            if isinstance(provider, OpenAICompatibleProvider) and provider.last_diagnostic:
                summary["diagnostic"] = provider.last_diagnostic.safe_dict()
                summary["model_executed"] = bool(provider.last_diagnostic.http_attempts)
            db.connection.execute(
                "UPDATE preview_jobs SET status='FAILED',summary_json=?,finished_at=? WHERE job_id=? AND status='RUNNING'",
                (json.dumps(summary), db.stamp(), jid),
            )
