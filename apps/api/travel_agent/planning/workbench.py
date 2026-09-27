"""Daily explicit operation grants on the existing ledger; never stage-specific."""

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from travel_agent.preview.projection import fingerprint
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.store import EvidenceStore

KINDS = ("CONNECT", "SEARCH", "DETAIL", "MODEL", "MAP_PLACE", "MAP_ROUTE")
PURPOSE = "PRIVATE_OPERATION"
STATUS_MESSAGES = {
    "NOT_AUTHORIZED": "本次旅行尚未授权外部操作，请先确认用途与上限。",
    "OPERATION_NOT_AUTHORIZED": "当前许可不包含这项用途，可在页面明确追加。",
    "OPERATION_CLOSED": "本次许可已关闭；本地编辑和已有资料仍可使用。",
    "OPERATION_EXPIRED": "本次许可已到期；需要新操作时请明确追加。",
    "BUDGET_EXHAUSTED": "模型额度已用完；可继续本地编辑，或明确追加额度。",
    "RUNNING": "已有任务正在运行，请等待或停止当前任务。",
    "NOT_CONFIGURED": "模型服务未配置；本地选择和编辑仍可用。",
    "BOUNDED_PROVIDER_CHANGED": "服务配置已变化，与当前授权不一致。",
    "MATERIAL_REQUIRED": "尚无可规划的来源活动，请复用本地资料或主动研究。",
    "NO_REMOVABLE_ACTIVITY": "仅剩一个项目或项目已锁定，不能再减少。",
    "UNADOPTED_CHANGES": "请先采用或取消当前修改，再以采用版改选。",
    "ADOPT_FIRST": "请先采用已有安排，再发起局部改选。",
    "CONFIGURED_120_SECOND_PROVIDER_REQUIRED": "模型服务未配置或超时配置不符；未发送请求。",
    "MAP_NOT_CONFIGURED": "高德服务尚未配置；本地操作仍可用。",
    "OPERATION_MATERIAL_CHANGED": "所选资料超出当前许可范围，请明确建立对应许可。",
    "OPERATION_SCOPE_MISMATCH": "当前操作不属于这次旅行的许可，未派发。",
    "OPERATION_PROVIDER_DENIED": "接收服务与当前支持的配置不符，未派发。",
    "REUSE_SOURCE_UNAVAILABLE": "历史资料已过期、范围不符或来源发生变化，未复用。",
    "REUSE_REQUIRES_EMPTY_DRAFT": "请在尚未选择活动的新旅行中复用，已有安排保留。",
    "DAILY_TRIP_REQUIRED": "这是保留的历史验收旅行；请新建独立旅行使用普通操作许可。",
}


def daily(p: dict[str, Any]) -> bool:
    return p.get("runtime_mode") == "DAILY"


def check_active(db: Any, state: dict[str, Any]) -> dict[str, Any]:
    gate = state["gate"]
    if state["finished_at"]:
        raise ValueError("OPERATION_CLOSED")
    if datetime.fromisoformat(gate["expires_at"]) <= db.clock():
        raise ValueError("OPERATION_EXPIRED")
    row = db.connection.execute(
        "SELECT state_json,mode FROM preview_sessions WHERE session_id=? AND account_scope=?",
        (gate["session_id"], state["account_scope"]),
    ).fetchone()
    p = json.loads(row[0]).get("planning", {}) if row else {}
    if (
        not row
        or row[1] != "CACHED_PRIVATE_PREVIEW"
        or not daily(p)
        or p.get("demo")
        or p.get("operation_grant") != state["continuation_id"]
        or p["destination"] != gate["destination"]
    ):
        raise ValueError("OPERATION_SCOPE_MISMATCH")
    return p


