"""Progressive trip drafts over existing preview storage; local reads only."""

from copy import deepcopy
import json
import re
from math import ceil
from typing import Any

from travel_agent.persistence.database import Database
from travel_agent.preview.projection import parse_preferences, fingerprint
from travel_agent.preview.models import Mode
from travel_agent.preview.service import PreviewService
from .flow_models import Activity, PlanAction, PlanCreate, PlanDraft


def demo_activities(kind: str) -> list[Activity]:
    # Authored fiction, never injected into private cache/evidence. Same names in
    # different regions deliberately exercise identity/ambiguity handling.
    region = (
        "虚构山岭乙区"
        if kind == "REGIONAL"
        else "虚构水城丙区"
        if kind == "OTHER_CITY"
        else "虚构城市甲区"
    )
    names = ["云台园", "纸舟工坊", "星河展厅"]
    return [
        Activity(
            activity_id=f"demo-{i}",
            name=name,
            region=region,
            provenance="SYNTHETIC_TEST",
            day=1 if i < 2 else 2,
        )
        for i, name in enumerate(names)
    ]


def timeline(
    draft: PlanDraft, movements: dict[str, float] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Only activity durations are computable here. Unknown movement is never zero."""
    rows: list[dict[str, Any]] = []
    gaps = ["交通、开放、预约与费用尚未核实；这是可编辑安排，不是可执行结论。"]
    if draft.inputs.planning_scope == "ACTIVITY_WINDOW":
        gaps.append("到达首个项目及活动结束后的路程由你安排，未纳入活动时间核实。")
    else:
        if not draft.inputs.origin or not draft.inputs.destination:
            gaps.append("门到门起终点尚未明确。")
        if not draft.inputs.depart_at or not draft.inputs.return_by:
            gaps.append("门到门出发和最晚返回日期时间尚未明确。")
        gaps.append("往返道路与末端接驳未核实，不能给门到门可行性结论。")
    deadline = draft.return_deadline or draft.inputs.return_by
    if deadline:
        gaps.append(f"硬约束保留：最晚 {deadline} 返回；活动结束不等于到家，返程和接驳仍未知。")
    previous_day = None
    previous = None
    end: list[float] | None = None

    def fmt(n: float) -> str:
        seconds = ceil(n * 60)
        minutes, second = divmod(seconds, 60)
        return (
            (f"+{minutes // 1440}天 " if minutes >= 1440 else "")
            + f"{minutes % 1440 // 60:02d}:{minutes % 60:02d}"
            + (f":{second:02d}" if second else "")
        )

    def clock_minute(value: str, day: int) -> int:
        h, m = map(int, value.split(":"))
        result = h * 60 + m
        if day == draft.first_day and draft.inputs.activity_start and draft.inputs.activity_end:
            sh, sm = map(int, draft.inputs.activity_start.split(":"))
            eh, em = map(int, draft.inputs.activity_end.split(":"))
            if eh * 60 + em <= sh * 60 + sm and result < sh * 60 + sm:
                result += 1440
        return result

    for activity in draft.activities:
        first = previous_day != activity.day
        previous_day = activity.day
        start = activity.locked_start or (
            draft.inputs.activity_start if first and activity.day == draft.first_day else None
        )
        movement = (
            (movements or {}).get(
                previous.activity_id.lower() + "--" + activity.activity_id.lower()
            )
            if previous and not first
            else None
        )
        arrival = (
            [n + previous.rest_minutes + movement for n in end]
            if end
            and previous
            and not first
            and movement is not None
            and previous.rest_minutes is not None
            else None
        )
        if activity.locked_start and arrival:
            locked_minute = clock_minute(activity.locked_start, activity.day)
            if arrival[0] > locked_minute:
                gaps.append(
                    f"时间冲突：按当前条件抵达 {activity.name} 已晚于锁定预约，预约未移动。"
                )
            elif arrival[1] > locked_minute:
                gaps.append(
                    f"可能迟到：{activity.name} 按停留区间上限可能错过锁定预约，请缩短前项或留足余量。"
                )
        if start:
            base = clock_minute(start, activity.day)
            end = (
                None
                if activity.stay_min is None
                else [base + activity.stay_min, base + (activity.stay_max or 0)]
            )

            end_label = "—".join(fmt(n) for n in end) if end else "待停留时间"
        elif arrival:
            start = "—".join(fmt(n) for n in arrival)
            end = (
                [arrival[0] + activity.stay_min, arrival[1] + (activity.stay_max or 0)]
                if activity.stay_min is not None
                else None
            )
            end_label = "—".join(fmt(n) for n in end) if end else "待停留时间"
        else:
            end = None
            end_label = "待交通、停留和休息核实"
        if activity.locked_start and not first and not arrival:
            gaps.append(
                f"{activity.name} 的 {activity.locked_start} 预约锁定；前段交通未知，能否准时抵达尚未核实。"
            )
        if activity.day < draft.first_day or (draft.days and activity.day > draft.days):
            gaps.append(f"{activity.name} 的日序超出当前活动窗口，请调整。")
        if deadline and end and len(deadline) == 5:
            dh, dm = map(int, deadline.split(":"))
            if end[0] > dh * 60 + dm:
                gaps.append(
                    f"时间冲突：{activity.name} 按当前停留建议已晚于返回硬约束；尚未计返程。"
                )
            elif end[1] > dh * 60 + dm:
                gaps.append(f"可能超时：{activity.name} 的停留上限可能超过返回硬约束；尚未计返程。")
        if end and draft.inputs.activity_end:
            h, m = map(int, draft.inputs.activity_end.split(":"))
            window_end = h * 60 + m
            if draft.inputs.activity_start:
                sh, sm = map(int, draft.inputs.activity_start.split(":"))
                if window_end <= sh * 60 + sm:
                    window_end += 1440
            if end[0] > window_end:
                gaps.append(
                    f"时间冲突：{activity.name} 按当前停留安排超出活动结束窗口；可修改活动，不能改写锁定预约。"
                )
        rows.append(
            {
                "activity_id": activity.activity_id,
                "name": activity.name,
                "day": activity.day,
                "start": start
                or (
                    "待交通核实"
                    if not first
                    else {"MORNING": "上午", "AFTERNOON": "下午", "EVENING": "晚上"}.get(
                        draft.first_period if activity.day == draft.first_day else "UNDECIDED",
                        "开始时间待选",
                    )
                ),
                "end": end_label,
                "stay_min": activity.stay_min,
                "stay_max": activity.stay_max,
                "rest_minutes": activity.rest_minutes,
                "movement_minutes": movement,
                "timing_origin": activity.timing_origin,
                "locked": bool(activity.locked_start),
                "meaning": "条件时间草案；未把未知移动或接驳按零计算",
            }
        )
        previous = activity
    if end and draft.inputs.buffer_minutes is not None:
        gaps.append(
            f"用户另留总缓冲 {draft.inputs.buffer_minutes} 分钟；活动结束后窗口为 {fmt(end[0] + draft.inputs.buffer_minutes)}—{fmt(end[1] + draft.inputs.buffer_minutes)}，不含未核实返程。"
        )
    return rows, list(dict.fromkeys(gaps))


class PlanningService:
    def __init__(self, db: Database, scope: str):
        self.db, self.scope = db, scope

    def load(self, sid: str) -> tuple[Any, dict[str, Any]]:
        row = self.db.connection.execute(
            "SELECT * FROM preview_sessions WHERE session_id=? AND account_scope=?",
            (sid, self.scope),
        ).fetchone()
        if row is None:
            raise ValueError("SESSION_UNAVAILABLE")
        state = json.loads(row["state_json"])
        if "planning" not in state:
            raise ValueError("SESSION_UNAVAILABLE")
        return row, state

    def create(self, body: PlanCreate, key: str) -> dict[str, Any]:
        mode: Mode = "SYNTHETIC_DEMO" if body.demo else "CACHED_PRIVATE_PREVIEW"
        service = PreviewService(self.db, self.scope, mode)
        payload = ["planning-create", body.model_dump()]
        with self.db.transaction():
            old = service._receipt(key, payload)
            if old:
                return self.get(old)
            matches = []
            if not body.demo:
                for research in service.researches():
                    q, _ = service._cache(research["research_id"])
                    if (
                        json.loads(q["request_json"]).get("destination", "").strip()
                        == body.destination
                    ):
                        matches.append(research["research_id"])
            # Never pick an arbitrary existing destination. A cache miss is usable.
            view = service.open(matches[0] if len(matches) == 1 else None, "", key + "-open")
            sid = view["session_id"]
            row = self.db.connection.execute(
                "SELECT state_json FROM preview_sessions WHERE session_id=?", (sid,)
            ).fetchone()
            state = json.loads(row[0])
            parsed, _ = parse_preferences(body.request)
            draft = PlanDraft(days=parsed.get("days"), driving=parsed.get("driving", "UNKNOWN"))
            if not body.demo:
                if re.search(r"公共交通|公交", body.request):
                    draft.transport, draft.inputs.mode = "PUBLIC_TRANSIT", "TRANSIT"
                draft.walking_allowed = "步行" in body.request
                match = re.search(
                    r"(?:上午)?(\d{1,2})(?:点|[:：](\d{2})).{0,8}(?:开始|第一|首)", body.request
                )
                if match and int(match[1]) < 24:
                    draft.inputs.activity_start = f"{int(match[1]):02d}:{int(match[2] or 0):02d}"
                    draft.anchor_origin = "USER_CONFIRMED"
            if body.demo:
                draft.days = 2 if body.demo != "REGIONAL" else None
                draft.transport = "PUBLIC_TRANSIT" if body.demo == "CITY" else "UNKNOWN"
                draft.inputs.activity_start = "10:00"
                draft.anchor_origin = "SYNTHETIC_TEST"
                draft.activities = demo_activities(body.demo)
            state["planning"] = {
                "destination": body.destination,
                "request": body.request,
                "travel_kind": body.travel_kind,
                "demo": body.demo,
                "validation_trip": body.validation_trip,
                "research_ids": sorted(matches),
                "research_job_id": None,
                "draft": draft.model_dump(),
                "adopted": None,
                "collapsed": {"activities": True, "conditions": True},
                "job_id": None,
            }
            self.db.connection.execute(
                "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
                (json.dumps(state, ensure_ascii=False), sid),
            )
            service._remember(key, payload, sid)
            return self.get(sid)

    def get(self, sid: str) -> dict[str, Any]:
        row, state = self.load(sid)
        p = state["planning"]
        draft = PlanDraft.model_validate(p["draft"])
        view = PreviewService(self.db, self.scope, row["mode"]).get(sid)
        city = p["travel_kind"] == "CITY"
        directions = [
            {
                "id": "relaxed",
                "label": "少量项目，留足停留和休息",
                "advice": "先选最想体验的项目；交通未知时保留后续时间窗口。",
                "origin": "PRODUCT_DEFAULT",
            },
            {
                "id": "varied",
                "label": "多种体验，交通确认后再加密",
                "advice": "先比较项目顺序，未核实的接驳不计为零。",
                "origin": "PRODUCT_DEFAULT",
            },
        ]
        for option in view["options"]:
            directions.append(
                {
                    "id": option["option_id"],
                    "label": option["label"],
                    "advice": "来源内的草案或日段，选择不代表当前可行。",
                    "origin": "SOURCE_REFERENCE",
                }
            )
        rows, gaps = timeline(draft)
        if draft.transport == "UNKNOWN":
            gaps.insert(
                0,
                "建议比较公共交通与步行；尚未替你选择。"
                if city
                else "可比较自己开车/租车、到集散地后接当地服务、其他不自己驾驶方式；都未落实具体服务。",
            )
        from .suggestions import job_view, model_available
        from .materials import references, activities, scope_gaps
        from .private_budget import PrivatePlanningBudget, IDENTIFIER
        from travel_agent.preview.jobs import JobService

        job = job_view(self.db, self.scope, p["job_id"]) if p["job_id"] else None
        refs = references(self.db, self.scope, sid)
        area_gaps = scope_gaps(p["travel_kind"] == "CITY" and "市区" in p["request"], refs)
        gaps += area_gaps
        candidates = [a.model_dump() for a in activities(refs, p["destination"])]
        if job and job.get("activity_catalog"):
            valid = {e["claim_id"] for e in refs}
            candidates += [a for a in job["activity_catalog"] if set(a["evidence_ids"]) <= valid]
        candidates = list({a["activity_id"]: a for a in candidates}.values())
        private_budget, research_available = None, False
        jobs = JobService(self.db, self.scope, row["mode"], IDENTIFIER)
        research_job = jobs.get(p["research_job_id"]) if p.get("research_job_id") else None
        try:
            budget = PrivatePlanningBudget(self.db)
            budget.check_trip(self.scope, sid)
            private_budget = budget.summary()
            from travel_agent.preview.worker import configured_provider

            budget.check_provider(configured_provider())
            research_available = jobs.index(True)["enabled"] and (
                len(candidates) < 2 or bool(area_gaps)
            )
        except ValueError, RuntimeError:
            pass
        available = model_available(self.db, self.scope, p, sid)
        old = p["adopted"]
        differences = [k for k in p["draft"] if old is not None and p["draft"][k] != old.get(k)]
        return {
            "session_id": sid,
            "revision": row["revision"],
            "destination": p["destination"],
            "request": p["request"],
            "travel_kind": p["travel_kind"],
            "demo": p["demo"],
            "mode": row["mode"],
            "draft": draft.model_dump(),
            "adopted": old,
            "collapsed": p["collapsed"],
            "directions": directions,
            "timeline": rows,
            "gaps": gaps,
            "differences": differences,
            "evidence_count": len(refs) if not p["demo"] else view["evidence_count"],
            "direction_change_pending": p.get("direction_backup") is not None,
            "cache_message": "合成活动测试，非真实攻略或地图。"
            if p["demo"]
            else "当前目的地有已审核缓存；原条件和引用保留。"
            if refs
            else "当前目的地没有匹配的已审核资料；可自行添加活动或比较规划类别，具体事实待研究。",
            "job": job,
            "model_available": available,
            "validation_trip": p.get("validation_trip", False),
            "activity_candidates": candidates,
            "references": refs,
            "research_job": research_job,
            "private_budget": private_budget,
            "research_available": research_available,
            "private_model_available": available and not p["demo"],
            "model_reason": None
            if available
            else "需要当前旅行已审核的活动依据、已配置服务和本批剩余额度；不会自动重试。",
            "provenance": {
                "preferences": "TEST_INPUT" if p["demo"] else "CURRENT_TRIP_USER_INPUT",
                "same_return": "PRODUCT_DEFAULT_MODIFIABLE",
                "plan": "AI_PROPOSED_OR_USER_DRAFT_NOT_SOURCE_ITINERARY",
                "long_term_memory": "NONE",
            },
            "feasibility": "UNVERIFIED",
        }

    def mutate(self, sid: str, action: PlanAction, key: str) -> dict[str, Any]:
        with self.db.transaction():
            row, state = self.load(sid)
            receipt = PreviewService(self.db, self.scope, row["mode"])
            payload = ["planning", sid, action.model_dump()]
            if receipt._receipt(key, payload):
                return self.get(sid)
            if row["revision"] != action.expected_revision:
                raise ValueError("STALE_REVISION")
            p = state["planning"]
            if action.action == "save":
                if action.draft is None:
                    raise ValueError("INVALID_INPUT")
                before = PlanDraft.model_validate(p["draft"])
                draft = action.draft
                view = PreviewService(self.db, self.scope, row["mode"]).get(sid)
                options = {o["option_id"]: o for o in view["options"]}
                allowed = {e["claim_id"] for o in view["options"] for e in o["evidence"]}
                if not p["demo"]:
                    from .materials import references

                    allowed = {e["claim_id"] for e in references(self.db, self.scope, sid)}
                if any(not set(a.evidence_ids) <= allowed for a in draft.activities):
                    raise ValueError("INVALID_INPUT")
                originals = {a.activity_id: a for a in before.activities}
                for a in draft.activities:
                    original = originals.get(a.activity_id)
                    if original is None or (a.name, a.region, a.evidence_ids, a.conditions) != (
                        original.name,
                        original.region,
                        original.evidence_ids,
                        original.conditions,
                    ):
                        a.provenance = "USER_INPUT"
                        a.evidence_ids = []
                        a.conditions = []
                        a.reference_kinds = []
                        a.description = "用户输入，来源支持待核实"
                    if original is None or (
                        a.stay_min,
                        a.stay_max,
                        a.rest_minutes,
                        a.locked_start,
                    ) != (
                        original.stay_min,
                        original.stay_max,
                        original.rest_minutes,
                        original.locked_start,
                    ):
                        a.timing_origin = "USER_CONFIRMED"
                if draft.inputs.activity_start != before.inputs.activity_start:
                    draft.anchor_origin = "USER_CONFIRMED"
                if draft.direction != before.direction:
                    p["collapsed"]["activities"] = False
                    if before.direction and p.get("direction_backup") is None:
                        p["direction_backup"] = {
                            "direction": before.direction,
                            "activities": deepcopy(p["draft"]["activities"]),
                        }
                    p["collapsed"]["direction"] = p.get("direction_backup") is None
                    if draft.direction in options:
                        o = options[draft.direction]
                        if not p["demo"]:
                            from .materials import activities

                            draft.activities = activities(o["evidence"], p["destination"])
                        else:
                            draft.activities = [
                                Activity(
                                    activity_id="source-" + fingerprint(e["claim_id"])[:20],
                                    name=e["text"][:120],
                                    evidence_ids=[e["claim_id"]],
                                    conditions=e["conditions"],
                                    provenance="SOURCE_REFERENCE",
                                )
                                for e in o["evidence"]
                                if e["claim_id"] in o["route_evidence_ids"]
                            ][:12]
                    elif draft.direction not in {None, "relaxed", "varied"}:
                        raise ValueError("OPTION_UNAVAILABLE")
                if len({a.activity_id.lower() for a in draft.activities}) != len(draft.activities):
                    raise ValueError("INVALID_INPUT")
                p["draft"] = draft.model_dump()
            elif action.action == "add_source":
                view = PreviewService(self.db, self.scope, row["mode"]).get(sid)
                option = next(
                    (o for o in view["options"] if o["option_id"] == action.option_id), None
                )
                if not option or view["stale"]:
                    raise ValueError("OPTION_UNAVAILABLE")
                present = {i for a in p["draft"]["activities"] for i in a["evidence_ids"]}
                if not p["demo"]:
                    from .materials import activities

                    added = [
                        a.model_dump()
                        for a in activities(option["evidence"], p["destination"])
                        if a.activity_id not in {a["activity_id"] for a in p["draft"]["activities"]}
                    ]
                else:
                    added = [
                        Activity(
                            activity_id="source-" + fingerprint(e["claim_id"])[:20],
                            name=e["text"][:120],
                            evidence_ids=[e["claim_id"]],
                            conditions=e["conditions"],
                            provenance="SOURCE_REFERENCE",
                        ).model_dump()
                        for e in option["evidence"]
                        if e["claim_id"] in option["route_evidence_ids"]
                        and e["claim_id"] not in present
                    ]
                if len(p["draft"]["activities"]) + len(added) > 12:
                    raise ValueError("INVALID_INPUT")
                p["draft"]["activities"].extend(added)
                p["collapsed"]["activities"] = False
            elif action.action == "use_activities":
                catalog = {a["activity_id"]: a for a in self.get(sid)["activity_candidates"]}
                if (
                    not action.activity_ids
                    or len(set(action.activity_ids)) != len(action.activity_ids)
                    or not set(action.activity_ids) <= catalog.keys()
                ):
                    raise ValueError("OPTION_UNAVAILABLE")
                p["draft"]["activities"] = [deepcopy(catalog[i]) for i in action.activity_ids]
                p["collapsed"]["activities"] = False
            elif action.action == "research":
                from travel_agent.preview.jobs import JobService
                from .private_budget import IDENTIFIER

                if not self.get(sid)["research_available"]:
                    raise ValueError("LIVE_RESEARCH_UNAVAILABLE")
                job = JobService(self.db, self.scope, row["mode"], IDENTIFIER).create(
                    sid, row["revision"], p["destination"], key + "-research", ready=True
                )
                p["research_job_id"] = job["job_id"]
            elif action.action == "adopt_research":
                from travel_agent.preview.jobs import JobService
                from .private_budget import IDENTIFIER

                research_service = JobService(self.db, self.scope, row["mode"], IDENTIFIER)
                if (
                    not p.get("research_job_id")
                    or not research_service.get(p["research_job_id"])["can_adopt"]
                ):
                    raise ValueError("NEW_MATERIAL_UNAVAILABLE")
                rid = self.db.connection.execute(
                    "SELECT research_id FROM preview_jobs WHERE job_id=?", (p["research_job_id"],)
                ).fetchone()[0]
                p["research_ids"] = sorted(set(p.get("research_ids", []) + [rid]))
                p["collapsed"]["activities"] = False
            elif action.action == "adopt":
                p["direction_backup"] = None
                p["adopted"] = deepcopy(p["draft"])
                p["collapsed"] = dict.fromkeys(["direction", "activities", "conditions"], True)
            elif action.action == "cancel":
                p["direction_backup"] = None
                if p["adopted"]:
                    p["draft"] = deepcopy(p["adopted"])
                p["collapsed"] = dict.fromkeys(["direction", "activities", "conditions"], True)
            elif action.action == "collapse":
                if action.section:
                    p["collapsed"][action.section] = action.collapsed
                    if action.section == "activities" and action.collapsed:
                        p["collapsed"]["conditions"] = False
            elif action.action in {"confirm_direction", "cancel_direction"}:
                if action.action == "cancel_direction" and p.get("direction_backup"):
                    p["draft"].update(p["direction_backup"])
                p["direction_backup"] = None
                p["collapsed"]["direction"] = True
            elif action.action == "suggest":
                from .suggestions import create_job

                p["job_id"] = create_job(self.db, self.scope, sid, row["revision"] + 1, p, key)
            elif action.action == "cancel_job":
                if p.get("research_job_id"):
                    from travel_agent.preview.jobs import JobService
                    from .private_budget import IDENTIFIER

                    JobService(self.db, self.scope, row["mode"], IDENTIFIER).cancel(
                        p["research_job_id"]
                    )
                if p["job_id"]:
                    self.db.connection.execute(
                        "UPDATE preview_jobs SET cancel_requested=1,status='CANCELED' WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                        (p["job_id"],),
                    )
            elif action.action == "use_proposal":
                from .suggestions import apply_proposal

                p["draft"] = apply_proposal(
                    self.db, self.scope, p, row["revision"], action.proposal_index
                )
                p["collapsed"]["activities"] = False
            self.db.connection.execute(
                "UPDATE preview_sessions SET state_json=?,revision=revision+?,updated_at=? WHERE session_id=?",
                (
                    json.dumps(state, ensure_ascii=False),
                    0 if action.action == "collapse" else 1,
                    self.db.stamp(),
                    sid,
                ),
            )
            receipt._remember(key, payload, sid)
            return self.get(sid)

    def index(self) -> dict[str, Any]:
        trips = []
        for r in self.db.connection.execute(
            "SELECT session_id,state_json FROM preview_sessions WHERE account_scope=? ORDER BY updated_at DESC,rowid DESC",
            (self.scope,),
        ):
            p = json.loads(r[1]).get("planning")
            if p:
                trips.append(
                    {"session_id": r[0], "destination": p["destination"], "demo": p["demo"]}
                )
        from .suggestions import model_used

        return {
            "trips": trips,
            "current": self.get(trips[0]["session_id"]) if trips else None,
            "model_used": model_used(self.db),
            "model_limit": 2,
        }
