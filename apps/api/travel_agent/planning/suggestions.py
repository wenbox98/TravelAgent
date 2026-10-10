"""Bounded planning task on preview_jobs + continuation_operations; no research."""

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from travel_agent.persistence.database import Database
from travel_agent.preview.projection import fingerprint, safe_text
from travel_agent.preview.worker import configured_provider
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.retry import _config
from travel_agent.research.store import EvidenceStore
from travel_agent.settings import PROJECT_ROOT
from .flow_models import (
    PlanDraft,
    PlanningResponse,
    ArrangementResponse,
    RevisionResponse,
    RevisionProposal,
)

IDENTIFIER = "p04-planning-synthetic-two"
_launch_lock = threading.Lock()
_workers: dict[tuple[str, str], subprocess.Popen[Any] | None] = {}
_closing: set[str] = set()


def grant(db: Database, scope: str, provider: OpenAICompatibleProvider) -> None:
    """Explicit CLI authorization only. Boot/read/restart cannot create a grant."""
    config = _config(provider, 180)
    if config["host"] != "api.deepseek.com" or provider.timeout != 120:
        raise ValueError("PLANNING_PROVIDER_DENIED")
    config["workspace"] = sha256(str(db.path.resolve()).encode()).hexdigest()
    with db.transaction() as con:
        previous = con.execute(
            "SELECT config_json FROM research_continuations WHERE account_scope=? AND limits_json IS NULL ORDER BY created_at DESC LIMIT 1",
            (scope,),
        ).fetchone()
        if previous is None or json.loads(previous[0]) != _config(provider, 180):
            raise ValueError("PLANNING_ORIGINAL_PROVIDER_REQUIRED")
        old = con.execute(
            "SELECT account_scope,config_json FROM research_continuations WHERE continuation_id=?",
            (IDENTIFIER,),
        ).fetchone()
        if old:
            if old[0] != scope or json.loads(old[1]) != config:
                raise ValueError("BOUNDED_GRANT_IMMUTABLE")
            return
        con.execute(
            "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
            (
                IDENTIFIER,
                scope,
                "P04_EXPLICIT_SYNTHETIC_AUTHORIZATION",
                json.dumps(config, sort_keys=True),
                db.stamp(),
                db.stamp(),
                json.dumps({"MODEL": 2}),
                '{"status":"SYNTHETIC_ONLY"}',
            ),
        )


def model_used(db: Database) -> int:
    return int(
        db.connection.execute(
            "SELECT count(*) FROM continuation_operations WHERE continuation_id=? AND kind='MODEL'",
            (IDENTIFIER,),
        ).fetchone()[0]
    )


def payload_for(
    p: dict[str, Any], db: Any = None, scope: str = "", sid: str = ""
) -> dict[str, Any]:
    """Allowlisted synthetic data only. Never serialize UI request/private endpoints."""
    from .flow import demo_activities
    from .advisory import enabled, payload as advisory_payload

    if enabled(p) and db is not None:
        return advisory_payload(db, scope, sid, p)

    if not p["demo"] and db is not None:
        from .private_budget import PrivatePlanningBudget, REVISION_IDENTIFIER

        from .workbench import daily

        if (
            daily(p) and p["draft"].get("adjustment") in {"LONGER_FIRST", "FEWER"}
        ) or PrivatePlanningBudget.for_trip(db, sid).identifier == REVISION_IDENTIFIER:
            from .revisions import payload as revision_payload

            return revision_payload(db, scope, sid, p)
        from .private_payload import payload

        return payload(db, scope, sid, p)

    if p["demo"] not in {"CITY", "REGIONAL"}:
        raise ValueError("PLANNING_SYNTHETIC_ONLY")
    draft = PlanDraft.model_validate(p["draft"])
    catalog = {a.activity_id: a for a in demo_activities(p["demo"])}
    if not draft.activities or any(
        a.activity_id not in catalog
        or (a.name, a.region, a.provenance, a.evidence_ids)
        != (catalog[a.activity_id].name, catalog[a.activity_id].region, "SYNTHETIC_TEST", [])
        for a in draft.activities
    ):
        raise ValueError("PLANNING_SYNTHETIC_ONLY")
    return {
        "purpose": "SYNTHETIC_PLANNING_TEST",
        "travel_kind": p["demo"],
        "destination": "虚构城市甲" if p["demo"] == "CITY" else "虚构山岭乙",
        "scope": draft.inputs.planning_scope,
        "days": draft.days,
        "transport": draft.transport,
        "driving": draft.driving,
        "charter": draft.inputs.charter,
        "first_start": draft.inputs.activity_start,
        "first_day": draft.first_day,
        "first_period": draft.first_period,
        "return_deadline": draft.return_deadline,
        "activities": [
            {
                "activity_id": a.activity_id,
                "name": catalog[a.activity_id].name,
                "region": catalog[a.activity_id].region,
                "day": a.day,
                "locked_start": a.locked_start,
                "stay_min": a.stay_min,
                "stay_max": a.stay_max,
            }
            for a in draft.activities
        ],
        "allowed_citation_ids": [],
        "known_map_values": [],
        "instructions": "提供两种可修改安排，锁定预约不移动；未知交通保留。所有活动地点均虚构。",
    }