class DailyBudget(BoundedBudget):
    def __init__(self, db: Any, identifier: str):
        super().__init__(EvidenceStore(db), identifier)

    @property
    def limits(self) -> dict[str, int]:
        return dict(self.state()["limits"])

    def check_trip(self, scope: str, sid: str, *, bind: bool = False) -> dict[str, Any]:
        s = self.state()
        if (
            s["gate"].get("purpose") != PURPOSE
            or s["account_scope"] != scope
            or s["gate"]["session_id"] != sid
        ):
            raise ValueError("OPERATION_SCOPE_MISMATCH")
        check_active(self.store.db, s)
        return s

    def task(self, task: str) -> None:
        s = self.state()
        check_active(self.store.db, s)
        if task not in s["gate"]["tasks"]:
            raise ValueError("OPERATION_NOT_AUTHORIZED")

    def check_payload(self, data: dict[str, Any]) -> None:
        s = self.state()
        self.task("REVISION" if data.get("protocol_version") == 3 else "PLANNING")
        gate = s["gate"]
        if "RESEARCH" not in gate["tasks"] and not {
            a["activity_id"] for a in data["activities"]
        } <= set(gate["activity_ids"]):
            raise ValueError("OPERATION_MATERIAL_CHANGED")

    def reserve(self, kind: str, identity: str) -> None:
        with self.store.db.transaction():
            s = self.state()
            self.task(
                "RESEARCH"
                if kind in {"CONNECT", "SEARCH", "DETAIL"}
                or identity.startswith(("extract:", "review:"))
                else "MAP"
                if kind.startswith("MAP_")
                else "PLANNING"
            )
            self.reserve_count(kind, identity, s["limits"])

    def reserve_for_trip(self, scope: str, sid: str, kind: str, identity: str) -> None:
        with self.store.db.transaction():
            self.check_trip(scope, sid)
            if kind.startswith("MAP_"):
                self.task("MAP")
            self.reserve_count(kind, identity, self.limits)


def authorize(db: Any, scope: str, sid: str, p: dict[str, Any], proposal: Any) -> None:
    from travel_agent.preview.worker import configured_provider
    from travel_agent.research.retry import _config
    from .discovery import contents

    if not daily(p) or p["demo"] or proposal is None or not proposal.confirm:
        raise ValueError("OPERATION_NOT_AUTHORIZED")
    limits = {k: getattr(proposal, k.lower()) for k in KINDS}
    tasks = sorted(set(proposal.tasks))
    if not any(limits.values()) or not tasks:
        raise ValueError("INVALID_INPUT")
    if (
        (any(limits[k] for k in ("CONNECT", "SEARCH", "DETAIL")) and "RESEARCH" not in tasks)
        or (any(limits[k] for k in ("MAP_PLACE", "MAP_ROUTE")) and "MAP" not in tasks)
        or (limits["MODEL"] and not set(tasks) & {"RESEARCH", "PLANNING", "REVISION"})
    ):
        raise ValueError("INVALID_INPUT")
    config: dict[str, Any] = {"model_disabled": True}
    if limits["MODEL"]:
        provider = configured_provider()
        config = _config(provider, 180)
        if config["host"] != "api.deepseek.com":
            raise ValueError("OPERATION_PROVIDER_DENIED")
    config["workspace"] = sha256(str(db.path.resolve()).encode()).hexdigest()
    if any(limits[k] for k in ("MAP_PLACE", "MAP_ROUTE")):
        from travel_agent.providers.amap import AmapAdapter

        if not AmapAdapter.from_env().configured:
            raise ValueError("MAP_NOT_CONFIGURED")
    previous = p.get("operation_grant")
    if previous:
        close(db, scope, sid, p)
    identifier = "operation-" + uuid4().hex
    material = contents(db, scope, sid, p)
    gate = dict(
        status="PASS",
        purpose=PURPOSE,
        session_id=sid,
        destination=p["destination"],
        tasks=tasks,
        expires_at=(db.clock() + timedelta(hours=proposal.hours)).isoformat(),
        content_ids=sorted(c["content_id"] for c in material),
        activity_ids=sorted(
            {a["activity_id"] for a in p["draft"]["activities"]}
            | {
                lead["lead_id"]
                for lead in p.get("discovery", {}).get("leads", [])
                if not lead["quarantined"]
            }
        ),
        research_ids=sorted(p.get("research_ids", [])),
        recipients=[
            h
            for enabled, h in (
                (limits["MODEL"], "api.deepseek.com"),
                (limits["MAP_PLACE"] + limits["MAP_ROUTE"], "restapi.amap.com"),
                (limits["CONNECT"] + limits["SEARCH"] + limits["DETAIL"], "www.xiaohongshu.com"),
            )
            if enabled
        ],
        authorized_input_hash=fingerprint([p["destination"], p["draft"], tasks]),
    )
    db.connection.execute(
        "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
        (
            identifier,
            scope,
            previous or "EXPLICIT_PAGE_AUTHORIZATION",
            json.dumps(config),
            db.stamp(),
            db.stamp(),
            json.dumps(limits),
            json.dumps(gate),
        ),
    )
    p["operation_grant"] = identifier


def close(db: Any, scope: str, sid: str, p: dict[str, Any]) -> None:
    identifier = p.get("operation_grant")
    if not identifier:
        return
    row = db.connection.execute(
        "SELECT gate_json FROM research_continuations WHERE continuation_id=? AND account_scope=?",
        (identifier, scope),
    ).fetchone()
    if not row or json.loads(row[0]).get("session_id") != sid:
        raise ValueError("OPERATION_SCOPE_MISMATCH")
    db.connection.execute(
        "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
        (db.stamp(), identifier),
    )
    db.connection.execute(
        "UPDATE preview_jobs SET cancel_requested=1,status='CANCELED' WHERE continuation_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
        (identifier,),
    )


