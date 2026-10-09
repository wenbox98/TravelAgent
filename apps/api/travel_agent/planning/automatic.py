"""Durable bounded research -> reviewed material -> advisory proposal orchestration.

Reads never dispatch. A process claims QUEUED once; interrupted work is not retried.
Only a versioned explicit page intent creates a grant. Adoption remains separate.
"""

import json
from pathlib import Path
import re
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from travel_agent.persistence.database import Database
from travel_agent.preview.projection import fingerprint
from travel_agent.preview.service import PreviewService
from .automatic_models import AutomaticAction, AutomaticStart, CONSENT
from .flow import PlanningService
from .flow_models import OperationAuthorization, PlanCreate, PlanDraft
from .workbench import authorize, DailyBudget

ACTIVE = {"QUEUED", "RUNNING", "WAITING_CONFIGURATION"}


def request_for(p: dict[str, Any]) -> Any:
    from travel_agent.research.models import ResearchRequest

    d = p["draft"]
    return ResearchRequest(
        destination=p["destination"],
        days=d.get("days"),
        no_self_drive=d.get("driving") == "NO",
        transport=d.get("transport"),
    )


def coverage(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    from travel_agent.research.advisory_coverage import assess
    from .reference_overview import references, focused

    return assess(
        focused(references(db, scope, sid, p), p), request_for(p), p["draft"]["spatial"]["intent"]
    )


def card_context(db: Any, scope: str, p: dict[str, Any]) -> None:
    """Related knowledge stays independently bound, never becomes place attributes."""
    from travel_agent.knowledge.planning import verify
    from travel_agent.knowledge.store import Library, binding

    p.pop("automatic_context_cards", None)
    cards = verify(db, scope, p)
    sources = {s["source_id"] for c in cards for s in c["sources"]}
    existing = {c["card_id"] for c in cards}
    lengths = {
        s: sum(
            len(c["text"]) + sum(map(len, c["conditions"]))
            for c in cards
            if s in {v["source_id"] for v in c["sources"]}
        )
        for s in sources
    }
    selected = []
    for c in Library(db, scope).search(destination=p["destination"], kind="SOURCE_REFERENCE")[
        "cards"
    ]:
        ids = {s["source_id"] for s in c["sources"]}
        n = len(c["text"]) + sum(map(len, c["conditions"]))
        if (
            c["card_id"] in existing
            or not ids <= sources
            or any(lengths[s] + n > 3000 for s in ids)
        ):
            continue
        selected.append(binding(c))
        for s in ids:
            lengths[s] += n
    p["automatic_context_cards"] = selected


def merge_research(db: Any, scope: str, sid: str, state: dict[str, Any], rid: str) -> None:
    p = state["planning"]
    for name in ("research_ids", "own_research_ids"):
        p[name] = sorted(set(p.get(name, []) + [rid]))
    if not p.get("knowledge_mode"):
        save(db, sid, state, bump=False)
        _activities(db, scope, sid, state)
        return
    # New reviewed research has already been organized by the existing worker.
    # Keep old valid cards, add only cards from sources actually read by this job.
    from travel_agent.knowledge.planning import templates, verify
    from travel_agent.knowledge.store import Library, binding

    read_sources = {
        r[0]
        for r in db.connection.execute(
            "SELECT DISTINCT c.source_id FROM research_runs r JOIN research_run_contents rc USING(run_id) JOIN source_contents c USING(content_id) WHERE r.research_id=? AND c.account_scope=?",
            (rid, scope),
        )
    }
    items = list(p["draft"]["activities"])
    seen = {a["activity_id"] for a in items}
    for c in Library(db, scope).search(destination=p["destination"], kind="SOURCE_REFERENCE")[
        "cards"
    ]:
        if (
            c["spatial_status"] == "MISMATCH"
            or not {s["source_id"] for s in c["sources"]} <= read_sources
        ):
            continue
        for a in templates(c):
            if a.activity_id not in seen:
                items.append(a.model_dump())
                seen.add(a.activity_id)
    library = Library(db, scope)

    def item_sources(a: Any) -> set[str]:
        return {s["source_id"] for r in a["knowledge_refs"] for s in library.get(r)["sources"]}

    items.sort(
        key=lambda a: (
            not (a.get("locked") or a.get("locked_start")),
            not bool(item_sources(a) & read_sources),
        )
    )
    selected: list[dict[str, Any]] = []
    sources: set[str] = set()
    for a in items:
        ids = item_sources(a)
        if len(sources | ids) <= 6 and len(selected) < 12:
            selected.append(a)
            sources |= ids
        elif a.get("locked") or a.get("locked_start"):
            raise ValueError("PLANNING_LOCKED_CONSTRAINT")
    p["automatic_previous_materials"] = p["draft"]["activities"]
    p["draft"]["activities"] = selected
    card_context(db, scope, p)
    cards = verify(db, scope, p)
    db.connection.execute(
        "UPDATE research_continuations SET gate_json=json_set(gate_json,'$.knowledge_bindings',json(?)) WHERE continuation_id=?",
        (json.dumps([binding(c) for c in cards]), p["operation_grant"]),
    )


def save(db: Any, sid: str, state: dict[str, Any], *, bump: bool = True) -> int:
    db.connection.execute(
        "UPDATE preview_sessions SET state_json=?,revision=revision+?,updated_at=? WHERE session_id=?",
        (json.dumps(state, ensure_ascii=False), int(bump), db.stamp(), sid),
    )
    return int(
        db.connection.execute(
            "SELECT revision FROM preview_sessions WHERE session_id=?", (sid,)
        ).fetchone()[0]
    )


def invalidate(db: Any, sid: str, reason: str = "CONDITIONS_CHANGED") -> None:
    """Invalidate first, then let the existing bounded workers close their resources."""
    rows = db.connection.execute(
        "SELECT * FROM planning_tasks WHERE session_id=? AND status IN ('QUEUED','RUNNING','WAITING_CONFIGURATION')",
        (sid,),
    ).fetchall()
    for r in rows:
        db.connection.execute(
            "UPDATE planning_tasks SET status='CANCELED',summary_json=?,finished_at=? WHERE task_id=?",
            (json.dumps(dict(reason=reason)), db.stamp(), r["task_id"]),
        )
        for jid in (r["research_job_id"], r["planning_job_id"]):
            if jid:
                db.connection.execute(
                    "UPDATE preview_jobs SET cancel_requested=1,status='CANCELED' WHERE job_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                    (jid,),
                )
        if r["grant_id"]:
            db.connection.execute(
                "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
                (db.stamp(), r["grant_id"]),
            )
    for row in db.connection.execute(
        "SELECT job_id,continuation_id FROM preview_jobs WHERE session_id=? AND (research_id LIKE 'question-%' OR research_id LIKE 'agent-%') AND status IN ('QUEUED','RUNNING')",
        (sid,),
    ).fetchall():
        db.connection.execute(
            "UPDATE preview_jobs SET status='CANCELED',cancel_requested=1,summary_json=? WHERE job_id=?",
            (json.dumps(dict(reason=reason)), row["job_id"]),
        )
        db.connection.execute(
            "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
            (db.stamp(), row["continuation_id"]),
        )


def recover(db: Any) -> None:
    # Boot does not replay a pending dispatch. Operator can create a NEW intent later.
    for r in db.connection.execute(
        "SELECT DISTINCT session_id FROM planning_tasks WHERE status IN ('QUEUED','RUNNING')"
    ).fetchall():
        invalidate(db, r[0], "SERVER_STOPPED")
    for r in db.connection.execute(
        "SELECT DISTINCT session_id FROM preview_jobs WHERE research_id LIKE 'question-%' AND status IN ('QUEUED','RUNNING')"
    ).fetchall():
        invalidate(db, r[0], "SERVER_STOPPED")
    db.connection.execute(
        "UPDATE planning_tasks SET status='INTERRUPTED' WHERE status='CANCELED' AND json_extract(summary_json,'$.reason')='SERVER_STOPPED'"
    )


def _cached(db: Any, scope: str, sid: str, state: dict[str, Any]) -> None:
    """Select currently valid minimal references, never copy historical preferences."""
    p = state["planning"]
    if p["draft"]["activities"]:
        if p.get("knowledge_mode"):
            card_context(db, scope, p)
        from .guide_assessment import references as guide_references

        p["automatic_cache_sources"] = len(
            {e.get("source_id") for e in guide_references(db, scope, sid, p) if e.get("source_id")}
        )
        return
    from travel_agent.knowledge.store import Library
    from travel_agent.knowledge.planning import templates, verify

    sources: set[str] = set()
    selected: list[Any] = []
    for c in Library(db, scope).search(destination=p["destination"], kind="SOURCE_REFERENCE")[
        "cards"
    ]:
        ids = {s["source_id"] for s in c["sources"]}
        items = templates(c)
        if (
            not items
            or c["spatial_status"] == "MISMATCH"
            or len(sources | ids) > 6
            or len(selected) + len(items) > 12
        ):
            continue
        sources |= ids
        selected += items
    if selected:
        p.update(knowledge_mode=True, knowledge_include_test=False)
        p["draft"]["activities"] = [a.model_dump() for a in selected]
        verify(db, scope, p)
        card_context(db, scope, p)
        p["automatic_cache_sources"] = len(sources)
        return
    # Use raw evidence only through the existing reviewed/versioned projection.
    service = PreviewService(db, scope, "CACHED_PRIVATE_PREVIEW")
    matches = []
    for option in service.researches():
        # Do not evade the library's default test-data exclusion through raw
        # research fallback. Explicit manual inclusion remains in advanced UI.
        if db.connection.execute(
            "SELECT 1 FROM preview_sessions WHERE account_scope=? AND "
            "(research_id=? OR ? IN (SELECT value FROM json_each(state_json,'$.planning.research_ids'))) AND "
            "(json_extract(state_json,'$.planning.validation_trip')=1 OR "
            "json_extract(state_json,'$.planning.demo') IS NOT NULL OR "
            "json_extract(state_json,'$.planning.material_test_input')=1 OR "
            "json_extract(state_json,'$.planning.local_reuse.test_input')=1)",
            (scope, option["research_id"], option["research_id"]),
        ).fetchone():
            continue
        q, _ = service._cache(option["research_id"])
        if json.loads(q["request_json"]).get("destination") == p["destination"]:
            matches.append(option["research_id"])
    p.update(knowledge_mode=False, research_ids=sorted(set(p.get("research_ids", []) + matches)))
    save(db, sid, state, bump=False)
    _activities(db, scope, sid, state)
    from .materials import references

    p["automatic_cache_sources"] = len({e["source_id"] for e in references(db, scope, sid)})


def _activities(db: Any, scope: str, sid: str, state: dict[str, Any]) -> None:
    from .materials import activities, references

    p = state["planning"]
    draft = PlanDraft.model_validate(p["draft"])
    refs = references(db, scope, sid)
    previous = {a["activity_id"]: a for a in p["draft"]["activities"]}
    allowed_sources: set[str] = set()
    chosen: list[dict[str, Any]] = []
    candidates = activities(refs, p["destination"], draft.spatial.intent)
    candidates.sort(
        key=lambda a: (
            not (
                previous.get(a.activity_id, {}).get("locked")
                or previous.get(a.activity_id, {}).get("locked_start")
            )
        )
    )
    for a in candidates:
        ids = {e["source_id"] for e in refs if e["claim_id"] in a.evidence_ids}
        old = previous.get(a.activity_id)
        locked = old and (old.get("locked") or old.get("locked_start"))
        if a.spatial_status == "MISMATCH" or len(allowed_sources | ids) > 6 or len(chosen) >= 12:
            if locked:
                raise ValueError("PLANNING_LOCKED_CONSTRAINT")
            continue
        allowed_sources |= ids
        chosen.append(old or a.model_dump())
    if any(
        (a.get("locked") or a.get("locked_start"))
        and a["activity_id"] not in {c["activity_id"] for c in chosen}
        for a in previous.values()
    ):
        raise ValueError("PLANNING_LOCKED_CONSTRAINT")
    p["automatic_previous_materials"] = list(previous.values())
    p["draft"]["activities"] = chosen


class AutomaticService:
    def __init__(self, db: Any, scope: str):
        self.db, self.scope = db, scope
        self.plans = PlanningService(db, scope, daily_workbench=True)

    def start(self, body: AutomaticStart, key: str) -> dict[str, Any]:
        from .agent_contract import CONSENTS as AGENT_CONSENTS
        payload = ["automatic-start", body.model_dump()]
        with self.db.transaction():
            old = self._receipt(key, payload)
            if old:
                return self.plans.get(old["session_id"])
            if self.db.connection.execute(
                "SELECT 1 FROM planning_tasks WHERE account_scope=? AND status IN ('QUEUED','RUNNING')",
                (self.scope,),
            ).fetchone():
                raise ValueError("RUNNING")
            destination = body.destination
            if body.consent in AGENT_CONSENTS and not destination:
                from .intake import destination_from_idea
                try:
                    destination = destination_from_idea(body.request)
                except ValueError:
                    destination = "待理解目的区域"
            v = self.plans.create(
                PlanCreate(
                    request=body.request,
                    destination=destination,
                    travel_kind=body.travel_kind,
                    knowledge_first=True,
                ),
                key + "-trip",
            )
            self._create(v["session_id"], payload, key, body.request,
                         agent=body.consent in AGENT_CONSENTS, map_consent=bool(body.map_consent),
                         destination_field=body.destination, agent_consent=body.consent)
            return self.plans.get(v["session_id"])

    def _receipt(self, key: str, payload: Any) -> Any:
        if not 8 <= len(key) <= 100:
            raise ValueError("INVALID_INPUT")
        row = self.db.connection.execute(
            "SELECT * FROM planning_tasks WHERE account_scope=? AND idempotency_key=?",
            (self.scope, key),
        ).fetchone()
        if row and row["request_hash"] != fingerprint(payload):
            raise ValueError("IDEMPOTENCY_CONFLICT")
        if row:
            return row
        sid = PreviewService(self.db, self.scope, "CACHED_PRIVATE_PREVIEW")._receipt(
            key, ["automatic-receipt", payload]
        )
        return dict(session_id=sid) if sid else None

    def _create(
        self, sid: str, payload: Any, key: str, text: str, *, followup: bool = False,
        agent: bool = False,
        map_consent: bool = False,
        destination_field: str = "",
        agent_consent: str = "PRIVATE_GOAL_AGENT_V3",
    ) -> None:
        _, state = self.plans.load(sid)
        p = state["planning"]
        if agent and self.db.connection.execute(
            "SELECT 1 FROM planning_tasks WHERE account_scope=? AND session_id!=? AND status IN ('QUEUED','RUNNING')",
            (self.scope,sid),
        ).fetchone():
            raise ValueError("AUTOMATIC_ALREADY_RUNNING")
        invalidate(self.db, sid)
        p["automatic_material_source_limit"] = 6
        if not agent:
            _cached(self.db, self.scope, sid, state)
        tid = "automatic-" + uuid4().hex
        p.pop("automatic_last_intent_key", None)
        p["automatic_task_id"] = tid
        p["automatic_generation"] = p.get("automatic_generation", 0) + 1
        from travel_agent.research.advisory_coverage import limits as research_limits

        from .agent_contract import CONSENT as AGENT_CONSENT, limits as agent_limits
        consent_version = agent_consent if agent else "PRIVATE_CONVERSATION_LOOP_V1" if followup else CONSENT
        limits = research_limits(p["draft"].get("days"), p["travel_kind"] == "REGIONAL")
        if followup:
            limits.update(search=1, detail=2, model=5)
        if agent and agent_consent == AGENT_CONSENT:
            limits = agent_limits(p["draft"].get("days"), p["travel_kind"] == "REGIONAL", followup=followup)
        if agent and map_consent:
            limits.update(map_place=2, map_route=1)
        p["automatic_coverage"] = coverage(self.db, self.scope, sid, p)
        if followup:
            p["conversation_iteration_decision"] = dict(
                p.get("conversation_iteration_decision") or {},
                purpose="UPDATE_ADVICE",
                will_research=not p["automatic_coverage"]["sufficient"],
                gap_keys=[g["key"] for g in p["automatic_coverage"]["gaps"]],
            )
        from .conversation import message, model_context, state as conversation_state

        if not any(
            m["role"] == "USER" and m["text"] == text
            for m in conversation_state(p)["messages"][-3:]
        ):
            message(p, "USER", text)
        from .reference_overview import choices, references, derive, project

        rows = references(self.db, self.scope, sid, p)
        p["reference_model_choices"] = choices(rows, p)
        if project(rows, p)["cards"]:
            derive(self.db, self.scope, sid, p)
        p["conversation_model_context"] = model_context(p)
        # Only sufficient, currently validated material avoids fresh research.
        if p["automatic_coverage"]["sufficient"] and not agent:
            limits.update(connect=0, search=0, detail=0, model=1)
        if agent:
            p["agent_input"] = text
            p["agent_destination_field"] = destination_field
            p["agent_followup"] = followup
            p["agent_rounds"] = []
            p["agent_research_job_ids"] = []
            p.pop("agent_browser_metrics", None)
            p.pop("agent_stop_stage", None)
            p.pop("proposed_conversation_conditions", None)
            p.pop("agent_map_selection",None)
            p["agent_understanding"] = dict(status="QUEUED", model_executed=False,
                                           provisional=not followup)
        status = "QUEUED"
        grant = None
        try:
            authorization=OperationAuthorization(confirm=True,tasks=["RESEARCH","PLANNING"],hours=1,**limits)
            if agent and map_consent:
                authorization.tasks.append("MAP")
            authorize(
                self.db,
                self.scope,
                sid,
                p,
                authorization,
            )
            grant = p["operation_grant"]
            self.db.connection.execute(
                "UPDATE research_continuations SET gate_json=json_set(gate_json,'$.automatic_task_id',?,'$.automatic_generation',?,'$.consent',?) WHERE continuation_id=?",
                (tid, p["automatic_generation"], consent_version, grant),
            )
        except (ValueError, RuntimeError) as exc:
            if str(exc) not in {"CONFIGURED_120_SECOND_PROVIDER_REQUIRED", "NOT_CONFIGURED"}:
                raise
            status = "WAITING_CONFIGURATION"
        revision = save(self.db, sid, state)
        self.db.connection.execute(
            "INSERT INTO planning_tasks(task_id,account_scope,session_id,request_revision,idempotency_key,request_hash,request_json,status,stage,grant_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                tid,
                self.scope,
                sid,
                revision,
                key,
                fingerprint(payload),
                json.dumps(dict(text=text, consent=consent_version, limits=limits)),
                status,
                "INTAKE" if agent else "CACHE",
                grant,
                self.db.stamp(),
            ),
        )

    def action(
        self, sid: str, body: AutomaticAction, key: str, *, followup: bool = False
    ) -> dict[str, Any]:
        payload = ["automatic-action", sid, body.model_dump()]
        with self.db.transaction():
            if self._receipt(key, payload):
                return self.plans.get(sid)
            row, state = self.plans.load(sid)
            p = state["planning"]
            if row["revision"] != body.expected_revision:
                raise ValueError("STALE_REVISION")
            if body.action == "cancel":
                invalidate(self.db, sid, "USER_CANCELED")
                p["automatic_last_intent_key"] = key
                save(self.db, sid, state)
                PreviewService(self.db, self.scope, "CACHED_PRIVATE_PREVIEW")._remember(
                    key, ["automatic-receipt", payload], sid
                )
                return self.plans.get(sid)
            from .agent_contract import CONSENTS as AGENT_CONSENTS
            if body.consent not in {CONSENT, *AGENT_CONSENTS}:
                raise ValueError("OPERATION_NOT_AUTHORIZED")
            if self.db.connection.execute(
                "SELECT 1 FROM planning_tasks WHERE account_scope=? AND session_id!=? AND status IN ('QUEUED','RUNNING','WAITING_CONFIGURATION')",
                (self.scope, sid),
            ).fetchone():
                raise ValueError("AUTOMATIC_ALREADY_RUNNING")
            if body.action == "continue":
                prior = self.db.connection.execute(
                    "SELECT status FROM planning_tasks WHERE task_id=?",
                    (p.get("automatic_task_id"),),
                ).fetchone()
                if prior and prior[0] != "WAITING_CONFIGURATION":
                    raise ValueError("AUTOMATIC_NO_RETRY")
            elif body.action == "revise":
                if not body.text:
                    raise ValueError("INVALID_INPUT")
                if body.consent in AGENT_CONSENTS:
                    self._create(sid, payload, key, body.text, followup=True, agent=True, map_consent=bool(body.map_consent), agent_consent=str(body.consent))
                    return self.plans.get(sid)
                draft = revise(PlanDraft.model_validate(p["draft"]), body.text)
                old = PlanDraft.model_validate(p["draft"])
                labels = {
                    "days": "天数",
                    "driving": "驾驶意愿",
                    "transport": "交通",
                    "pace": "节奏",
                    "walking_allowed": "步行意愿",
                    "spatial": "游玩范围",
                    "inputs": "出行条件",
                    "return_deadline": "返回硬截止",
                    "activities": "旧日序重新分配",
                }
                p["automatic_changes"] = [
                    label
                    for field, label in labels.items()
                    if old.model_dump()[field] != draft.model_dump()[field]
                ]
                p["draft"] = draft.model_dump()
                # Current normalized conditions are authoritative; keep original input history.
                p.setdefault("automatic_input_history", []).append(p["request"])
                p["request"] = body.text
                save(self.db, sid, state, bump=False)
            elif body.action == "research_more":
                if p.get("automatic_coverage", {}).get("sufficient"):
                    raise ValueError("AUTOMATIC_CLARIFY_CHANGE")
            agent_text = body.text or (p.get("agent_input",p["request"]) if body.action == "continue" else
                "继续补充研究" if body.action == "research_more" else "按当前取舍更新建议")
            agent_followup = p.get("agent_followup",False) if body.action == "continue" else True
            self._create(sid, payload, key, agent_text if body.consent in AGENT_CONSENTS else body.text or p["request"],
                         followup=agent_followup if body.consent in AGENT_CONSENTS else followup,
                         agent=body.consent in AGENT_CONSENTS, map_consent=bool(body.map_consent), agent_consent=str(body.consent))
            return self.plans.get(sid)