def model_available(db: Database, scope: str, p: dict[str, Any], sid: str = "") -> bool:
    from .workbench import daily, model_status

    if daily(p):
        return model_status(db, scope, sid, p) == "AVAILABLE"
    budget: BoundedBudget
    try:
        if not p["demo"]:
            from .private_budget import PrivatePlanningBudget

            budget = PrivatePlanningBudget.for_trip(db, sid)
            PRIVATE_ID = budget.identifier
            payload_for(p, db, scope, sid)
            n = db.connection.execute(
                "SELECT count(*) FROM preview_jobs WHERE continuation_id=? AND research_id LIKE 'planning-%'",
                (PRIVATE_ID,),
            ).fetchone()[0]
            if n >= 2 or budget.summary()["remaining"]["model"] <= 0:
                return False
            from .private_budget import DISCOVERY_IDENTIFIER

            if (
                PRIVATE_ID == DISCOVERY_IDENTIFIER
                and n == 1
                and (
                    p["draft"].get("adjustment", "NONE") == "NONE"
                    or not p.get("adopted")
                    or not any(
                        a.get("timing_origin") == "AI_PROPOSED" for a in p["adopted"]["activities"]
                    )
                )
            ):
                return False
            from .private_budget import REVISION_IDENTIFIER

            if PRIVATE_ID == REVISION_IDENTIFIER:
                from .revisions import base

                first = db.connection.execute(
                    "SELECT * FROM preview_jobs WHERE continuation_id=? ORDER BY created_at,rowid LIMIT 1",
                    (PRIVATE_ID,),
                ).fetchone()
                if first is None:
                    if p["draft"]["adjustment"] != "LONGER_FIRST":
                        return False
                elif first["status"] in {"COMPLETED", "PARTIAL"}:
                    if (
                        p["draft"]["adjustment"] != "FEWER"
                        or p.get("last_revision_adoption", {}).get("job_id") != first["job_id"]
                        or fingerprint(base(p["adopted"]))
                        == json.loads(first["request_json"])["payload"]["base_hash"]
                    ):
                        return False
                else:
                    gate = budget.state()["gate"]
                    if (
                        gate.get("retest_of") != first["job_id"]
                        or p["draft"]["adjustment"] != "LONGER_FIRST"
                    ):
                        return False
            if (
                PRIVATE_ID != REVISION_IDENTIFIER
                and db.connection.execute(
                    "SELECT 1 FROM preview_jobs WHERE continuation_id=? AND research_id LIKE 'planning-%' AND status IN ('FAILED','INTERRUPTED')",
                    (PRIVATE_ID,),
                ).fetchone()
            ):
                return False
            if db.connection.execute(
                "SELECT 1 FROM preview_jobs WHERE continuation_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                (PRIVATE_ID,),
            ).fetchone():
                return False
            budget.check_provider(configured_provider())
            return True
        payload_for(p)
        budget = BoundedBudget(EvidenceStore(db), IDENTIFIER)
        s = budget.state()
        if s["account_scope"] != scope or s["finished_at"] or model_used(db) >= 2:
            return False
        if db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE continuation_id=? AND json_extract(request_json,'$.slot')=?",
            (IDENTIFIER, p["demo"]),
        ).fetchone():
            return False
        budget.check_provider(configured_provider())
        return True
    except ValueError, RuntimeError:
        return False


