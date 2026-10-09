"""A single explicitly chosen adjacent public leg, on the existing map ledger."""

import json
from typing import Any, Literal
from pydantic import Field
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import fingerprint
from travel_agent.persistence.database import Database
from .flow_models import PlanDraft, OperationAuthorization
from .models import MapAction

CONSENT = "PRIVATE_KEY_LEG_V1"


class CriticalMapAction(StrictModel):
    action: Literal["start", "resolve", "confirm", "route", "close"]
    expected_revision: int = Field(ge=0)
    leg_id: str | None = Field(default=None, max_length=170)
    place_id: str | None = Field(default=None, max_length=80)
    candidate_id: str | None = Field(default=None, max_length=80)
    relation: Literal["SAME_OBJECT", "REGIONAL_REFERENCE", "ACCESS_POINT"] | None = None
    consent: Literal["PRIVATE_KEY_LEG_V1"] | None = None
    leg_depart_at: str | None = None


def binding(p: dict[str, Any]) -> str:
    return fingerprint([p["destination"], p["draft"]])


def view(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    from .discovery import checked, verify_activity
    from .materials import references, candidate_from_name
    from .workbench import DailyBudget, daily
    from travel_agent.providers.amap import AmapAdapter

    draft = PlanDraft.model_validate(p["draft"])
    refs = {r["claim_id"]: r for r in references(db, scope, sid)}
    leads = checked(db, scope, sid, p)
    supported = set()
    for a in draft.activities:
        try:
            if a.provenance == "SOURCE_MENTION":
                verify_activity(a, leads)
            elif (
                a.provenance == "SOURCE_REFERENCE"
                and a.evidence_ids
                and set(a.evidence_ids) <= refs.keys()
            ):
                candidate = candidate_from_name(
                    a.name,
                    [refs[i] for i in a.evidence_ids],
                    p["destination"],
                    draft.spatial.intent,
                )
                if draft.spatial.intent == "CITY_CORE" and candidate.spatial_status != "MATCH":
                    continue
            else:
                continue
            if a.region == p["destination"]:
                supported.add(a.activity_id)
        except ValueError:
            continue
    pairs = [
        dict(
            leg_id=a.activity_id.lower() + "--" + b.activity_id.lower(),
            place_ids=[a.activity_id.lower(), b.activity_id.lower()],
            names=[a.name, b.name],
            day=a.day,
        )
        for a, b in zip(draft.activities, draft.activities[1:])
        if a.day == b.day and a.activity_id in supported and b.activity_id in supported
    ]
    allowed = {"PUBLIC_TRANSIT": "TRANSIT", "WALKING": "WALKING", "SELF_DRIVE": "DRIVING"}.get(
        draft.transport
    )
    mode_valid = draft.inputs.mode != "UNKNOWN" and (
        draft.inputs.mode == allowed
        and not (allowed == "DRIVING" and draft.driving == "NO")
        or draft.inputs.mode == "WALKING"
        and draft.walking_allowed is True
    )
    gaps = []
    if not daily(p) or p.get("demo"):
        gaps.append("仅在普通私人旅行中核实公共路段。")
    if not pairs:
        gaps.append("需要同一天至少两个有来源依据的公共地点；路线概述不会自动拆成景点。")
    if not mode_valid:
        if allowed:
            label = {"DRIVING": "自驾", "TRANSIT": "公共交通", "WALKING": "步行"}[allowed]
            gaps.append(f"已确认{label}意向；仅在核实具体路段前选择与之相符的参考模式，不必重复回答交通偏好。")
        else:
            gaps.append("交通意向可以暂未定，不阻止查资料或生成建议；核实具体路段前才需要选择适用方式，不会把驾车时间当公共交通。")
    if draft.inputs.origin or draft.inputs.destination or draft.inputs.endpoints_private:
        gaps.append("此入口只发送所选公共项目，不发送家庭或往返私址。")
    configured = AmapAdapter.from_env().configured
    task = p.get("critical_map_task")
    current = bool(
        task and task["draft_hash"] == binding(p) and task["leg_id"] in {v["leg_id"] for v in pairs}
    )
    active = False
    remaining = dict(map_place=0, map_route=0)
    if current and task and task["grant_id"] == p.get("operation_grant"):
        try:
            budget = DailyBudget(db, task["grant_id"])
            budget.check_trip(scope, sid)
            budget.task("MAP")
            remaining = {k: budget.summary()["remaining"][k] for k in remaining}
            active = True
        except ValueError:
            pass
    return dict(
        intent_key=p.get("critical_map_intent_key"),
        ready=not gaps,
        configured=configured,
        gaps=gaps,
        pairs=pairs,
        current=current,
        active=active,
        task=task,
        remaining=remaining,
        meaning="一次只核实你确认的一段，最多两个地点查询和一次路径查询；结果是临时估算，接驳、班次与未来可行性仍未知。",
    )


def enrich(value: dict[str, Any], maps: dict[str, Any]) -> dict[str, Any]:
    task = value.get("task") if value["current"] else None
    ids = task["place_ids"] if task else []
    return dict(
        value,
        places=[p for p in maps["places"] if p["place_id"] in ids],
        leg=next((leg for leg in maps["legs"] if task and leg["leg_id"] == task["leg_id"]), None),
        map_result_state=maps["map_result_state"],
    )


def action(service: Any, sid: str, body: CriticalMapAction, key: str) -> None:
    from .flow import PlanningService
    from .workbench import authorize, close
    from .automatic import save
    from travel_agent.preview.service import PreviewService

    data = ["critical-map", sid, body.model_dump()]
    with Database(service.database) as db, db.transaction():
        receipts = PreviewService(db, service.scope, "CACHED_PRIVATE_PREVIEW")
        if receipts._receipt(key, data):
            return
        row, state = PlanningService(db, service.scope).load(sid)
        p = state["planning"]
        if row["revision"] != body.expected_revision:
            raise ValueError("STALE_REVISION")
        status = view(db, service.scope, sid, p)
        if body.action == "close":
            if status["active"]:
                close(db, service.scope, sid, p)
            receipts._remember(key, data, sid)
            db.connection.execute(
                "UPDATE preview_sessions SET state_json=json_set(state_json,'$.planning.critical_map_intent_key',?) WHERE session_id=?",
                (key, sid),
            )
            return
        if body.action == "start":
            if body.consent != CONSENT:
                raise ValueError("OPERATION_NOT_AUTHORIZED")
            if not status["ready"]:
                raise ValueError("KEY_LEG_INPUT_REQUIRED")
            pair = next((v for v in status["pairs"] if v["leg_id"] == body.leg_id), None)
            if not pair:
                raise ValueError("KEY_LEG_INPUT_REQUIRED")
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
            authorize(
                db,
                service.scope,
                sid,
                p,
                OperationAuthorization(
                    confirm=True, tasks=["MAP"], map_place=2, map_route=1, hours=1
                ),
            )
            p["critical_map_task"] = dict(
                **pair, draft_hash=binding(p), grant_id=p["operation_grant"]
            )
            db.connection.execute(
                "UPDATE research_continuations SET gate_json=json_set(gate_json,'$.critical_leg',json(?)) WHERE continuation_id=?",
                (json.dumps(p["critical_map_task"]), p["operation_grant"]),
            )
            save(db, sid, state, bump=False)
            receipts._remember(key, data, sid)
            task = p["critical_map_task"]
        else:
            if not status["current"] or not status["active"]:
                raise ValueError("KEY_LEG_STALE_OR_CLOSED")
            task = status["task"]
            if body.action == "confirm" and body.place_id not in task["place_ids"]:
                raise ValueError("KEY_LEG_INPUT_REQUIRED")
            # Record before I/O: a refresh never resumes a partial request.
            receipts._remember(key, data, sid)
        db.connection.execute(
            "UPDATE preview_sessions SET state_json=json_set(state_json,'$.planning.critical_map_intent_key',?) WHERE session_id=?",
            (key, sid),
        )

    def dispatch(
        kind: Literal["resolve", "confirm_place", "route"], suffix: str, **fields: Any
    ) -> dict[str, Any]:
        latest = service.get(sid)
        return dict(
            service.mutate(
                MapAction(
                    action=kind,
                    session_id=sid,
                    expected_revision=latest["revision"],
                    expected_preview_revision=latest["preview_revision"],
                    send_confirmed=True,
                    **fields,
                ),
                key + suffix,
                _auto_confirm=False,
            )
        )

    if body.action in {"start", "resolve"}:
        for i, pid in enumerate(task["place_ids"]):
            result = dispatch("resolve", "-place-" + str(i), place_id=pid)
            place = next((v for v in result["places"] if v["place_id"] == pid), None)
            if not place or not place["candidates"]:
                break  # no retry, and no second request after a failed first lookup
    elif body.action == "confirm":
        dispatch(
            "confirm_place",
            "-confirm",
            place_id=body.place_id,
            candidate_id=body.candidate_id,
            relation=body.relation,
        )
    elif body.action == "route":
        dispatch("route", "-route", leg_id=task["leg_id"], leg_depart_at=body.leg_depart_at)