def revise(before: PlanDraft, text: str) -> PlanDraft:
    from .guide_context import from_request, request_quantity
    from .advisory import request_times, check_transition
    from .spatial import parse_intent

    result = before.model_copy(deep=True)
    parsed = PlanDraft()
    from_request(parsed, text)
    if parsed.days is not None:
        if any(a.day > parsed.days and (a.locked or a.locked_start) for a in before.activities):
            raise ValueError("PLANNING_LOCKED_CONSTRAINT")
        result.days = parsed.days
        # Old AI allocation is input material, not a locked schedule. Clear out-of-range
        # day advice before regeneration; the adopted version remains unchanged.
        result.guide.day_choices = [c for c in result.guide.day_choices if c.day <= parsed.days]
        for a in result.activities:
            if a.day > parsed.days:
                a.day = 1
                a.period = "UNDECIDED"
    if parsed.pace != "UNKNOWN":
        result.pace = parsed.pace
    if re.search(r"不(?:想|要)?自驾|不自己(?:开车|驾驶)|不自驾", text):
        result.driving = "NO"
        if result.transport == "SELF_DRIVE":
            result.transport = "UNKNOWN"
        if result.inputs.mode == "DRIVING":
            result.inputs.mode = "UNKNOWN"
    elif re.search(r"(?:想|要|选择)自驾", text):
        result.driving = "YES"
        result.transport = "SELF_DRIVE"
        result.inputs.mode = "DRIVING"
    if re.search(r"公共交通|公交", text):
        result.transport = "PUBLIC_TRANSIT"
        result.inputs.mode = "TRANSIT"
    if parsed.walking_origin == "USER_EXPLICIT":
        result.walking_allowed, result.walking_origin = (
            parsed.walking_allowed,
            parsed.walking_origin,
        )
    for k, unit in (("people", "(?:个)?人"), ("rooms", "间房"), ("nights", "晚")):
        v = request_quantity(text, unit)
        if v is not None:
            setattr(result.trip_budget, k, v)
    spatial = parse_intent(text, "CITY", False)
    if spatial.origin == "USER_EXPLICIT":
        result.spatial = spatial
    request_times(result, text)
    check_transition(before, result)
    if result.model_dump() == before.model_dump():
        raise ValueError("AUTOMATIC_CLARIFY_CHANGE")
    result.adjustment = "NONE"
    return result