def create_job(
    db: Database, scope: str, sid: str, revision: int, p: dict[str, Any], key: str
) -> str:
    if not p.get("demo") and p.get("conversation"):
        from .conversation import freeze_context

        freeze_context(db, scope, sid, p)
    if not model_available(db, scope, p, sid):
        raise ValueError("PLANNING_UNAVAILABLE")
    payload = payload_for(p, db, scope, sid)
    jid = "planning-" + uuid4().hex
    identifier, slot = IDENTIFIER, p["demo"]
    from .workbench import daily

    if not p["demo"] or daily(p):
        from .private_budget import PrivatePlanningBudget

        budget_private = PrivatePlanningBudget.for_trip(db, sid)
        identifier, slot = budget_private.identifier, jid
        from .workbench import DailyBudget

        if isinstance(budget_private, DailyBudget):
            budget_private.check_payload(payload)
        from .private_budget import DISCOVERY_IDENTIFIER

        if identifier == DISCOVERY_IDENTIFIER:
            n = db.connection.execute(
                "SELECT count(*) FROM preview_jobs WHERE continuation_id=? AND research_id LIKE 'planning-%'",
                (identifier,),
            ).fetchone()[0]
            slot = "INITIAL_PLAN" if n == 0 else "ADJUST_PLAN"
        from .private_budget import REVISION_IDENTIFIER

        if identifier == REVISION_IDENTIFIER:
            n = db.connection.execute(
                "SELECT count(*) FROM preview_jobs WHERE continuation_id=?", (identifier,)
            ).fetchone()[0]
            slot = (
                "LONGER_FIRST"
                if n == 0
                else ("FEWER" if payload["adjustment"] == "FEWER" else "LONGER_FIRST_RETEST")
            )
        budget_private.reserve_for_trip(scope, sid, "MODEL", slot)
    else:
        BoundedBudget(EvidenceStore(db), IDENTIFIER).reserve_count("MODEL", slot, {"MODEL": 2})
    data = {
        "task": "planning_suggestion",
        "slot": slot,
        "payload": payload,
        "draft": p["draft"],
    }
    if payload.get("protocol_version") == 3:
        data.update(base_revision=revision - 1, base_adopted_version=p.get("adopted_version", 0))
    db.connection.execute(
        "INSERT INTO preview_jobs VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL,?,NULL)",
        (
            jid,
            identifier,
            sid,
            scope,
            revision,
            jid,
            json.dumps(data, ensure_ascii=False),
            key,
            fingerprint(payload),
            "QUEUED",
            db.stamp(),
        ),
    )
    return jid


def job_view(db: Database, scope: str, jid: str) -> dict[str, Any]:
    row = db.connection.execute(
        "SELECT * FROM preview_jobs WHERE job_id=? AND account_scope=? AND research_id LIKE 'planning-%'",
        (jid, scope),
    ).fetchone()
    if row is None:
        raise ValueError("JOB_UNAVAILABLE")
    summary = json.loads(row["summary_json"] or "{}")
    return {
        "job_id": jid,
        "status": row["status"],
        "request_revision": row["request_revision"],
        "proposals": summary.get("proposals", []),
        "reason": summary.get("reason"),
        "provenance": "AI_PROPOSED",
        "diagnostic": summary.get("diagnostic", {}),
        "activity_catalog": summary.get("activity_catalog", []),
        "protocol_version": summary.get("protocol_version", 1),
        "decisions": summary.get("decisions", []),
        "accepted_count": summary.get("accepted_count", len(summary.get("proposals", []))),
        "rejected_count": summary.get("rejected_count", 0),
        "generated_count": summary.get("generated_count"),
        "isolated_count": summary.get("isolated_count", 0),
        "local_diagnostic": summary.get("local_diagnostic", {}),
        "rule_version": summary.get("rule_version"),
        "returned": summary.get("returned", False),
        "parsed": summary.get("parsed", False),
        "base_revision": json.loads(row["request_json"]).get("base_revision"),
        "base_activities": [
            {k: a.get(k) for k in ("activity_id", "name", "stay_min", "stay_max", "rest_minutes")}
            for a in json.loads(row["request_json"]).get("payload", {}).get("activities", [])
        ],
        "can_preview": can_preview(db, scope, row)
        if summary.get("protocol_version") == 3
        else None,
    }


def revision_binding(db: Database, scope: str, row: Any, p: dict[str, Any]) -> dict[str, Any]:
    from .revisions import base

    request = json.loads(row["request_json"])
    if (
        not p.get("adopted")
        or p.get("adopted_version", 0) != request["base_adopted_version"]
        or fingerprint(base(p["adopted"])) != request["payload"]["base_hash"]
    ):
        raise ValueError("STALE_PROPOSAL")
    context = deepcopy(p)
    context["draft"] = request["draft"]
    if payload_for(context, db, scope, row["session_id"]) != request["payload"]:
        raise ValueError("STALE_PROPOSAL")
    return dict(request)


