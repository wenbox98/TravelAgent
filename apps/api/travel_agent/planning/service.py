"""User-input persistence + process-only Amap projection. No source/model worker."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

from travel_agent.persistence.database import Database
from travel_agent.preview.service import PreviewService
from travel_agent.preview.projection import fingerprint
from travel_agent.providers.amap import AmapAdapter, route_parameters
from travel_agent.research.store import EvidenceStore
from .budget import MapBudget
from .models import MapAction, PlaceInput, TripInputs
from .time_check import check_time


def seed_places(option: dict[str, Any]) -> list[PlaceInput]:
    """Only current object's explicit arrow sequence; no model or cross-day stitching."""
    rows = [e for e in option["evidence"] if e["claim_id"] in option["route_evidence_ids"]]
    # Multiple day fragments need explicit user editing; never concatenate them.
    if len(rows) != 1:
        return []
    text = re.sub(
        r"^\s*(?:Day\s*\d+|D\s*\d+|第[一二三四五六七八九十\d]+天)\s*[：:]?\s*",
        "",
        rows[0]["text"],
        flags=re.I,
    )
    names = [s.strip() for s in re.split(r"\s*(?:→|->|—>|➡|➜)\s*", text)]
    if len(names) < 2 or len(names) > 12 or any(not s or len(s) > 80 for s in names):
        return []
    return [
        PlaceInput(
            place_id=f"s{i}",
            name=s,
            evidence_ids=[rows[0]["claim_id"]],
            provenance="EVIDENCE_FRAGMENT",
        )
        for i, s in enumerate(names)
    ]


def all_places(inputs: TripInputs) -> list[PlaceInput]:
    rows = list(inputs.places)
    if inputs.origin:
        rows.insert(
            0,
            PlaceInput(
                place_id="origin", name=inputs.origin, private_address=inputs.endpoints_private
            ),
        )
    if inputs.destination:
        rows.append(
            PlaceInput(
                place_id="return", name=inputs.destination, private_address=inputs.endpoints_private
            )
        )
    return rows


def place_kind(poi: dict[str, Any]) -> str:
    name, category = poi["name"], poi["type"]
    if "停车" in name or "停车" in category:
        return "PARKING"
    if any(s in name for s in ("入口", "大门", "出入口")):
        return "ENTRANCE"
    if "游客中心" in name:
        return "VISITOR_CENTER"
    if "站" in name or "交通设施" in category:
        return "STATION"
    if "行政地名" in category or re.search(r"[市县区镇乡]$", name):
        return "AREA"
    return "SCENIC" if "风景" in category or "景点" in category else "UNKNOWN"