def task_view(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any] | None:
    row = db.connection.execute(
        "SELECT * FROM planning_tasks WHERE task_id=? AND account_scope=? AND session_id=?",
        (p.get("automatic_task_id"), scope, sid),
    ).fetchone()
    if not row:
        return None
    summary = json.loads(row["summary_json"])
    stage = row["stage"]
    research = db.connection.execute(
        "SELECT status,summary_json,research_id FROM preview_jobs WHERE job_id=?",
        (row["research_job_id"],),
    ).fetchone()
    if research and row["stage"] == "RESEARCH":
        stage = (
            "LOGIN_REQUIRED"
            if research[0] == "WAITING_LOGIN"
            else json.loads(research[1] or "{}").get("stage", stage)
        )
    sources = []
    researches = [research] if research else []
    if p.get("agent_research_job_ids"):
        researches = [db.connection.execute(
            "SELECT status,summary_json,research_id FROM preview_jobs WHERE job_id=? AND continuation_id=?",
            (jid, row["grant_id"]),
        ).fetchone() for jid in p["agent_research_job_ids"]]
        researches = [r for r in researches if r]
    seen_sources = set()
    for step in researches:
        for s in db.connection.execute(
            "SELECT DISTINCT s.source_id,s.title,c.retrieved_at,c.content_completeness,c.published_at FROM research_runs r JOIN research_run_contents rc USING(run_id) JOIN source_contents c USING(content_id) JOIN sources s USING(source_id) WHERE r.research_id=? AND c.account_scope=?",
            (step[2], scope),
        ):
            if s["source_id"] in seen_sources:
                continue
            seen_sources.add(s["source_id"])
            url = (
                "https://www.xiaohongshu.com/explore/" + s["source_id"][4:]
                if re.fullmatch(r"xhs:[a-fA-F0-9]{24}", s["source_id"])
                else None
            )
            sources.append(
                dict(
                    title=s["title"],
                    url=url,
                    retrieved_at=s["retrieved_at"],
                    published_at=s["published_at"],
                    completeness=s["content_completeness"],
                    origin="NEW_READ" if s["retrieved_at"] >= row["created_at"] else "CACHE",
                )
            )
    budget = DailyBudget(db, row["grant_id"]).summary() if row["grant_id"] else None
    research_summary = json.loads(research[1] or "{}") if research else {}
    if p.get("agent_research_job_ids"):
        summaries = [json.loads(r[1] or "{}") for r in researches]
        research_summary = dict(research_summary)
        research_summary["report"] = dict(
            candidate_count=sum(s.get("report", {}).get("candidate_count", 0) for s in summaries),
            source_count=sum(s.get("report", {}).get("source_count", 0) for s in summaries),
        )
        research_summary["unique_candidate_count"] = len({i for s in summaries for i in s.get("candidate_source_ids", [])})
        research_summary["duplicate_body_count"] = sum(s.get("duplicate_body_count", 0) for s in summaries)
        research_summary["source_skips"] = [q for s in summaries for q in s.get("source_skips", [])]
        research_summary["query_progress"] = [dict(q, search_number=n) for n,q in enumerate(
            (q for s in summaries for q in s.get("query_progress", [])), 1)]
    if not research:
        from .guide_assessment import references

        seen = set()
        for e in references(db, scope, sid, p):
            if e.get("source_id") not in seen:
                seen.add(e.get("source_id"))
                sources.append(
                    dict(
                        title=e.get("source_title", "本机知识条目"),
                        url=e.get("source_url"),
                        retrieved_at=e.get("retrieved_at"),
                        completeness=e.get("completeness"),
                        origin="CACHE",
                        reference_kind=e.get("reference_kind"),
                    )
                )
    return dict(
        intent_key=p.get("automatic_last_intent_key", row["idempotency_key"]),
        task_id=row["task_id"],
        status=row["status"],
        stage=stage,
        reason=summary.get("reason"),
        sources=sources,
        new_body_count=sum(s["origin"] == "NEW_READ" for s in sources),
        cache_source_count=p.get("automatic_cache_sources", 0),
        research_attempted=bool(budget and budget["used"]["search"]),
        limits=json.loads(row["request_json"])["limits"],
        budget=budget,
        generated=summary.get("generated", False),
        changes=p.get("automatic_changes", []),
        coverage=p.get("automatic_coverage") if p.get("agent_understanding") else research_summary.get("advisory_coverage") or p.get("automatic_coverage"),
        login_state=research_summary.get("login_state", "NOT_CHECKED"),
        search_count=budget["used"]["search"] if budget else 0,
        candidate_count=research_summary.get("report", {}).get("candidate_count", 0),
        unique_candidate_count=research_summary.get("unique_candidate_count", 0),
        accepted_source_count=research_summary.get("report", {}).get("source_count", 0),
        duplicate_body_count=research_summary.get("duplicate_body_count", 0),
        query_progress=research_summary.get("query_progress", []),
        source_skips=research_summary.get("source_skips", []),
        body_attempts=budget["used"]["detail"] if budget else 0,
        research_stop=research_summary.get("research_stop"),
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        understanding=p.get("agent_understanding"),
        agent_rounds=p.get("agent_rounds", []),
        browser_metrics=p.get("agent_browser_metrics", {"measured": False}),
        protocol=json.loads(row["request_json"]).get("consent"),
    )


