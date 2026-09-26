"""Synthetic P03 API, storage, concurrency, and recovery. No real map/browser calls."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import shutil
import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from travel_agent.persistence.database import Database
from travel_agent.preview.service import PreviewService
from travel_agent.planning.budget import MapBudget
from travel_agent.planning.models import MapAction, TripInputs, PlaceInput, MapView
from travel_agent.planning.service import RoutePreviewService, seed_places
from travel_agent.providers.amap import AmapAdapter
from travel_agent.research.store import EvidenceStore
from test_cached_overview import seed


class Fake(AmapAdapter):
    def __init__(self):
        super().__init__(SecretStr("SYNTHETIC_ONLY"))
        self.calls = []

    def resolve_place(self, name, region):
        self.calls.append(("place", name))
        return {
            "status": "OK",
            "candidates": [
                {
                    "name": "MAP-EPHEMERAL-SENTINEL-入口",
                    "location": "121,31",
                    "type": "入口",
                    "address": "PRIVATE-MAP-ADDRESS-SENTINEL",
                    "pname": "合成省",
                    "cityname": "合成市",
                    "adname": "合成区",
                    "citycode": "021",
                    "adcode": "310000",
                    "coordinate_system": "GCJ02",
                }
            ],
        }

    def route(self, start, end, mode, at):
        self.calls.append(("route", mode))
        return {
            "status": "OK",
            "distance_meters": 1200.0,
            "duration_seconds": 600.0,
            "date_applicability": "GENERAL_REFERENCE_ONLY",
        }


@pytest.fixture
def setup(tmp_path, clock):
    path = tmp_path / "routes.sqlite3"
    with Database(path, clock=clock) as db:
        seed(db, clock)
        s = PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW")
        v = s.open("partial", "五天，不自驾", "p03-open-0001")
        option = v["options"][1]["option_id"]
        v = s.mutate(
            v["session_id"],
            dict(action="preview", option_id=option, expected_revision=v["revision"]),
            "p03-preview-1",
        )
        v = s.mutate(
            v["session_id"],
            dict(action="confirm", option_id=option, expected_revision=v["revision"]),
            "p03-confirm-1",
        )
        MapBudget(EvidenceStore(db)).initialize("owner", v["session_id"], option)
    s = RoutePreviewService(path, "owner", "CACHED_PRIVATE_PREVIEW", Fake())
    return s, v["session_id"]


def act(s, sid, action, **values):
    v = s.get(sid)
    return s.mutate(
        MapAction(
            action=action,
            session_id=sid,
            expected_revision=v["revision"],
            expected_preview_revision=v["preview_revision"],
            **values,
        ),
        str(uuid4()),
    )


def places(s, sid):
    inputs = TripInputs(
        places=[
            PlaceInput(place_id="a", name="合成入口甲"),
            PlaceInput(place_id="b", name="合成入口乙"),
        ]
    )
    act(s, sid, "save", inputs=inputs)
    for pid in ["a", "b"]:
        out = act(s, sid, "resolve", place_id=pid, send_confirmed=True)
        p = next(p for p in out["places"] if p["place_id"] == pid)
        assert p["status"] == "AWAITING_CONFIRMATION" and p["confirmed"] is None
        act(
            s,
            sid,
            "confirm_place",
            place_id=pid,
            candidate_id=p["candidates"][0]["candidate_id"],
            relation="SAME_OBJECT",
        )


def test_inheritance_get_local_inputs_adopt_cancel_and_recovery(setup):
    s, sid = setup
    v = s.get(sid)
    assert v["inherited"]["days"] == 5 and v["inherited"]["driving"] == "NO"
    assert v["inputs"]["charter"] == "UNKNOWN" and v["inputs"]["depart_at"] is None
    assert not s.adapter.calls
    data = TripInputs.model_validate(v["inputs"])
    data.charter = "COMPARE"
    act(s, sid, "save", inputs=data)
    out = act(s, sid, "adopt")
    original = deepcopy(out["adopted_inputs"])
    data.charter = "NO"
    assert act(s, sid, "save", inputs=data)["adopted_inputs"] == original
    out = act(s, sid, "cancel")
    assert out["inputs"] == original
    fresh = RoutePreviewService(s.database, s.scope, s.mode, Fake()).get(sid)
    assert fresh["inputs"] == original and fresh["evidence_count"] > 0
    assert fresh["map_result_state"] == "EXPIRED_OR_NOT_QUERIED"
    assert not s.adapter.calls
    MapView.model_validate(fresh)


def test_ephemeral_map_values_never_in_sqlite_stale_and_restart(setup):
    s, sid = setup
    places(s, sid)
    out = act(s, sid, "route", leg_id="a--b", send_confirmed=True)
    assert out["legs"][0]["duration_seconds"] == 600
    assert len(s.adapter.calls) == 3
    # New idempotency key still cannot duplicate the same external request.
    act(s, sid, "route", leg_id="a--b", send_confirmed=True)
    assert len(s.adapter.calls) == 3
    data = TripInputs.model_validate(out["inputs"])
    data.charter = "NO"
    stale = act(s, sid, "save", inputs=data)
    assert stale["legs"][0]["stale"] and stale["legs"][0]["duration_seconds"] == 600
    assert stale["time_check"]["known_movement_minutes"] == 0
    act(s, sid, "adopt")
    blob = s.database.read_bytes()
    for sentinel in [b"MAP-EPHEMERAL-SENTINEL", b"PRIVATE-MAP-ADDRESS-SENTINEL", b"121,31"]:
        assert sentinel not in blob
    fresh = RoutePreviewService(s.database, s.scope, s.mode, Fake()).get(sid)
    assert all(p["confirmed"] is None and not p["candidates"] for p in fresh["places"])
    assert fresh["legs"][0]["duration_seconds"] is None
    assert fresh["budget"]["used"] == {"map_place": 2, "map_route": 1}


def test_late_result_after_edit_is_discarded(setup):
    s, sid = setup
    places(s, sid)
    entered, release = threading.Event(), threading.Event()

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return {"status": "OK", "duration_seconds": 99, "distance_meters": 99}

    s.adapter.route = delayed
    with ThreadPoolExecutor(1) as pool:
        f = pool.submit(act, s, sid, "route", leg_id="a--b", send_confirmed=True)
        assert entered.wait(5)
        data = TripInputs.model_validate(s.get(sid)["inputs"])
        data.mode = "WALKING"
        act(s, sid, "save", inputs=data)
        release.set()
        out = f.result()
    assert out["last_action"] == "LATE_RESULT_DISCARDED"
    assert out["legs"][0]["duration_seconds"] is None
    assert out["budget"]["used"]["map_route"] == 1


def test_map_budget_independent_caps_atomic_and_copy_cannot_renew(setup, tmp_path):
    s, sid = setup
    option = s.get(sid)["interest"]
    with Database(s.database) as db:
        option = PreviewService(db, s.scope, s.mode).get(sid)["confirmed_option_id"]

    def reserve(i):
        with Database(s.database) as db:
            try:
                MapBudget(EvidenceStore(db)).reserve_map("MAP_PLACE", str(i), s.scope, sid, option)
                return True
            except ValueError:
                return False

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(reserve, range(14)))
    assert sum(results) == 8
    assert s.get(sid)["budget"]["remaining"] == {"map_place": 0, "map_route": 8}
    copied = tmp_path / "copied.sqlite3"
    shutil.copyfile(s.database, copied)
    with Database(copied) as db, pytest.raises(ValueError, match="WORKSPACE_MISMATCH"):
        MapBudget(EvidenceStore(db)).summary()
    with Database(s.database) as db, pytest.raises(ValueError, match="BINDING_CHANGED"):
        MapBudget(EvidenceStore(db)).initialize("owner", sid, option + "different")


def test_private_address_consent_and_no_driving_fallback(setup):
    s, sid = setup
    inputs = TripInputs(origin="USER-PRIVATE-SENTINEL", endpoints_private=True)
    act(s, sid, "save", inputs=inputs)
    with pytest.raises(ValueError, match="PRIVATE_ADDRESS"):
        act(s, sid, "resolve", place_id="origin", send_confirmed=True)
    assert not s.adapter.calls
    places(s, sid)
    data = TripInputs.model_validate(s.get(sid)["inputs"])
    data.mode = "DRIVING"
    act(s, sid, "save", inputs=data)
    # Mode changes preserve unchanged place objects, but require charter comparison.
    assert all(p["confirmed"] for p in s.get(sid)["places"])
    with pytest.raises(ValueError, match="CHARTER_UNDECIDED"):
        act(s, sid, "route", leg_id="a--b", send_confirmed=True)


def test_seed_never_stitches_days_and_regional_center_is_not_entrance():
    fragment = {"claim_id": "r", "text": "Day4：合成甲→合成乙"}
    option = {"evidence": [fragment], "route_evidence_ids": ["r"]}
    assert [p.name for p in seed_places(option)] == ["合成甲", "合成乙"]
    assert not seed_places(
        {"evidence": [fragment, fragment | {"claim_id": "s"}], "route_evidence_ids": ["r", "s"]}
    )


def test_edited_source_name_preserves_reference_but_becomes_user_input(setup, monkeypatch):
    s, sid = setup
    with Database(s.database) as db:
        original = PreviewService(db, s.scope, s.mode).get(sid)
    option = next(
        o for o in original["options"] if o["option_id"] == original["confirmed_option_id"]
    )
    claim_id = option["route_evidence_ids"][0]
    # Authored place projection only; the accepted Evidence and selection stay untouched.
    seeded = [
        PlaceInput(
            place_id="s0",
            name="合成源景区",
            evidence_ids=[claim_id],
            provenance="EVIDENCE_FRAGMENT",
        )
    ]
    monkeypatch.setattr("travel_agent.planning.service.seed_places", lambda _: deepcopy(seeded))
    data = TripInputs.model_validate(s.get(sid)["inputs"])
    data.places[0].name = "用户指定的入口"
    out = act(s, sid, "save", inputs=data)
    assert out["places"][0]["raw_name"] == "合成源景区"
    assert out["places"][0]["source"] == "USER_INPUT"
    assert out["places"][0]["evidence_ids"] == [claim_id]
    act(s, sid, "adopt")
    fresh = RoutePreviewService(s.database, s.scope, s.mode, Fake()).get(sid)
    assert fresh["places"][0]["name"] == "用户指定的入口"
    assert fresh["places"][0]["raw_name"] == "合成源景区"
    assert fresh["places"][0]["source"] == "USER_INPUT"
    with Database(s.database) as db:
        assert PreviewService(db, s.scope, s.mode).get(sid) == original
    assert not s.adapter.calls


def test_api_auth_csrf_no_key_and_read_no_operations(setup):
    s, sid = setup
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    from travel_agent.settings import Settings

    config = PreviewConfig(s.database, s.scope, s.mode, b"x" * 32, route_check=True)
    app = create_app(Settings.load(preferred_port=18768), preview=config)
    app.state.route_preview.adapter = AmapAdapter.from_env({})
    with TestClient(app, base_url="http://127.0.0.1:18768") as client:
        assert client.get("/api/v1/preview").status_code == 401
        client.get("/bootstrap?ticket=" + config.ticket)
        assert "ta_preview_18768" in client.cookies and "ta_preview" not in client.cookies
        index = client.get("/api/v1/preview").json()
        assert index["route_check_available"] and not index["workbench_available"]
        view = client.get("/api/v1/preview/routes/" + sid).json()
        MapView.model_validate(view)
        body = {
            "session_id": sid,
            "action": "save",
            "expected_revision": view["revision"],
            "expected_preview_revision": view["preview_revision"],
            "inputs": view["inputs"],
        }
        assert client.post("/api/v1/preview/routes", json=body).status_code == 403
        headers = {
            "Origin": "http://127.0.0.1:18768",
            "X-CSRF-Token": index["csrf_token"],
            "Idempotency-Key": "safe-map-request",
        }
        assert client.post("/api/v1/preview/routes", json=body, headers=headers).status_code == 200
        for _ in range(3):
            read = client.get("/api/v1/preview/routes/" + sid).json()
            assert read["budget"]["total_used"] == 0
        assert read["configuration_status"] == "AMAP_LIVE_BLOCKED_NOT_CONFIGURED"
    assert not s.adapter.calls


def test_ambiguous_area_and_entrance_are_not_interchangeable(setup):
    s, sid = setup
    data = TripInputs(places=[PlaceInput(place_id="a", name="合成景区", object_type="ENTRANCE")])
    act(s, sid, "save", inputs=data)
    original = s.adapter.resolve_place

    def multiple(*args):
        out = original(*args)
        out["candidates"].insert(0, out["candidates"][0] | {"name": "合成镇", "type": "行政地名"})
        return out

    s.adapter.resolve_place = multiple
    out = act(s, sid, "resolve", place_id="a", send_confirmed=True)
    assert (
        out["places"][0]["status"] == "MULTIPLE_CANDIDATES"
        and out["places"][0]["confirmed"] is None
    )
    first, second = out["places"][0]["candidates"]
    with pytest.raises(ValueError, match="OBJECT_TYPE_MISMATCH"):
        act(
            s,
            sid,
            "confirm_place",
            place_id="a",
            candidate_id=first["candidate_id"],
            relation="REGIONAL_REFERENCE",
        )
    out = act(
        s,
        sid,
        "confirm_place",
        place_id="a",
        candidate_id=second["candidate_id"],
        relation="ACCESS_POINT",
    )
    assert out["places"][0]["confirmed"]["object_type"] == "ENTRANCE"


def test_concurrent_identical_queries_reserve_once_and_restart_needs_new_explicit_action(setup):
    s, sid = setup
    act(s, sid, "save", inputs=TripInputs(places=[PlaceInput(place_id="a", name="合成入口")]))
    started, release = threading.Event(), threading.Event()
    original = s.adapter.resolve_place

    def delayed(*args):
        started.set()
        assert release.wait(5)
        return original(*args)

    s.adapter.resolve_place = delayed
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(act, s, sid, "resolve", place_id="a", send_confirmed=True)
        assert started.wait(5)
        second = pool.submit(act, s, sid, "resolve", place_id="a", send_confirmed=True)
        assert second.result()["last_action"] == "BUDGET_OR_DUPLICATE_DENIED"
        release.set()
        first.result()
    assert len(s.adapter.calls) == 1
    fresh = RoutePreviewService(s.database, s.scope, s.mode, Fake())
    assert fresh.get(sid)["budget"]["used"]["map_place"] == 1 and not fresh.adapter.calls
    act(fresh, sid, "resolve", place_id="a", send_confirmed=True)
    assert fresh.get(sid)["budget"]["used"]["map_place"] == 2 and len(fresh.adapter.calls) == 1


def test_actual_new_process_restores_nonempty_evidence_inputs_counts_not_map_results(
    setup, tmp_path
):
    import subprocess
    import sys
    from pathlib import Path
    import json

    s, sid = setup
    places(s, sid)
    act(s, sid, "route", leg_id="a--b", send_confirmed=True)
    act(s, sid, "adopt")
    root = Path(__file__).resolve().parents[2]
    code = """
import sys,json,socket
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def deny(*a,**k): raise AssertionError('OUTBOUND_FORBIDDEN')
socket.getaddrinfo=deny
socket.socket.connect=deny
from travel_agent.planning.service import RoutePreviewService
from travel_agent.providers.amap import AmapAdapter
s=RoutePreviewService(Path(sys.argv[1]),'owner','CACHED_PRIVATE_PREVIEW',AmapAdapter.from_env({}))
v=s.get(sys.argv[2])
assert v['evidence_count']>0 and v['inherited']['days']==5 and v['adopted_inputs']
assert v['budget']['used']=={'map_place':2,'map_route':1}
assert all(not p['candidates'] and p['confirmed'] is None for p in v['places'])
assert all(l['duration_seconds'] is None for l in v['legs'])
print(json.dumps({'status':'PASS','evidence':v['evidence_count'],'used':v['budget']['used'],'external':0}))
"""
    process = subprocess.run(
        [sys.executable, "-c", code, str(s.database), sid],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["status"] == "PASS"