def overview(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    from travel_agent.preview.worker import configured_provider
    from travel_agent.providers.amap import AmapAdapter

    history, used = [], dict.fromkeys((k.lower() for k in KINDS), 0)
    for r in db.connection.execute(
        "SELECT continuation_id FROM research_continuations WHERE account_scope=? AND json_extract(gate_json,'$.purpose')=? AND json_extract(gate_json,'$.session_id')=? ORDER BY created_at,rowid",
        (scope, PURPOSE, sid),
    ):
        b = DailyBudget(db, r[0])
        s = b.state()
        v = b.summary()
        expired = datetime.fromisoformat(s["gate"]["expires_at"]) <= db.clock()
        for k in used:
            used[k] += v["used"][k]
        history.append(
            dict(
                **v,
                limits={k.lower(): v for k, v in s["limits"].items()},
                current=r[0] == p.get("operation_grant"),
                expired=expired,
                tasks=s["gate"]["tasks"],
                recipients=s["gate"]["recipients"],
            )
        )
    try:
        provider = configured_provider()
        from travel_agent.research.retry import _config

        configured = _config(provider, 180)["host"] == "api.deepseek.com"
    except ValueError, RuntimeError:
        configured = False
    current = next((v for v in history if v["current"]), None)
    active = bool(current and not current["closed"] and not current["expired"])
    map_configured = AmapAdapter.from_env().configured

    def capability(task: str, configured: bool, enough: bool) -> str:
        if not configured:
            return "NOT_CONFIGURED"
        if not current or task not in current["tasks"]:
            return "NOT_AUTHORIZED"
        if not active:
            return "CLOSED" if current["closed"] else "EXPIRED"
        return "AVAILABLE" if enough else "BUDGET_EXHAUSTED"

    remaining = current["remaining"] if current else dict.fromkeys((k.lower() for k in KINDS), 0)
    running = (
        db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE session_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (sid,),
        ).fetchone()
        is not None
    )
    return dict(
        history=history,
        cumulative_used=used,
        current=current,
        active=active,
        model_configuration="CONFIGURED_NOT_VERIFIED" if configured else "NOT_CONFIGURED",
        map_configuration="CONFIGURED_NOT_VERIFIED" if map_configured else "NOT_CONFIGURED",
        research_status="RUNNING"
        if running
        else capability(
            "RESEARCH",
            configured,
            remaining["search"] > 0 and remaining["detail"] > 0 and remaining["model"] >= 3,
        ),
        map_status=capability(
            "MAP", map_configured, remaining["map_place"] + remaining["map_route"] > 0
        ),
        status="NOT_AUTHORIZED"
        if not current
        else "CLOSED"
        if current["closed"]
        else "EXPIRED"
        if current["expired"]
        else "ACTIVE",
    )


def model_status(db: Any, scope: str, sid: str, p: dict[str, Any]) -> str:
    from .private_budget import PrivatePlanningBudget
    from .suggestions import payload_for
    from travel_agent.preview.worker import configured_provider

    try:
        budget = PrivatePlanningBudget.for_trip(db, sid)
        budget.check_trip(scope, sid)
        budget.task(
            "REVISION" if p["draft"]["adjustment"] in {"FEWER", "LONGER_FIRST"} else "PLANNING"
        )
        if budget.summary()["remaining"]["model"] <= 0:
            return "BUDGET_EXHAUSTED"
        if db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE session_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (sid,),
        ).fetchone():
            return "RUNNING"
        provider = configured_provider()
        budget.check_provider(provider)
        budget.check_payload(payload_for(p, db, scope, sid))
        return "AVAILABLE"
    except ValueError as exc:
        code = str(exc)
        return {
            "BOUNDED_GRANT_MISSING": "NOT_AUTHORIZED",
            "CONFIGURED_120_SECOND_PROVIDER_REQUIRED": "NOT_CONFIGURED",
            "REVISION_BASE_UNADOPTED": "UNADOPTED_CHANGES",
            "REVISION_NO_REMOVABLE_ACTIVITY": "NO_REMOVABLE_ACTIVITY",
            "REVISION_INTENT_REQUIRED": "ADOPT_FIRST",
            "PLANNING_REFERENCE_UNAVAILABLE": "MATERIAL_REQUIRED",
        }.get(code, code)
    except RuntimeError:
        return "NOT_CONFIGURED"