def run_task(
    database: Path, tid: str, *, research_runner: Any = None, planning_runner: Any = None
) -> None:
    """Runner injection is test-only; HTTP cannot choose providers or substitute results."""
    with Database(database) as probe:
        row = probe.connection.execute("SELECT request_json FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
        from .agent_contract import CONSENTS as AGENT_CONSENTS
        if row and json.loads(row[0]).get("consent") in AGENT_CONSENTS:
            from .agent import run
            run(database, tid)
            return
    with Database(database) as db:
        with db.transaction():
            task = db.connection.execute(
                "SELECT * FROM planning_tasks WHERE task_id=?", (tid,)
            ).fetchone()
            if (
                not task
                or db.connection.execute(
                    "UPDATE planning_tasks SET status='RUNNING' WHERE task_id=? AND status='QUEUED'",
                    (tid,),
                ).rowcount
                != 1
            ):
                return
        scope, sid = task["account_scope"], task["session_id"]
        service = PlanningService(db, scope)

        def current() -> tuple[Any, dict[str, Any]]:
            t = db.connection.execute(
                "SELECT * FROM planning_tasks WHERE task_id=?", (tid,)
            ).fetchone()
            row, state = service.load(sid)
            if (
                t["status"] != "RUNNING"
                or state["planning"].get("automatic_task_id") != tid
                or row["revision"] != t["request_revision"]
            ):
                raise ValueError("STALE_PROPOSAL")
            DailyBudget(db, task["grant_id"]).check_trip(scope, sid)
            return row, state

        def checkpoint(state: dict[str, Any], stage: str) -> int:
            rev = save(db, sid, state)
            db.connection.execute(
                "UPDATE planning_tasks SET request_revision=?,stage=? WHERE task_id=?",
                (rev, stage, tid),
            )
            return rev

        def await_job(jid: str, research: bool) -> Any:
            runner = research_runner if research else planning_runner
            if runner is not None:
                runner(database, jid)
            else:
                from .suggestions import launch

                launch(database, jid, research=research)
            deadline = monotonic() + (2850 if research else 190)
            while True:
                current()
                child = db.connection.execute(
                    "SELECT * FROM preview_jobs WHERE job_id=?", (jid,)
                ).fetchone()
                if child["status"] not in {"QUEUED", "RUNNING", "WAITING_LOGIN"}:
                    return child
                if monotonic() > deadline:
                    raise ValueError("TASK_DEADLINE")
                sleep(0.25)

        try:
            _, state = current()
            p = state["planning"]
            if not coverage(db, scope, sid, p)["sufficient"]:
                from travel_agent.preview.jobs import JobService

                with db.transaction():
                    row, state = current()
                    p = state["planning"]
                    jobs = JobService(db, scope, "CACHED_PRIVATE_PREVIEW", task["grant_id"])
                    job = jobs.create(
                        sid, row["revision"], p["destination"], tid + "-research", ready=True
                    )
                    if not p["draft"]["activities"]:
                        p["knowledge_mode"] = False
                    p["research_job_id"] = job["job_id"]
                    checkpoint(state, "RESEARCH")
                    db.connection.execute(
                        "UPDATE planning_tasks SET research_job_id=? WHERE task_id=?",
                        (job["job_id"], tid),
                    )
                child = await_job(job["job_id"], True)
                info = json.loads(child["summary_json"] or "{}")
                stopped = child["status"] not in {
                    "COMPLETED",
                    "PARTIAL",
                    "NEEDS_REVIEW",
                } or info.get("research_stop") in {
                    "VERIFICATION_REQUIRED",
                    "NEED_LOGIN",
                    "SOURCE_UNAVAILABLE",
                    "ERROR",
                }
                if stopped and info.get("new_evidence_count", 0):
                    with db.transaction():
                        _, state = current()
                        merge_research(db, scope, sid, state, child["research_id"])
                        state["planning"]["automatic_coverage"] = coverage(
                            db, scope, sid, state["planning"]
                        )
                        from .reference_overview import derive

                        try:
                            derive(db, scope, sid, state["planning"])
                        except ValueError:
                            pass
                        checkpoint(state, "RESEARCH")
                if stopped:
                    raise ValueError("RESEARCH_" + (info.get("reason") or child["status"]))
                with db.transaction():
                    _, state = current()
                    p = state["planning"]
                    merge_research(db, scope, sid, state, child["research_id"])
                    p["automatic_coverage"] = info.get("advisory_coverage") or coverage(
                        db, scope, sid, p
                    )
                    p["automatic_research_stop"] = info.get("research_stop")
                    checkpoint(state, "MATERIALS")
            with db.transaction():
                row, state = current()
                p = state["planning"]
                if not p["draft"]["activities"]:
                    from .reference_overview import derive
                    from .conversation import message

                    try:
                        derive(db, scope, sid, p)
                    except ValueError:
                        raise ValueError("NO_REVIEWED_PLAY_MATERIAL") from None
                    message(
                        p,
                        "ASSISTANT",
                        "已有可引用的路线参考，先比较原作者建议和条件。具体玩法与交通不足，尚未生成活动攻略；不会为凑天数编排项目。",
                        origin="LOCAL_REFERENCE_OVERVIEW",
                    )
                    save(db, sid, state, bump=False)
                    db.connection.execute(
                        "UPDATE planning_tasks SET status='PARTIAL',stage='OVERVIEW',summary_json=?,finished_at=? WHERE task_id=? AND status='RUNNING'",
                        (
                            json.dumps(
                                dict(
                                    generated=False,
                                    local_derived=True,
                                    reason="ROUTE_REFERENCE_ONLY",
                                )
                            ),
                            db.stamp(),
                            tid,
                        ),
                    )
                    return
                from .suggestions import create_job

                # Existing workers verify references, current conditions and each proposal.
                jid = create_job(db, scope, sid, row["revision"] + 1, p, tid + "-planning")
                p["job_id"] = jid
                checkpoint(state, "PLANNING")
                db.connection.execute(
                    "UPDATE planning_tasks SET planning_job_id=? WHERE task_id=?", (jid, tid)
                )
            child = await_job(jid, False)
            summary = json.loads(child["summary_json"] or "{}")
            if child["status"] not in {"COMPLETED", "PARTIAL"} or not summary.get("proposals"):
                raise ValueError("PLANNING_" + (summary.get("reason") or child["status"]))
            with db.transaction():
                _, state = current()
                from .conversation import message, options
                from .suggestions import job_view

                message(
                    state["planning"],
                    "ASSISTANT",
                    "已整理出新的建议；来源与交通缺口保留，请先比较取舍。尚未覆盖已采用攻略。",
                    options=options(job_view(db, scope, jid)),
                    origin="AI_PROPOSED",
                )
                save(db, sid, state, bump=False)
                db.connection.execute(
                    "UPDATE planning_tasks SET status=?,stage='RESULT',summary_json=?,finished_at=? WHERE task_id=? AND status='RUNNING'",
                    (
                        "COMPLETED"
                        if p.get("automatic_coverage", {}).get("sufficient")
                        else "PARTIAL",
                        json.dumps(
                            dict(
                                generated=True,
                                material_coverage=p.get("automatic_coverage"),
                                reason="有限建议，来源、交通与逐日缺口仍以结果为准。",
                            )
                        ),
                        db.stamp(),
                        tid,
                    ),
                )
        except Exception as exc:
            # Persist safe codes only. No exception text/payload/keys in diagnostics.
            code = (
                str(exc)
                if isinstance(exc, ValueError) and re.fullmatch(r"[A-Z0-9_]+", str(exc))
                else "TASK_STOPPED"
            )
            with db.transaction():
                db.connection.execute(
                    "UPDATE planning_tasks SET status='BLOCKED',summary_json=?,finished_at=? WHERE task_id=? AND status='RUNNING'",
                    (json.dumps(dict(reason=code)), db.stamp(), tid),
                )
                for r in db.connection.execute(
                    "SELECT research_job_id,planning_job_id FROM planning_tasks WHERE task_id=?",
                    (tid,),
                ):
                    for jid in r:
                        if jid:
                            db.connection.execute(
                                "UPDATE preview_jobs SET status='CANCELED',cancel_requested=1 WHERE job_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                                (jid,),
                            )
        finally:
            db.connection.execute(
                "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
                (db.stamp(), task["grant_id"]),
            )
