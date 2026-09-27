"""Reuse map identity/leg lifecycle in synthetic mode; private P04 maps disabled."""

from typing import Any
from pydantic import SecretStr
from travel_agent.preview.projection import fingerprint
from travel_agent.providers.amap import AmapAdapter
from .flow import PlanningService
from .flow_models import PlanDraft
from .models import MapAction, PlaceInput
from .service import RoutePreviewService, all_places


class SyntheticMapAdapter(AmapAdapter):
    """Authored map fixture. Never installed by the real Amap entry point."""

    def __init__(self) -> None:
        super().__init__(SecretStr("SYNTHETIC_LOCAL_ONLY"))

    def resolve_place(self, name: str, region: str = "") -> dict[str, Any]:
        seed = int(fingerprint([name, region])[:4], 16) % 9000
        return {
            "status": "OK",
            "candidates": [
                {
                    "name": name,
                    "location": f"120.{seed + i:04d},31.{i + 1}",
                    "type": "合成风景名胜",
                    "address": "虚构测试位置",
                    "pname": "虚构省",
                    "cityname": region if i < 2 else "另一虚构地区",
                    "adname": f"虚构分区{i + 1}",
                    "citycode": "0512",
                    "adcode": "320500",
                    "coordinate_system": "GCJ02",
                }
                for i in range(4)
            ],
        }

    def route(
        self, start: dict[str, Any], end: dict[str, Any], mode: str, at: str | None = None
    ) -> dict[str, Any]:
        if mode == "TRANSIT":
            return {"status": "NO_ROUTE_RETURNED", "date_applicability": "GENERAL_REFERENCE_ONLY"}
        return {
            "status": "OK",
            "duration_seconds": 600.0 if start["location"] < end["location"] else 900.0,
            "distance_meters": 1000.0,
            "date_applicability": "GENERAL_REFERENCE_ONLY",
        }