class RoutePreviewService:
    def __init__(self, database: Path, scope: str, mode: Any, adapter: AmapAdapter):
        self.database, self.scope, self.mode, self.adapter = database, scope, mode, adapter
        self.lock = RLock()
        self.memory: dict[str, dict[str, Any]] = {}
        self.process_epoch = uuid4().hex

    def _context(self, db: Any, sid: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        preview = PreviewService(db, self.scope, self.mode).get(sid)
        option = next(
            (o for o in preview["options"] if o["option_id"] == preview["confirmed_option_id"]),
            None,
        )
        if option is None or preview["stale"] or preview["interest_needs_confirmation"]:
            raise ValueError("MAP_INTEREST_REQUIRED")
        MapBudget(EvidenceStore(db)).check_binding(self.scope, sid, option["option_id"])
        row = db.connection.execute(
            "SELECT * FROM route_preview_inputs WHERE session_id=? AND account_scope=?",
            (sid, self.scope),
        ).fetchone()
        if row:
            if row["option_id"] != option["option_id"]:
                raise ValueError("MAP_GRANT_BINDING_CHANGED")
            state = {
                "revision": row["revision"],
                "draft": json.loads(row["draft_json"]),
                "adopted": json.loads(row["adopted_json"]) if row["adopted_json"] else None,
            }
        else:
            state = {
                "revision": 0,
                "draft": TripInputs(places=seed_places(option)).model_dump(),
                "adopted": None,
            }
        return preview, option, state

    def _view(self, db: Any, sid: str) -> dict[str, Any]:
        preview, option, state = self._context(db, sid)
        inputs = TripInputs.model_validate(state["draft"])
        mem = self.memory.get(sid, {})
        live = (
            mem.get("revision") == state["revision"]
            and mem.get("preview_revision") == preview["revision"]
        )
        places = []
        original_names = {p.place_id: p.name for p in seed_places(option)}
        for p in all_places(inputs):
            temp = mem.get("places", {}).get(p.place_id, {}) if live else {}
            confirmed = temp.get("confirmed")
            places.append(
                p.model_dump()
                | {
                    "raw_name": original_names.get(p.place_id, p.name),
                    "status": "CONFIRMED" if confirmed else temp.get("status", "UNRESOLVED"),
                    "candidates": temp.get("candidates", []),
                    "confirmed": confirmed,
                    "source": "USER_INPUT"
                    if p.provenance == "USER_INPUT"
                    else "REVIEWED_SOURCE_FRAGMENT",
                }
            )
        legs = []
        for start, end in zip(places, places[1:]):
            lid = start["place_id"] + "--" + end["place_id"]
            old = mem.get("legs", {}).get(lid)
            result = old or {}
            stale = bool(old and (not live or old.get("status") == "STALE"))
            legs.append(
                {
                    "leg_id": lid,
                    "from_id": start["place_id"],
                    "to_id": end["place_id"],
                    "from_name": start["name"],
                    "to_name": end["name"],
                    "mode": result.get("mode", inputs.mode),
                    "endpoint_confidence": "USER_CONFIRMED_MAP_OBJECTS"
                    if start["confirmed"] and end["confirmed"]
                    else "UNCONFIRMED",
                    "kind": "OUTBOUND"
                    if start["place_id"] == "origin"
                    else "RETURN"
                    if end["place_id"] == "return"
                    else "BETWEEN_SOURCE_PLACES",
                    "status": "STALE" if stale else result.get("status", "NOT_QUERIED"),
                    "stale": stale,
                    "duration_seconds": result.get("duration_seconds"),
                    "distance_meters": result.get("distance_meters"),
                    "queried_at": result.get("queried_at"),
                    "date_applicability": result.get(
                        "date_applicability", "TIME_WINDOW_UNCONFIRMED"
                    ),
                    "requested_depart_at": result.get("requested_depart_at"),
                    "availability": "UNKNOWN",
                    "basis": "高德地图 · 临时估算" if result else "尚未查询",
                    "gaps": ["班次、运营、车辆与可订性未核实", "入口及末端接驳仍需核实"]
                    + (
                        ["驾车仅为道路时间；不是公共交通，包车意愿不代表车辆落实"]
                        if result.get("mode", inputs.mode) == "DRIVING"
                        else ["步行参考不证明高山徒步安全或景区开放"]
                        if result.get("mode", inputs.mode) == "WALKING"
                        else ["本次无方案不代表现实无交通；方案总耗时含等车，不再叠加"]
                    ),
                    "result_endpoint_names": result.get("endpoint_names", []),
                    "error_code": result.get("error_code"),
                }
            )
        # A source day fragment cannot become a five-day itinerary, regardless of map success.
        scope = (
            "LOCAL_DAY_SEGMENT"
            if option["source_schedule"]["day_count"] is None
            or len(option["source_schedule"]["entries"]) <= 1
            else "WHOLE_SELECTED_OBJECT"
        )
        budget = MapBudget(EvidenceStore(db)).summary()
        return {
            "session_id": sid,
            "revision": state["revision"],
            "preview_revision": preview["revision"],
            "interest": option["label"],
            "evidence_count": preview["evidence_count"],
            "inherited": preview["preferences"],
            "source_schedule": option["source_schedule"],
            "source_route_fragments": [
                e["text"]
                for e in option["evidence"]
                if e["claim_id"] in option["route_evidence_ids"]
            ],
            "source_reference_kinds": option["reference_kinds"],
            "inputs": state["draft"],
            "adopted_inputs": state["adopted"],
            "has_changes": state["draft"] != state["adopted"],
            "places": places,
            "legs": legs,
            "time_check": check_time(inputs, legs, checked_scope=scope),
            "configured": self.adapter.configured,
            "configuration_status": "CONFIGURED_NOT_VERIFIED"
            if self.adapter.configured
            else "AMAP_LIVE_BLOCKED_NOT_CONFIGURED",
            "budget": budget,
            "map_storage": "EPHEMERAL_MEMORY_ONLY",
            "map_result_state": "STALE"
            if mem and (not live or mem.get("inputs_changed"))
            else "CURRENT_PROCESS"
            if mem
            else "EXPIRED_OR_NOT_QUERIED",
            "message": "地图内容仅本次进程可用，刷新可读取，重启后需显式重新核实。用户输入、原资料和额度保留。",
            "last_action": mem.get("last_action"),
            "business_calls": {
                "xhs_connect": 0,
                "xhs_search": 0,
                "xhs_detail": 0,
                "xhs_browser": 0,
                "model": 0,
            },
        }

    def get(self, sid: str) -> dict[str, Any]:
        with self.lock, Database(self.database) as db:
            return self._view(db, sid)

    def mutate(self, action: MapAction, key: str) -> dict[str, Any]:
        sid = action.session_id
        payload = ["p03", action.model_dump()]
        with self.lock, Database(self.database) as db, db.transaction():
            preview, option, state = self._context(db, sid)
            receipts = PreviewService(db, self.scope, self.mode)
            if receipts._receipt(key, payload):
                return self._view(db, sid)
            if (
                action.expected_revision != state["revision"]
                or action.expected_preview_revision != preview["revision"]
            ):
                raise ValueError("STALE_REVISION")
            inputs = TripInputs.model_validate(state["draft"])
            mem = self.memory.get(sid)
            if (
                mem is None
                or mem.get("revision") != state["revision"]
                or mem.get("preview_revision") != preview["revision"]
            ):
                mem = {
                    "places": {},
                    "legs": deepcopy(mem.get("legs", {})) if mem else {},
                    "revision": state["revision"],
                    "preview_revision": preview["revision"],
                    "generation": uuid4().hex,
                }
                # Old legs are only retained for a STALE display, never used in new totals.
                for leg in mem["legs"].values():
                    leg["status"] = "STALE"
                self.memory[sid] = mem
            if action.action in {"save", "cancel", "adopt"}:
                if action.action == "save":
                    if action.inputs is None:
                        raise ValueError("INVALID_INPUT")
                    ids = set(option["route_evidence_ids"])
                    original_places = {p.place_id: p for p in seed_places(option)}
                    for input_place in action.inputs.places:
                        if not set(input_place.evidence_ids) <= ids or (
                            input_place.provenance == "EVIDENCE_FRAGMENT"
                            and not input_place.evidence_ids
                        ):
                            raise ValueError("INVALID_INPUT")
                        original_place = original_places.get(input_place.place_id)
                        if (
                            original_place is None
                            or input_place.name != original_place.name
                            or input_place.evidence_ids != original_place.evidence_ids
                        ):
                            input_place.provenance = "USER_INPUT"
                    state["draft"] = action.inputs.model_dump()
                elif action.action == "cancel":
                    state["draft"] = (
                        deepcopy(state["adopted"])
                        if state["adopted"]
                        else TripInputs(places=seed_places(option)).model_dump()
                    )
                else:
                    state["adopted"] = deepcopy(state["draft"])
                # Adoption changes no calculation input, and may retain current memory results.
                state["revision"] += 1
                if action.action == "adopt":
                    mem["revision"] = state["revision"]
                else:
                    mem["generation"] = uuid4().hex
                    mem["inputs_changed"] = bool(mem["legs"])
                    mem["revision"] = state["revision"]
                    current_places = {
                        p.place_id: fingerprint(p.model_dump())
                        for p in all_places(TripInputs.model_validate(state["draft"]))
                    }
                    mem["places"] = {
                        k: v
                        for k, v in mem["places"].items()
                        if v.get("input_hash") == current_places.get(k)
                    }
                    for old_leg in mem["legs"].values():
                        old_leg["status"] = "STALE"
                db.connection.execute(
                    "INSERT INTO route_preview_inputs VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,draft_json=excluded.draft_json,adopted_json=excluded.adopted_json,updated_at=excluded.updated_at",
                    (
                        sid,
                        self.scope,
                        option["option_id"],
                        state["revision"],
                        json.dumps(state["draft"], ensure_ascii=False),
                        json.dumps(state["adopted"], ensure_ascii=False)
                        if state["adopted"]
                        else None,
                        db.stamp(),
                    ),
                )
                receipts._remember(key, payload, sid)
                return self._view(db, sid)
            place = next((p for p in all_places(inputs) if p.place_id == action.place_id), None)
            if action.action == "confirm_place":
                temp = mem["places"].get(action.place_id, {})
                candidate = next(
                    (
                        c
                        for c in temp.get("candidates", [])
                        if c["candidate_id"] == action.candidate_id
                    ),
                    None,
                )
                if place is None or candidate is None or not action.relation:
                    raise ValueError("MAP_CANDIDATE_UNAVAILABLE")
                kind = candidate["object_type"]
                if (
                    place.object_type in {"ENTRANCE", "PARKING", "STATION", "VISITOR_CENTER"}
                    and kind != place.object_type
                ):
                    raise ValueError("MAP_OBJECT_TYPE_MISMATCH")
                if kind == "AREA" and action.relation != "REGIONAL_REFERENCE":
                    raise ValueError("MAP_REGIONAL_REFERENCE_REQUIRED")
                temp["confirmed"] = deepcopy(candidate) | {"relation": action.relation}
                mem["generation"] = uuid4().hex
                # A changed map object invalidates previous route calculations, without persisting it.
                for leg in mem["legs"].values():
                    leg["status"] = "STALE"
                state["revision"] += 1
                mem["revision"] = state["revision"]
                db.connection.execute(
                    "INSERT INTO route_preview_inputs VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at",
                    (
                        sid,
                        self.scope,
                        option["option_id"],
                        state["revision"],
                        json.dumps(state["draft"], ensure_ascii=False),
                        json.dumps(state["adopted"], ensure_ascii=False)
                        if state["adopted"]
                        else None,
                        db.stamp(),
                    ),
                )
                receipts._remember(key, payload, sid)
                return self._view(db, sid)
            if not action.send_confirmed:
                raise ValueError("MAP_SEND_CONFIRMATION_REQUIRED")
            if not self.adapter.configured:
                mem["last_action"] = "NOT_CONFIGURED"
                return self._view(db, sid)
            if action.action == "resolve":
                if place is None or place.private_address and not action.private_send_confirmed:
                    raise ValueError("MAP_PRIVATE_ADDRESS_CONFIRMATION_REQUIRED")
                kind = "MAP_PLACE"
                arguments: Any = (place.name, place.region)
                dispatch: list[Any] = ["place", place.name, place.region]
            else:
                rows = all_places(inputs)
                pair = next(
                    (
                        (a, b)
                        for a, b in zip(rows, rows[1:])
                        if a.place_id + "--" + b.place_id == action.leg_id
                    ),
                    None,
                )
                if pair is None:
                    raise ValueError("INVALID_INPUT")
                start, end = [mem["places"].get(p.place_id, {}).get("confirmed") for p in pair]
                if not start or not end:
                    raise ValueError("MAP_CONFIRM_PLACES_FIRST")
                if any(p.private_address for p in pair) and not action.private_send_confirmed:
                    raise ValueError("MAP_PRIVATE_ADDRESS_CONFIRMATION_REQUIRED")
                if (
                    inputs.mode == "DRIVING"
                    and preview["preferences"]["driving"] == "NO"
                    and inputs.charter != "COMPARE"
                ):
                    raise ValueError("MAP_CHARTER_UNDECIDED")
                # Validate before reservation. Departure is the explicit LEG time, not trip start.
                params = route_parameters(start, end, inputs.mode, action.leg_depart_at)
                kind, arguments = (
                    "MAP_ROUTE",
                    (deepcopy(start), deepcopy(end), inputs.mode, action.leg_depart_at),
                )
                dispatch = ["route", inputs.mode, params]
            try:
                MapBudget(EvidenceStore(db)).reserve_map(
                    kind,
                    fingerprint([self.process_epoch, dispatch]),
                    self.scope,
                    sid,
                    option["option_id"],
                )
            except ValueError as exc:
                if str(exc) != "BOUNDED_BUDGET_OR_DUPLICATE_DENIED":
                    raise
                mem["last_action"] = "BUDGET_OR_DUPLICATE_DENIED"
                return self._view(db, sid)
            receipts._remember(key, payload, sid)
            generation = mem["generation"]
            captured = (state["revision"], preview["revision"], generation)
            mem["last_action"] = "RUNNING"
        # Release SQLite/lock during I/O so edits can invalidate late results.
        try:
            result = (
                self.adapter.resolve_place(*arguments)
                if kind == "MAP_PLACE"
                else self.adapter.route(*arguments)
            )
        except Exception:
            result = {"status": "UPSTREAM_ERROR", "error_code": "SAFE_PROVIDER_FAILURE"}
        with self.lock, Database(self.database) as db:
            current_preview, _, current_state = self._context(db, sid)
            mem = self.memory[sid]
            if captured != (
                current_state["revision"],
                current_preview["revision"],
                mem["generation"],
            ):
                mem["last_action"] = "LATE_RESULT_DISCARDED"
                return self._view(db, sid)
            if kind == "MAP_PLACE":
                candidates = []
                for c in result.get("candidates", []):
                    uri = "https://uri.amap.com/marker?" + urlencode(
                        {
                            "position": c["location"],
                            "name": c["name"],
                            "src": "TravelAgent",
                            "coordinate": "gaode",
                            "callnative": "0",
                        }
                    )
                    candidates.append(
                        c | {"candidate_id": uuid4().hex, "object_type": place_kind(c), "uri": uri}
                    )
                mem["places"][action.place_id] = {
                    "status": "MULTIPLE_CANDIDATES"
                    if len(candidates) > 1
                    else "AWAITING_CONFIRMATION"
                    if candidates
                    else result["status"],
                    "candidates": candidates,
                    "input_hash": fingerprint(place.model_dump()) if place else "",
                }
            else:
                mem["legs"][action.leg_id] = result | {
                    "mode": inputs.mode,
                    "queried_at": datetime.now(timezone.utc).isoformat(),
                    "requested_depart_at": action.leg_depart_at,
                    "endpoint_names": [arguments[0]["name"], arguments[1]["name"]],
                }
                mem["inputs_changed"] = any(
                    leg.get("status") == "STALE" for leg in mem["legs"].values()
                )
            mem["last_action"] = result["status"]
            return self._view(db, sid)