def can_preview(db: Database, scope: str, row: Any) -> bool:
    try:
        from .flow import PlanningService
        from .revisions import base

        _, state = PlanningService(db, scope).load(row["session_id"])
        p = state["planning"]
        revision_binding(db, scope, row, p)
        return row["status"] in {"COMPLETED", "PARTIAL"} and base(p["draft"]) == base(p["adopted"])
    except ValueError, KeyError:
        return False


def revision_proposal(
    db: Database, scope: str, p: dict[str, Any], index: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .revisions import validate

    row = db.connection.execute(
        "SELECT * FROM preview_jobs WHERE job_id=? AND account_scope=?", (p["job_id"], scope)
    ).fetchone()
    if row is None or row["status"] not in {"COMPLETED", "PARTIAL"}:
        raise ValueError("STALE_PROPOSAL")
    request = revision_binding(db, scope, row, p)
    proposals = json.loads(row["summary_json"])["proposals"]
    if index >= len(proposals):
        raise ValueError("STALE_PROPOSAL")
    item = {k: proposals[index][k] for k in RevisionProposal.model_fields}
    result = validate(dict(protocol_version=3, proposals=[item]), request["payload"])
    if result["accepted_count"] != 1:
        raise ValueError("STALE_PROPOSAL")
    return request, result["proposals"][0]


def validate_response(raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    response = PlanningResponse.model_validate(raw).model_dump()
    allowed = {a["activity_id"]: a for a in payload["activities"]}
    for proposal in response["proposals"]:
        ids = [a["activity_id"] for a in proposal["activities"]]
        if (
            len(set(ids)) != len(ids)
            or not set(ids) <= allowed.keys()
            or not set(proposal["citation_ids"]) <= set(payload["allowed_citation_ids"])
        ):
            raise ValueError("PLANNING_UNKNOWN_REFERENCE")
        days = [a["day"] for a in proposal["activities"]]
        if days != sorted(days) or days[0] != payload["first_day"]:
            raise ValueError("PLANNING_INVALID_TIME")
        for activity in proposal["activities"]:
            if activity["stay_max"] < activity["stay_min"] or (
                payload["days"] and activity["day"] > payload["days"]
            ):
                raise ValueError("PLANNING_INVALID_TIME")
        for identifier, activity in allowed.items():
            if activity["locked_start"] and (
                identifier not in ids
                or next(a for a in proposal["activities"] if a["activity_id"] == identifier)["day"]
                != activity["day"]
            ):
                raise ValueError("PLANNING_LOCKED_CONSTRAINT")
        if payload["first_start"] and proposal["first_start"] != payload["first_start"]:
            raise ValueError("PLANNING_LOCKED_ANCHOR")
        if payload["transport"] != "UNKNOWN" and proposal["transport"] != payload["transport"]:
            raise ValueError("PLANNING_LOCKED_TRANSPORT")
        if payload["driving"] == "NO" and proposal["transport"] == "SELF_DRIVE":
            raise ValueError("PLANNING_LOCKED_TRANSPORT")
        for value in [
            proposal["title"],
            proposal["reason"],
            *proposal["assumptions"],
            *proposal["unknowns"],
            *proposal["impacts"],
        ]:
            safe_text(value, 500)
            if re.search(
                r"https?://|保证|已预订|已核实|\d+\s*(?:元|公里|km)|(?:车程|公交|驾车|接驳).{0,8}\d+\s*分钟",
                value,
                re.I,
            ):
                raise ValueError("PLANNING_UNSUPPORTED_FACT")
    return response


def apply_proposal(
    db: Database, scope: str, p: dict[str, Any], revision: int, index: int
) -> dict[str, Any]:
    job = job_view(db, scope, p["job_id"])
    if job["protocol_version"] == 3:
        if not job["can_preview"]:
            raise ValueError("STALE_PROPOSAL")
        request, proposal = revision_proposal(db, scope, p, index)
        draft = PlanDraft.model_validate(request["draft"])
        originals = {a.activity_id: a for a in draft.activities}
        draft.activities = [
            originals[item["activity_id"]].model_copy(
                update={k: item[k] for k in ("day", "stay_min", "stay_max", "rest_minutes")}
                | {"timing_origin": "AI_PROPOSED"}
            )
            for item in proposal["activities"]
        ]
        draft.adjustment, draft.adjustment_minutes = "NONE", None
        p["revision_preview"] = dict(
            job_id=p["job_id"],
            index=index,
            draft_hash=fingerprint(draft.model_dump()),
            preview_revision=revision + 1,
        )
        return draft.model_dump()
    if (
        job["status"] not in {"COMPLETED", "PARTIAL"}
        or (
            job["request_revision"] != revision
            and not (
                (p.get("knowledge_mode") or p.get("draft", {}).get("planning_mode") == "ADVISORY")
                and p.get("knowledge_preview_cancel", {}).get("job_id") == p.get("job_id")
                and p.get("knowledge_preview_cancel", {}).get("restored_revision") == revision
            )
        )
        or index >= len(job["proposals"])
    ):
        raise ValueError("STALE_PROPOSAL")
    if not p["demo"] or job["protocol_version"] == 4:
        stored = db.connection.execute(
            "SELECT session_id,request_json FROM preview_jobs WHERE job_id=? AND account_scope=?",
            (p["job_id"], scope),
        ).fetchone()
        if (
            stored is None
            or payload_for(p, db, scope, stored["session_id"])
            != json.loads(stored["request_json"])["payload"]
        ):
            raise ValueError("STALE_PROPOSAL")
    draft = PlanDraft.model_validate(p["draft"])
    proposal = job["proposals"][index]
    if job["protocol_version"] == 4:
        from .advisory import validate, apply
        from .guide_models import GuideProposal

        current_payload = payload_for(p, db, scope, stored["session_id"])
        checked = validate(
            dict(
                protocol_version=4, proposals=[{k: proposal[k] for k in GuideProposal.model_fields}]
            ),
            current_payload,
        )
        if checked["accepted_count"] != 1:
            raise ValueError("STALE_PROPOSAL")
        return apply(p, checked["proposals"][0])
    if job["protocol_version"] == 2:
        from .arrangements import validate_arrangements

        current_payload = payload_for(p, db, scope, stored["session_id"])
        from .materials import candidate_from_name

        refs = {r["claim_id"]: r for r in current_payload["references"]}
        for a in job["activity_catalog"]:
            supported = candidate_from_name(
                a["name"],
                [refs[i] for i in a["evidence_ids"]],
                p["destination"],
                draft.spatial.intent,
            )
            current_payload["activities"].append(supported.model_dump())
        checked = validate_arrangements(
            {
                "protocol_version": 2,
                "proposals": [
                    {
                        k: v
                        for k, v in proposal.items()
                        if k not in {"proposal_id", "first_start", "transport", "fixed_origin"}
                    }
                ],
            },
            current_payload,
        )
        if checked["accepted_count"] != 1:
            raise ValueError("STALE_PROPOSAL")
    old = {a.activity_id: a for a in draft.activities}
    from .flow_models import Activity

    old.update({a["activity_id"]: Activity.model_validate(a) for a in job["activity_catalog"]})
    arranged = []
    for item in proposal["activities"]:
        a = deepcopy(old[item["activity_id"]])
        a.day, a.stay_min, a.stay_max, a.rest_minutes = (
            item["day"],
            item["stay_min"],
            item["stay_max"],
            item["rest_minutes"],
        )
        a.timing_origin = "AI_PROPOSED"
        arranged.append(a)
    draft.activities = arranged
    if not draft.inputs.activity_start and job["protocol_version"] != 2:
        draft.inputs.activity_start = proposal["first_start"]
        draft.anchor_origin = "AI_PROPOSED"
    # A transport suggestion remains in the proposal, never silently a preference.
    return draft.model_dump()


def run_worker(database: Path, jid: str, provider: Any = None) -> None:
    with Database(database) as db:
        with db.transaction() as con:
            row = con.execute(
                "SELECT * FROM preview_jobs WHERE job_id=? AND research_id LIKE 'planning-%'",
                (jid,),
            ).fetchone()
            if (
                row is None
                or con.execute(
                    "UPDATE preview_jobs SET status='RUNNING' WHERE job_id=? AND status='QUEUED' AND cancel_requested=0",
                    (jid,),
                ).rowcount
                != 1
            ):
                return
        summary: dict[str, Any] = {}
        raw: Any = None
        status = "FAILED"
        try:
            provider = provider or configured_provider()
            budget = BoundedBudget(EvidenceStore(db), row["continuation_id"])
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            data = json.loads(row["request_json"])
            budget.check_permit("MODEL", data["slot"])
            budget.check_job_active(jid)
            from .flow import PlanningService
            from .workbench import DailyBudget, PURPOSE

            if budget.state()["gate"].get("purpose") == PURPOSE:
                DailyBudget(db, row["continuation_id"]).check_payload(data["payload"])

            live, state = PlanningService(db, row["account_scope"]).load(row["session_id"])
            if (
                live["revision"] != row["request_revision"]
                or payload_for(state["planning"], db, row["account_scope"], row["session_id"])
                != data["payload"]
            ):
                raise ValueError("STALE_PROPOSAL")
            modern = data["payload"].get("protocol_version") == 2
            revision_mode = data["payload"].get("protocol_version") == 3
            advisory_mode = data["payload"].get("protocol_version") == 4
            from .advisory import response_schema as guide_response_schema

            raw = provider.structured(
                "planning_advisory_v4"
                if advisory_mode
                else "planning_revision_v3"
                if revision_mode
                else "planning_arrangement_v2"
                if modern
                else "planning_suggestion",
                data["payload"],
                guide_response_schema()
                if advisory_mode
                else RevisionResponse.model_json_schema()
                if revision_mode
                else ArrangementResponse.model_json_schema()
                if modern or revision_mode
                else PlanningResponse.model_json_schema(),
            )
            if advisory_mode:
                from .advisory import validate as validate_guide

                summary = validate_guide(raw, data["payload"])
            elif revision_mode:
                from .revisions import validate

                summary = validate(raw, data["payload"])
            elif modern:
                from .arrangements import validate_arrangements

                summary = validate_arrangements(raw, data["payload"])
            elif data["payload"]["purpose"] == "PRIVATE_PLANNING":
                from .private_payload import ground

                raw, validation_payload, catalog = ground(raw, data["payload"])
                summary = validate_response(raw, validation_payload)
                summary["activity_catalog"] = catalog
            else:
                summary = validate_response(raw, data["payload"])
            current, latest_state = PlanningService(db, row["account_scope"]).load(
                row["session_id"]
            )
            if (data["payload"].get("knowledge_mode") or advisory_mode) and payload_for(
                latest_state["planning"], db, row["account_scope"], row["session_id"]
            ) != data["payload"]:
                raise ValueError("STALE_PROPOSAL")
            budget.check_job_active(jid)
            if current["revision"] != row["request_revision"]:
                raise ValueError("STALE_PROPOSAL")
            status = (
                (
                    "PARTIAL"
                    if summary.get("rejected_count") or summary.get("advisory_status") == "PARTIAL"
                    else "COMPLETED"
                )
                if summary.get("proposals")
                else "FAILED"
            )
        except Exception as exc:
            summary = {
                "reason": str(exc)
                if str(exc)
                in {
                    "STALE_PROPOSAL",
                    "PLANNING_UNKNOWN_REFERENCE",
                    "PLANNING_LOCKED_CONSTRAINT",
                    "PLANNING_LOCKED_ANCHOR",
                    "PLANNING_LOCKED_TRANSPORT",
                    "PLANNING_UNSUPPORTED_FACT",
                    "PLANNING_INVALID_TIME",
                    "PLANNING_UNSAFE_RESPONSE",
                }
                else "PLANNING_NOT_GENERATED"
            }
        if isinstance(provider, OpenAICompatibleProvider) and provider.last_diagnostic:
            summary["diagnostic"] = provider.last_diagnostic.safe_dict()
        saved_input = json.loads(row["request_json"])["payload"]
        if saved_input.get("protocol_version") == 3:
            from .revisions import VERSION as REVISION_VERSION
            from .revision_diagnostics import retain

            summary.update(
                protocol_version=3,
                rule_version=REVISION_VERSION,
                input_hash=fingerprint(saved_input),
            )
            try:
                summary["local_diagnostic"] = retain(db, row, raw, summary)
            except OSError, ValueError, TypeError:
                summary["local_diagnostic"] = dict(
                    replayable=False, reason="RECORD_UNAVAILABLE", adopted_affected=False
                )
        if saved_input.get("protocol_version") == 2:
            from .arrangements import VERSION

            summary.update(
                protocol_version=2, rule_version=VERSION, input_hash=fingerprint(saved_input)
            )
        if saved_input.get("protocol_version") == 4:
            from .advisory import VERSION as GUIDE_VERSION
            from .revision_diagnostics import retain

            summary.update(
                protocol_version=4,
                rule_version=GUIDE_VERSION,
                input_hash=fingerprint(saved_input),
                returned=raw is not None,
                parsed=isinstance(raw, dict),
            )
            try:
                summary["local_diagnostic"] = retain(db, row, raw, summary)
            except OSError, ValueError, TypeError:
                summary["local_diagnostic"] = dict(
                    replayable=False, reason="RECORD_UNAVAILABLE", adopted_affected=False
                )
        with db.transaction() as con:
            if (
                saved_input.get("knowledge_mode") or saved_input.get("protocol_version") == 4
            ) and status in {"COMPLETED", "PARTIAL"}:
                try:
                    latest, state = PlanningService(db, row["account_scope"]).load(
                        row["session_id"]
                    )
                    if (
                        latest["revision"] != row["request_revision"]
                        or payload_for(
                            state["planning"], db, row["account_scope"], row["session_id"]
                        )
                        != saved_input
                    ):
                        raise ValueError("STALE_PROPOSAL")
                except ValueError:
                    status, summary = "FAILED", {"reason": "STALE_PROPOSAL", "protocol_version": 2}
            # Never writes a trip draft or adopted plan. Cancellation/deadline wins.
            con.execute(
                "UPDATE preview_jobs SET status=?,summary_json=?,finished_at=? WHERE job_id=? AND status='RUNNING' AND cancel_requested=0",
                (status, json.dumps(summary, ensure_ascii=False), db.stamp(), jid),
            )


def _finish_answer_grant(db: Any, jid: str) -> None:
    db.connection.execute(
        "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=(SELECT continuation_id FROM preview_jobs WHERE job_id=? AND research_id LIKE 'question-%' AND status NOT IN ('QUEUED','RUNNING'))",
        (db.stamp(), jid),
    )


def _worker_finished(db: Database, jid: str, *, automatic: bool, reason: str,
                     exit_code: int | None = None) -> None:
    """Settle only this dispatch; retain completed children, materials and usage."""
    with db.transaction():
        if automatic:
            task = db.connection.execute(
                "SELECT grant_id,stage,summary_json FROM planning_tasks WHERE task_id=? AND status IN ('QUEUED','RUNNING')",
                (jid,),
            ).fetchone()
            if task:
                summary = json.loads(task["summary_json"] or "{}")
                summary.update(reason=reason, failure=dict(
                    reason=reason, phase=task["stage"], category="PROCESS", exit_code=exit_code,
                ))
                db.connection.execute(
                    "UPDATE planning_tasks SET status='INTERRUPTED',summary_json=?,finished_at=? WHERE task_id=? AND status IN ('QUEUED','RUNNING')",
                    (json.dumps(summary), db.stamp(), jid),
                )
                db.connection.execute(
                    "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,summary_json=json_set(coalesce(summary_json,'{}'),'$.reason',?) WHERE continuation_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                    (reason, task["grant_id"]),
                )
                db.connection.execute(
                    "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
                    (db.stamp(), task["grant_id"]),
                )
        else:
            db.connection.execute(
                "UPDATE preview_jobs SET status='FAILED',summary_json=?,finished_at=? WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                (json.dumps(dict(reason=reason, exit_code=exit_code)), db.stamp(), jid),
            )
        _finish_answer_grant(db, jid)


def launch(
    database: Path,
    jid: str,
    *,
    research: bool = False,
    automatic: bool = False,
    question: bool = False,
) -> None:
    owner = str(database.resolve())
    identity = (owner, jid)
    with _launch_lock:
        if identity in _workers or owner in _closing:
            return
        # Keep the receipt after completion: replay cannot start a second supervisor.
        _workers[identity] = None

    def supervise() -> None:
        task_action = "task-worker"
        if automatic:
            with Database(database) as db:
                row = db.connection.execute("SELECT request_json FROM planning_tasks WHERE task_id=?",(jid,)).fetchone()
                from .agent_contract import CONSENT as AGENT_CONSENT
                if row and json.loads(row[0]).get("consent") == AGENT_CONSENT:
                    task_action = "agent-worker"
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts/product_preview.py"),
            task_action
            if automatic
            else "job-worker"
            if research
            else "answer-worker"
            if question
            else "worker",
            "--job",
            jid,
            "--workspace",
            str(database.resolve().parent),
        ]
        try:
            with _launch_lock:
                if owner in _closing:
                    return
                process = subprocess.Popen(
                    command,
                    cwd=PROJECT_ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                _workers[identity] = process
        except OSError:
            with Database(database) as db:
                if automatic:
                    db.connection.execute(
                        "UPDATE planning_tasks SET status='BLOCKED',summary_json=?,finished_at=? WHERE task_id=? AND status='QUEUED'",
                        ('{"reason":"WORKER_NOT_STARTED"}', db.stamp(), jid),
                    )
                    db.connection.execute(
                        "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=(SELECT grant_id FROM planning_tasks WHERE task_id=?)",
                        (db.stamp(), jid),
                    )
                db.connection.execute(
                    "UPDATE preview_jobs SET status='FAILED',summary_json=? WHERE job_id=? AND status='QUEUED'",
                    ('{"reason":"WORKER_NOT_STARTED"}', jid),
                )
                _finish_answer_grant(db, jid)
            return
        end = monotonic() + (3300 if automatic else 2850 if research else 180)
        # Reuse a connection; each poll is a read, not a migration transaction.
        with Database(database) as db:
            while process.poll() is None:
                row = db.connection.execute(
                    "SELECT CASE WHEN status IN ('CANCELED','INTERRUPTED','BLOCKED') THEN 1 ELSE 0 END,status FROM planning_tasks WHERE task_id=?"
                    if automatic
                    else "SELECT cancel_requested,status FROM preview_jobs WHERE job_id=?",
                    (jid,),
                ).fetchone()
                stop = (
                    row is None
                    or row[0]
                    or row[1] in {"INTERRUPTED", "CANCELED"}
                    or monotonic() >= end
                )
                if stop:
                    if automatic:
                        from .automatic import invalidate

                        task = db.connection.execute(
                            "SELECT session_id FROM planning_tasks WHERE task_id=?", (jid,)
                        ).fetchone()
                        if task:
                            invalidate(db, task[0], "TASK_DEADLINE")
                    db.connection.execute(
                        "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,summary_json=? WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                        ('{"reason":"CANCELED_OR_TOTAL_DEADLINE"}', jid),
                    )
                    _finish_answer_grant(db, jid)
                    if research or automatic:
                        # The reader observes cancellation between API calls and closes
                        # its browser in finally; no asyncio task.cancel into Playwright.
                        try:
                            process.wait(timeout=200)
                        except subprocess.TimeoutExpired:
                            _stop_process(process)
                    else:
                        _stop_process(process)
                    return
                sleep(0.25)
            _worker_finished(db, jid, automatic=automatic, reason="WORKER_EXITED",
                             exit_code=process.returncode)

    def guarded() -> None:
        try:
            supervise()
        except Exception:
            # A monitor failure must not silently abandon RUNNING. Invalidate
            # before waiting for the flow to close its own browser resources.
            with Database(database) as db:
                _worker_finished(db, jid, automatic=automatic, reason="WORKER_MONITOR_FAILED")
            process = _workers.get(identity)
            if process is not None and process.poll() is None:
                try:
                    process.wait(timeout=200 if automatic or research else 5)
                except subprocess.TimeoutExpired:
                    _stop_process(process)

    threading.Thread(target=guarded, daemon=True).start()


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def shutdown_workers(database: Path) -> None:
    """Normal server shutdown invalidates jobs before stopping its own children."""
    owner = str(database.resolve())
    with _launch_lock:
        _closing.add(owner)
        processes = [p for (path, _), p in _workers.items() if path == owner and p is not None]
    from .private_budget import (
        IDENTIFIER as PRIVATE_ID,
        CURRENT_IDENTIFIER,
        DISCOVERY_IDENTIFIER,
        REVISION_IDENTIFIER,
    )

    with Database(database) as db:
        from .automatic import recover

        recover(db)
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,summary_json=? WHERE continuation_id IN (?,?,?,?,?) AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (
                '{"reason":"SERVER_STOPPED"}',
                IDENTIFIER,
                PRIVATE_ID,
                CURRENT_IDENTIFIER,
                DISCOVERY_IDENTIFIER,
                REVISION_IDENTIFIER,
            ),
        )
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1 WHERE continuation_id IN (SELECT continuation_id FROM research_continuations WHERE json_extract(gate_json,'$.purpose')='PRIVATE_OPERATION') AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')"
        )
    for process in processes:
        try:
            process.wait(timeout=200)
        except subprocess.TimeoutExpired:
            _stop_process(process)