def reuse_options(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    from .discovery import checked, verify_activity
    from .flow_models import PlanDraft

    result = []
    for row in db.connection.execute(
        "SELECT session_id,state_json FROM preview_sessions WHERE account_scope=? AND session_id!=?",
        (scope, sid),
    ):
        old = json.loads(row[1]).get("planning", {})
        if (
            old.get("demo")
            or old.get("destination") != p["destination"]
            or old.get("travel_kind") != p["travel_kind"]
        ):
            continue
        versions = [*old.get("adoption_history", [])]
        if old.get("adopted"):
            versions.append(dict(version=old.get("adopted_version", 0), draft=old["adopted"]))
        for version in versions:
            try:
                draft = PlanDraft.model_validate(version["draft"])
                context = dict(old, draft=version["draft"])
                leads = checked(db, scope, row[0], context)
                from .materials import references

                allowed = {e["claim_id"] for e in references(db, scope, row[0])}
                for a in draft.activities:
                    if a.provenance == "SOURCE_MENTION":
                        verify_activity(a, leads)
                    elif (
                        a.provenance != "SOURCE_REFERENCE"
                        or not a.evidence_ids
                        or not set(a.evidence_ids) <= allowed
                    ):
                        raise ValueError("REUSE_SOURCE_UNAVAILABLE")
                if draft.activities:
                    result.append(
                        dict(
                            key=fingerprint([row[0], version]),
                            session_id=row[0],
                            version=version["version"],
                            activities=[a.model_dump() for a in draft.activities],
                        )
                    )
            except ValueError:
                continue
    return result


def reuse(
    db: Any, scope: str, sid: str, p: dict[str, Any], key: str, activity_ids: list[str]
) -> None:
    from .flow import PlanningService
    from .discovery import checked

    choice = next((v for v in reuse_options(db, scope, sid, p) if v["key"] == key), None)
    if (
        not choice
        or not activity_ids
        or len(set(activity_ids)) != len(activity_ids)
        or not set(activity_ids) <= {a["activity_id"] for a in choice["activities"]}
    ):
        raise ValueError("REUSE_SOURCE_UNAVAILABLE")
    if p.get("adopted") or p["draft"]["activities"]:
        raise ValueError("REUSE_REQUIRES_EMPTY_DRAFT")
    _, state = PlanningService(db, scope).load(choice["session_id"])
    old = state["planning"]
    leads = checked(db, scope, choice["session_id"], old)
    selected = [deepcopy(a) for a in choice["activities"] if a["activity_id"] in activity_ids]
    for a in selected:
        a["locked_start"] = None
    p["draft"]["activities"] = selected
    p["discovery"] = dict(
        version=1, leads=[deepcopy(leads[i]) for a in selected for i in a["discovery_ids"]]
    )
    p["reuse_materials"] = [
        dict(
            source_session=choice["session_id"],
            source_version=choice["version"],
            source_choice=choice["key"],
            content_id=lead["content_id"],
            source_id=lead["source_id"],
            content_hash=lead["content_hash"],
        )
        for lead in p["discovery"]["leads"]
    ]
    p["research_ids"] = list(old.get("research_ids", []))
    p["reused_claim_ids"] = sorted({i for a in selected for i in a["evidence_ids"]})
    p["collapsed"]["activities"] = False


def local_contents(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    from travel_agent.research.content_store import SourceContentStore

    bindings = list(p.get("reuse_materials", []))
    ids = p.get("research_ids", [])
    if p.get("research_job_id"):
        row = db.connection.execute(
            "SELECT research_id FROM preview_jobs WHERE job_id=? AND session_id=? AND account_scope=?",
            (p["research_job_id"], sid, scope),
        ).fetchone()
        if row:
            ids = [*ids, row[0]]
    for rid in ids:
        if not db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE research_id=? AND session_id=? AND account_scope=?",
            (rid, sid, scope),
        ).fetchone():
            continue
        for row in db.connection.execute(
            "SELECT c.* FROM research_run_contents x JOIN research_runs r USING(run_id) JOIN research_questions q USING(research_id) JOIN source_contents c USING(content_id) WHERE r.research_id=? AND q.account_scope=? AND r.revision=q.current_revision AND json_extract(q.request_json,'$.destination')=?",
            (rid, scope, p["destination"]),
        ):
            bindings.append(dict(row))
    result = {}
    for binding in bindings:
        for c in SourceContentStore(db).load(binding["source_id"], scope, purge=False):
            if (
                c["content_id"] == binding["content_id"]
                and c["content_hash"] == binding["content_hash"]
            ):
                result[c["content_id"]] = c
    return list(result.values())
