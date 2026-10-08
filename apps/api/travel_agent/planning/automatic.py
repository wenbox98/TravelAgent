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
LIMITS = dict(connect=1, search=1, detail=2, model=5, map_place=0, map_route=0)


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


def recover(db: Any) -> None:
    # Boot does not replay a pending dispatch. Operator can create a NEW intent later.
    for r in db.connection.execute(
        "SELECT DISTINCT session_id FROM planning_tasks WHERE status IN ('QUEUED','RUNNING')"
    ).fetchall():
        invalidate(db, r[0], "SERVER_STOPPED")
    db.connection.execute(
        "UPDATE planning_tasks SET status='INTERRUPTED' WHERE status='CANCELED' AND json_extract(summary_json,'$.reason')='SERVER_STOPPED'"
    )


def _cached(db: Any, scope: str, sid: str, state: dict[str, Any]) -> None:
    """Select currently valid minimal references, never copy historical preferences."""
    p = state["planning"]
    if p["draft"]["activities"]:
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
            or len(sources | ids) > 2
            or len(selected) + len(items) > 8
        ):
            continue
        sources |= ids
        selected += items
    if selected:
        p.update(knowledge_mode=True, knowledge_include_test=False)
        p["draft"]["activities"] = [a.model_dump() for a in selected]
        verify(db, scope, p)
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
    allowed_sources: set[str] = set()
    chosen = []
    for a in activities(refs, p["destination"], draft.spatial.intent):
        ids = {e["source_id"] for e in refs if e["claim_id"] in a.evidence_ids}
        if a.spatial_status == "MISMATCH" or len(allowed_sources | ids) > 2:
            continue
        allowed_sources |= ids
        chosen.append(a.model_dump())
    p["draft"]["activities"] = chosen[:8]


class AutomaticService:
    def __init__(self, db: Any, scope: str):
        self.db, self.scope = db, scope
        self.plans = PlanningService(db, scope, daily_workbench=True)

    def start(self, body: AutomaticStart, key: str) -> dict[str, Any]:
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
            v = self.plans.create(
                PlanCreate(
                    request=body.request,
                    destination=body.destination,
                    travel_kind=body.travel_kind,
                    knowledge_first=True,
                ),
                key + "-trip",
            )
            self._create(v["session_id"], payload, key, body.request)
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

    def _create(self, sid: str, payload: Any, key: str, text: str) -> None:
        _, state = self.plans.load(sid)
        p = state["planning"]
        invalidate(self.db, sid)
        _cached(self.db, self.scope, sid, state)
        tid = "automatic-" + uuid4().hex
        p.pop("automatic_last_intent_key", None)
        p["automatic_task_id"] = tid
        p["automatic_generation"] = p.get("automatic_generation", 0) + 1
        limits = dict(LIMITS)
        # A follow-up with usable material needs one advisory call, no site access.
        if p["draft"]["activities"]:
            limits.update(connect=0, search=0, detail=0, model=1)
        status = "QUEUED"
        grant = None
        try:
            authorize(
                self.db,
                self.scope,
                sid,
                p,
                OperationAuthorization(
                    confirm=True, tasks=["RESEARCH", "PLANNING"], hours=1, **limits
                ),
            )
            grant = p["operation_grant"]
            self.db.connection.execute(
                "UPDATE research_continuations SET gate_json=json_set(gate_json,'$.automatic_task_id',?,'$.automatic_generation',?,'$.consent',?) WHERE continuation_id=?",
                (tid, p["automatic_generation"], CONSENT, grant),
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
                json.dumps(dict(text=text, consent=CONSENT, limits=limits)),
                status,
                "CACHE",
                grant,
                self.db.stamp(),
            ),
        )

    def action(self, sid: str, body: AutomaticAction, key: str) -> dict[str, Any]:
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
            if body.consent != CONSENT:
                raise ValueError("OPERATION_NOT_AUTHORIZED")
            if body.action == "continue":
                prior = self.db.connection.execute(
                    "SELECT status FROM planning_tasks WHERE task_id=?",
                    (p.get("automatic_task_id"),),
                ).fetchone()
                if prior and prior[0] != "WAITING_CONFIGURATION":
                    raise ValueError("AUTOMATIC_NO_RETRY")
            else:
                if not body.text:
                    raise ValueError("INVALID_INPUT")
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
            self._create(sid, payload, key, body.text or p["request"])
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
    elif re.search(r"(?:想|要|选择)自驾", text):
        result.driving = "YES"
        result.transport = "SELF_DRIVE"
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
    if research and row["status"] == "RUNNING" and row["stage"] == "RESEARCH":
        stage = (
            "LOGIN"
            if research[0] == "WAITING_LOGIN"
            else json.loads(research[1] or "{}").get("stage", stage)
        )
    sources = []
    if research:
        for s in db.connection.execute(
            "SELECT DISTINCT s.source_id,s.title,c.retrieved_at,c.content_completeness,c.published_at FROM research_runs r JOIN research_run_contents rc USING(run_id) JOIN source_contents c USING(content_id) JOIN sources s USING(source_id) WHERE r.research_id=? AND c.account_scope=?",
            (research[2], scope),
        ):
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
        created_at=row["created_at"],
        finished_at=row["finished_at"],
    )


def run_task(
    database: Path, tid: str, *, research_runner: Any = None, planning_runner: Any = None
) -> None:
    """Runner injection is test-only; HTTP cannot choose providers or substitute results."""
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
            deadline = monotonic() + (1200 if research else 190)
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
            if not p["draft"]["activities"]:
                from travel_agent.preview.jobs import JobService

                with db.transaction():
                    row, state = current()
                    p = state["planning"]
                    jobs = JobService(db, scope, "CACHED_PRIVATE_PREVIEW", task["grant_id"])
                    job = jobs.create(
                        sid, row["revision"], p["destination"], tid + "-research", ready=True
                    )
                    p["knowledge_mode"] = False
                    p["research_job_id"] = job["job_id"]
                    checkpoint(state, "RESEARCH")
                    db.connection.execute(
                        "UPDATE planning_tasks SET research_job_id=? WHERE task_id=?",
                        (job["job_id"], tid),
                    )
                child = await_job(job["job_id"], True)
                info = json.loads(child["summary_json"] or "{}")
                if child["status"] not in {"COMPLETED", "PARTIAL"} or not info.get(
                    "new_evidence_count"
                ):
                    raise ValueError("RESEARCH_" + (info.get("reason") or child["status"]))
                with db.transaction():
                    _, state = current()
                    p = state["planning"]
                    for name in ("research_ids", "own_research_ids"):
                        p[name] = sorted(set(p.get(name, []) + [child["research_id"]]))
                    save(db, sid, state, bump=False)
                    _activities(db, scope, sid, state)
                    checkpoint(state, "MATERIALS")
            with db.transaction():
                row, state = current()
                p = state["planning"]
                if not p["draft"]["activities"]:
                    raise ValueError("NO_REVIEWED_PLAY_MATERIAL")
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
                current()
                db.connection.execute(
                    "UPDATE planning_tasks SET status='COMPLETED',stage='RESULT',summary_json=?,finished_at=? WHERE task_id=? AND status='RUNNING'",
                    (
                        json.dumps(
                            dict(
                                generated=True,
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