class FlowMapService(RoutePreviewService):
    def _context(self, db: Any, sid: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        row, saved = PlanningService(db, self.scope).load(sid)
        p = saved["planning"]
        draft = PlanDraft.model_validate(p["draft"])
        inputs = draft.inputs.model_copy(deep=True)
        inputs.places = [
            PlaceInput(
                place_id=a.activity_id.lower(),
                name=a.name[:80],
                region=a.region,
                evidence_ids=a.evidence_ids,
                provenance="EVIDENCE_FRAGMENT" if a.evidence_ids else "USER_INPUT",
            )
            for a in draft.activities
        ]
        previous = db.connection.execute(
            "SELECT * FROM route_preview_inputs WHERE session_id=? AND account_scope=?",
            (sid, self.scope),
        ).fetchone()
        state = {
            "revision": previous["revision"] if previous else 0,
            "draft": inputs.model_dump(),
            "adopted": None,
        }
        preview = {
            "revision": row["revision"],
            "evidence_count": 0,
            "preferences": {
                "days": draft.days,
                "driving": draft.driving,
                "budget_cny_fen": None,
                "traveler_count": None,
                "time_hint": None,
                "travel_date": None,
                "charter": "UNKNOWN",
                "answered": [],
            },
        }
        option = {
            "option_id": "planning-" + sid,
            "label": p["destination"],
            "evidence": [],
            "route_evidence_ids": [],
            "source_schedule": {
                "entries": [],
                "day_count": None,
                "basis": "INCOMPLETE_OR_AMBIGUOUS",
                "meaning": "用户/系统活动安排，不是来源路线",
            },
            "reference_kinds": [],
        }
        mem = self.memory.get(sid)
        dates = (inputs.depart_at, inputs.return_by)
        if mem and mem.get("preview_revision") != row["revision"]:
            hashes = {a.place_id: fingerprint(a.model_dump()) for a in all_places(inputs)}
            old = mem.get("input_hashes", {})
            mem["places"] = {
                k: v for k, v in mem["places"].items() if v.get("input_hash") == hashes.get(k)
            }
            for lid, leg in mem["legs"].items():
                if (
                    leg.get("mode") != inputs.mode
                    or mem.get("query_dates") != dates
                    or any(hashes.get(k) != old.get(k) for k in lid.split("--"))
                ):
                    leg["status"] = "STALE"
            mem["input_hashes"] = hashes
            mem["preview_revision"] = row["revision"]
            mem["generation"] = fingerprint([row["revision"], state["revision"]])
        if mem is not None:
            mem["query_dates"] = dates
        return preview, option, state

    def _quota(self, db: Any) -> dict[str, Any]:
        # No map authorization is granted/transferred in P04. Local fixtures do
        # not consume or pretend to be real Amap operations.
        return {
            "used": {"map_place": 0, "map_route": 0},
            "remaining": {"map_place": 0, "map_route": 0},
            "total_used": 0,
            "total_limit": 16,
        }

    def _reserve(self, db: Any, kind: str, payload: str, sid: str, option: str) -> None:
        _, state = PlanningService(db, self.scope).load(sid)
        if not state["planning"]["demo"]:
            raise ValueError("P04_MAP_DISABLED")
        mem = self.memory[sid]
        dispatched = mem.setdefault("synthetic_dispatches", set())
        if payload in dispatched:
            raise ValueError("BOUNDED_BUDGET_OR_DUPLICATE_DENIED")
        dispatched.add(payload)

    def _view(self, db: Any, sid: str) -> dict[str, Any]:
        view = super()._view(db, sid)
        _, state = PlanningService(db, self.scope).load(sid)
        demo = bool(state["planning"]["demo"])
        view["configured"] = demo
        view["configuration_status"] = (
            "CONFIGURED_NOT_VERIFIED" if demo else "AMAP_LIVE_BLOCKED_NOT_CONFIGURED"
        )
        view["message"] = (
            "合成地图交互测试：候选和耗时均为自编，非高德实测。"
            if demo
            else "本批地图请求关闭；原地图剩余额度保留，未转移给新旅行。"
        )
        for leg in view["legs"]:
            leg["basis"] = (
                "自编合成测试返回，非真实路程" if leg["status"] != "NOT_QUERIED" else "尚未核实"
            )
        return view

    def mutate(self, action: MapAction, key: str) -> dict[str, Any]:
        if action.action not in {"resolve", "confirm_place", "route"}:
            raise ValueError("INVALID_INPUT")
        from travel_agent.persistence.database import Database

        with Database(self.database) as db:
            _, state = PlanningService(db, self.scope).load(action.session_id)
            if not state["planning"]["demo"]:
                raise ValueError("P04_MAP_DISABLED")
        view = super().mutate(action, key)
        self.memory[action.session_id]["input_hashes"] = {
            p.place_id: fingerprint(p.model_dump())
            for p in all_places(PlanDraft.model_validate(state["planning"]["draft"]).inputs)
        }
        # Include activity places, which are derived from current draft IDs.
        with Database(self.database) as db:
            _, _, current = self._context(db, action.session_id)
            from .models import TripInputs

            self.memory[action.session_id]["input_hashes"] = {
                p.place_id: fingerprint(p.model_dump())
                for p in all_places(TripInputs.model_validate(current["draft"]))
            }
        return view


class PrivateFlowMapService(FlowMapService):
    """The same place/leg lifecycle, with real adapter and this trip's grant."""

    def _quota(self, db: Any, sid: str = "") -> dict[str, Any]:
        from .private_budget import PrivatePlanningBudget

        try:
            summary = PrivatePlanningBudget.for_trip(db, sid).summary()
            used = {k: summary["used"][k] for k in ("map_place", "map_route")}
            left = {k: summary["remaining"][k] for k in used}
        except ValueError:
            used = dict(map_place=0, map_route=0)
            left = dict(used)
        return {
            "used": used,
            "remaining": left,
            "total_used": sum(used.values()),
            "total_limit": sum(used.values()) + sum(left.values()) or 8,
        }

    def _reserve(self, db: Any, kind: str, payload: str, sid: str, option: str) -> None:
        from .private_budget import PrivatePlanningBudget

        PrivatePlanningBudget.for_trip(db, sid).reserve_for_trip(self.scope, sid, kind, payload)

    def _view(self, db: Any, sid: str) -> dict[str, Any]:
        from .private_budget import PrivatePlanningBudget

        view = RoutePreviewService._view(self, db, sid)
        try:
            PrivatePlanningBudget.for_trip(db, sid).check_trip(self.scope, sid)
            authorized = True
        except ValueError:
            authorized = False
        view["budget"] = self._quota(db, sid)
        view["configured"] = self.adapter.configured and authorized
        view["configuration_status"] = (
            "CONFIGURED_NOT_VERIFIED" if view["configured"] else "AMAP_LIVE_BLOCKED_NOT_CONFIGURED"
        )
        if not authorized:
            view["message"] = "本次旅行尚无可用查询许可；历史额度保留。"
        return view

    def mutate(self, action: MapAction, key: str) -> dict[str, Any]:
        from travel_agent.persistence.database import Database
        from .private_budget import PrivatePlanningBudget
        from .materials import references, candidate_from_name

        if isinstance(self.adapter, SyntheticMapAdapter) or action.action not in {
            "resolve",
            "confirm_place",
            "route",
        }:
            raise ValueError("INVALID_INPUT")
        with Database(self.database) as db:
            PrivatePlanningBudget.for_trip(db, action.session_id).check_trip(
                self.scope, action.session_id
            )
            _, state = PlanningService(db, self.scope).load(action.session_id)
            p = state["planning"]
            draft = PlanDraft.model_validate(p["draft"])
            if draft.inputs.origin or draft.inputs.destination or draft.inputs.endpoints_private:
                raise ValueError("PRIVATE_ENDPOINT_NOT_AUTHORIZED")
            refs = {e["claim_id"]: e for e in references(db, self.scope, action.session_id)}
            for a in draft.activities:
                if a.provenance != "SOURCE_REFERENCE" or not set(a.evidence_ids) <= refs.keys():
                    raise ValueError("ACTIVITY_SUPPORT_REQUIRED")
                supported = candidate_from_name(
                    a.name,
                    [refs[i] for i in a.evidence_ids],
                    p["destination"],
                    draft.spatial.intent,
                )
                if (
                    action.action == "route"
                    and p.get("protocol_version") == 2
                    and draft.spatial.intent == "CITY_CORE"
                    and supported.spatial_status != "MATCH"
                ):
                    raise ValueError("MAP_SCOPE_UNVERIFIED")
                if a.region != p["destination"]:
                    raise ValueError("ACTIVITY_SUPPORT_REQUIRED")
            if action.action == "route":
                adopted = PlanDraft.model_validate(p["adopted"]) if p["adopted"] else None
                if not adopted or [(a.activity_id, a.day) for a in adopted.activities] != [
                    (a.activity_id, a.day) for a in draft.activities
                ]:
                    raise ValueError("MAP_ADOPT_ORDER_FIRST")
                allowed = (
                    {"TRANSIT"}
                    if draft.transport == "PUBLIC_TRANSIT"
                    else {"WALKING"}
                    if draft.transport == "WALKING"
                    else {"DRIVING"}
                    if draft.transport == "SELF_DRIVE" and draft.driving != "NO"
                    else set()
                )
                if draft.walking_allowed:
                    allowed.add("WALKING")
                if draft.inputs.mode not in allowed:
                    raise ValueError("MAP_MODE_REQUIRED")
        result = RoutePreviewService.mutate(self, action, key)
        with self.lock, Database(self.database) as db:
            _, _, current = self._context(db, action.session_id)
            from .models import TripInputs

            if action.session_id in self.memory:
                self.memory[action.session_id]["input_hashes"] = {
                    a.place_id: fingerprint(a.model_dump())
                    for a in all_places(TripInputs.model_validate(current["draft"]))
                }
        return result
