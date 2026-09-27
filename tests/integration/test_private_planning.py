"""Authored private-path fixtures, never real sources or external transports."""

from copy import deepcopy
from hashlib import sha256
import json
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import SecretStr

from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService, timeline
from travel_agent.planning.flow_models import PlanAction, PlanDraft
from travel_agent.planning.flow_maps import PrivateFlowMapService
from travel_agent.planning.models import MapAction, MapView
from travel_agent.planning.private_budget import IDENTIFIER, LIMITS, PrivatePlanningBudget
from travel_agent.planning.suggestions import payload_for, run_worker, validate_response
from travel_agent.planning.private_payload import ground
from travel_agent.preview.jobs import JobService
from travel_agent.providers.amap import AmapAdapter
from test_cached_overview import seed
from test_planning_flow import act, create, response


@pytest.fixture
def private(tmp_path, clock, monkeypatch):
    with Database(tmp_path / "private.sqlite3", clock=clock) as db:
        seed(db, clock)
        db.connection.execute(
            "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
            (
                IDENTIFIER,
                "owner",
                "AUTHORED_FIXTURE",
                json.dumps({"workspace": sha256(str(db.path.resolve()).encode()).hexdigest()}),
                db.stamp(),
                db.stamp(),
                json.dumps(LIMITS),
                json.dumps({"status": "PASS", "destination": "合成青谷", "session_id": None}),
            ),
        )
        monkeypatch.setattr(
            "travel_agent.planning.suggestions.configured_provider", lambda: object()
        )
        monkeypatch.setattr("travel_agent.preview.worker.configured_provider", lambda: object())
        monkeypatch.setattr(
            "travel_agent.research.bounded.BoundedBudget.check_provider", lambda *_: None
        )
        yield PlanningService(db, "owner")


def chosen(s):
    v = create(s, "合成青谷", request="一天，公共交通和步行，上午10点开始第一个项目")
    assert v["demo"] is None and len(v["activity_candidates"]) >= 2
    return act(
        s,
        v,
        "use_activities",
        activity_ids=[a["activity_id"] for a in v["activity_candidates"][:2]],
    )


def test_private_payload_reviewed_source_not_map_private_address_or_synthetic(private):
    v = chosen(private)
    draft = PlanDraft.model_validate(v["draft"])
    draft.inputs.origin = "PRIVATE_HOME_SENTINEL"
    v = act(private, v, "save", draft=draft)
    _, state = private.load(v["session_id"])
    data = payload_for(state["planning"], private.db, "owner", v["session_id"])
    assert data["purpose"] == "PRIVATE_PLANNING" and data["references"]
    assert data["first_start"] == "10:00" and data["walking_allowed"]
    assert "PRIVATE_HOME_SENTINEL" not in json.dumps(data) and data["known_map_values"] == []
    assert all(len(a["name"]) < 30 and "Day" not in a["name"] for a in data["activities"])
    assert all(a["conditions"] for a in data["activities"])
    state["planning"]["draft"]["activities"][0]["provenance"] = "SYNTHETIC_TEST"
    with pytest.raises(ValueError, match="REFERENCE_UNAVAILABLE"):
        payload_for(state["planning"], private.db, "owner", v["session_id"])
    assert not create(private, "另一合成城")["activity_candidates"]
    with pytest.raises(ValueError, match="SESSION_UNAVAILABLE"):
        PlanningService(private.db, "another").get(v["session_id"])


def test_private_adoption_second_version_cancel_restart_no_dispatch(private, monkeypatch):
    v = chosen(private)
    sid = v["session_id"]
    v = act(private, v, "suggest")

    class Fake:
        calls = 0

        def structured(self, task, data, schema):
            self.calls += 1
            return response(data)

    provider = Fake()
    run_worker(private.db.path, v["job"]["job_id"], provider)
    v = act(private, private.get(sid), "use_proposal")
    v = act(private, v, "adopt")
    original = deepcopy(v["adopted"])
    d = PlanDraft.model_validate(v["draft"])
    d.adjustment = "LONGER_FIRST"
    v = act(private, v, "save", draft=d)
    v = act(private, v, "suggest")
    run_worker(private.db.path, v["job"]["job_id"], provider)
    v = act(private, private.get(sid), "use_proposal")
    assert v["adopted"] == original
    v = act(private, v, "cancel")
    assert v["draft"] == original and provider.calls == 2
    assert all(a["timing_origin"] == "AI_PROPOSED" for a in v["adopted"]["activities"])
    assert not private.get(sid)["model_available"]
    assert not create(private, "合成青谷")["model_available"]
    code = """
import sys,socket
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def deny(*a,**kw): raise AssertionError('NETWORK')
socket.getaddrinfo=deny;socket.socket.connect=deny
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 assert len(v['adopted']['activities'])==2 and v['references']
 assert v['draft']['inputs']['activity_start']=='10:00'
 assert v['private_budget']['used']['model']==2
 print('NONEMPTY_LOCAL_RECOVERY')
"""
    r = subprocess.run(
        [sys.executable, "-c", code, str(private.db.path), sid],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "NONEMPTY_LOCAL_RECOVERY" in r.stdout


def test_research_cache_miss_queue_idempotent_cancel_preserves_inputs(private):
    # Authored scenario with no compatible source, same durable grant.
    private.db.connection.execute(
        "UPDATE research_questions SET request_json=?", ('{"destination":"无关区域"}',)
    )
    v = create(private, "合成青谷", request="一天，公共交通和步行，上午10点开始")
    assert v["research_available"] and not v["activity_candidates"]
    command = PlanAction(action="research", expected_revision=v["revision"])
    key = str(uuid4())
    v = private.mutate(v["session_id"], command, key)
    again = private.mutate(v["session_id"], command, key)
    assert again["research_job"] == v["research_job"]
    jobs = private.db.connection.execute(
        "SELECT request_json FROM preview_jobs WHERE continuation_id=?", (IDENTIFIER,)
    ).fetchall()
    assert len(jobs) == 1
    req = json.loads(jobs[0][0])
    assert req["request"]["days"] == 1 and "公共交通" in req["focus"] and "步行" in req["focus"]
    assert PrivatePlanningBudget(private.db).summary()["used"] == dict.fromkeys(
        (k.lower() for k in LIMITS), 0
    )
    v = act(private, v, "cancel_job")
    assert (
        v["research_job"]["status"] == "CANCELED"
        and v["draft"]["inputs"]["activity_start"] == "10:00"
    )
    JobService(private.db, "owner", "CACHED_PRIVATE_PREVIEW", IDENTIFIER).reconcile_restart()
    assert not private.get(v["session_id"])["research_available"]


def test_rejected_policy_pending_refs_not_usable_for_model(private):
    v = chosen(private)
    private.db.connection.execute("UPDATE extraction_candidates SET context_status='REJECTED'")
    assert not private.get(v["session_id"])["model_available"]
    assert not private.get(v["session_id"])["activity_candidates"]
    assert not private.get(v["session_id"])["references"]


def test_same_call_names_require_exact_supported_positive_references(private):
    v = create(private, "合成青谷")
    _, state = private.load(v["session_id"])
    payload = payload_for(state["planning"], private.db, "owner", v["session_id"])
    e = payload["references"][0]
    from travel_agent.planning.materials import activities

    name = activities(v["references"], "合成青谷")[0].name
    e = next(e for e in payload["references"] if name in e["text"])
    raw = response(payload)
    raw["proposals"][0]["activities"] = [
        dict(activity_id="candidate-0", day=1, stay_min=30, stay_max=60, rest_minutes=15)
    ]
    raw["grounded_activities"] = [
        dict(candidate_key="candidate-0", place_name=name, evidence_ids=[e["claim_id"]])
    ]
    result, data, catalog = ground(raw, payload)
    assert validate_response(result, data) and catalog[0]["conditions"]
    raw["grounded_activities"][0]["place_name"] = "模型记忆中的新景点"
    with pytest.raises(ValueError):
        ground(raw, payload)


class Maps(AmapAdapter):
    def __init__(self):
        super().__init__(SecretStr("AUTHORED_FIXTURE"))
        self.calls = []

    def resolve_place(self, name, region=""):
        self.calls.append("place")
        return {
            "status": "OK",
            "candidates": [
                dict(
                    name=name,
                    location="120.1,31.1",
                    type="风景名胜",
                    address="自编公共地标",
                    pname="自编省",
                    cityname=region,
                    adname="自编区",
                    citycode="0512",
                    adcode="320500",
                    coordinate_system="GCJ02",
                )
            ],
        }

    def route(self, start, end, mode, at=None):
        self.calls.append(mode)
        return dict(
            status="OK",
            duration_seconds=659,
            distance_meters=700,
            date_applicability="GENERAL_REFERENCE_ONLY",
        )


def test_private_maps_adopted_edges_mode_stale_budget_and_expiry(private):
    v = chosen(private)
    sid = v["session_id"]
    adapter = Maps()
    maps = PrivateFlowMapService(private.db.path, "owner", "CACHED_PRIVATE_PREVIEW", adapter)

    def change(action, **kwargs):
        m = maps.get(sid)
        return maps.mutate(
            MapAction(
                action=action,
                session_id=sid,
                expected_revision=m["revision"],
                expected_preview_revision=m["preview_revision"],
                send_confirmed=True,
                **kwargs,
            ),
            str(uuid4()),
        )

    for a in v["draft"]["activities"]:
        m = change("resolve", place_id=a["activity_id"])
        poi = next(p for p in m["places"] if p["place_id"] == a["activity_id"])["candidates"][0]
        change(
            "confirm_place",
            place_id=a["activity_id"],
            candidate_id=poi["candidate_id"],
            relation="SAME_OBJECT",
        )
    lid = maps.get(sid)["legs"][0]["leg_id"]
    with pytest.raises(ValueError, match="ADOPT_ORDER"):
        change("route", leg_id=lid)
    v = act(private, v, "adopt")
    m = change("route", leg_id=lid)
    assert m["legs"][0]["duration_seconds"] == 659 and adapter.calls == [
        "place",
        "place",
        "TRANSIT",
    ]
    MapView.model_validate(m)
    d = PlanDraft.model_validate(v["draft"])
    d.activities.reverse()
    v = act(private, v, "save", draft=d)
    assert maps.get(sid)["legs"][0]["duration_seconds"] is None
    with pytest.raises(ValueError, match="ADOPT_ORDER"):
        change("route", leg_id=maps.get(sid)["legs"][0]["leg_id"])
    fresh = PrivateFlowMapService(private.db.path, "owner", "CACHED_PRIVATE_PREVIEW", adapter).get(
        sid
    )
    assert fresh["map_result_state"] == "EXPIRED_OR_NOT_QUERIED"
    assert fresh["budget"]["used"] == {"map_place": 2, "map_route": 1}
    assert len(adapter.calls) == 3


def test_seconds_intervals_night_and_day_independence(private):
    v = chosen(private)
    d = PlanDraft.model_validate(v["draft"])
    a, b = d.activities
    a.stay_min, a.stay_max, a.rest_minutes = 60, 90, 0
    b.stay_min, b.stay_max = 30, 45
    lid = a.activity_id + "--" + b.activity_id
    rows, _ = timeline(d, {lid: 59 / 60})
    assert rows[1]["start"] == "11:00:59—11:30:59"
    b.locked_start = "11:15"
    assert any("可能迟到" in g for g in timeline(d, {lid: 59 / 60})[1])
    b.locked_start = "10:59"
    assert any("时间冲突" in g for g in timeline(d, {lid: 59 / 60})[1])
    b.locked_start = None
    d.inputs.activity_start, d.inputs.activity_end = "23:00", "02:00"
    rows, gaps = timeline(d, {lid: 59 / 60})
    assert rows[1]["start"].startswith("+1天 00:00:59")
    assert not any("超出活动结束" in g for g in gaps)
    b.day = 2
    rows, _ = timeline(d, {lid: 59 / 60})
    assert rows[1]["start"] == "开始时间待选" and rows[1]["movement_minutes"] is None


def test_normal_research_v3_model_review_attaches_without_replacing_adopted(private):
    from test_workbench_pipeline import Provider, Reader, dispatches
    from travel_agent.preview.worker import run_job
    from travel_agent.research.models import Candidate

    private.db.connection.execute(
        "UPDATE research_questions SET request_json=?", ('{"destination":"无关区域"}',)
    )
    v = create(private, "合成青谷", request="一天，公共交通和步行，上午10点开始")
    v = act(private, v, "adopt")
    original = deepcopy(v["adopted"])
    v = act(private, v, "research")
    row = private.db.connection.execute(
        "SELECT job_id FROM preview_jobs WHERE continuation_id=?", (IDENTIFIER,)
    ).fetchone()

    class CityReader(Reader):
        def search(self, query):
            self.calls.append("search")
            assert "合成青谷" in query and "公共交通" in query and "步行" in query
            return (Candidate("xhs:city-fixture", "合成青谷一天市区路线", "normal", True),)

    reader, provider = CityReader(), Provider()
    extract, review = dispatches(provider)
    run_job(
        private.db.path,
        row[0],
        reader=reader,
        provider=provider,
        extract_dispatch=extract,
        review_dispatch=review,
    )
    v = private.get(v["session_id"])
    assert v["research_job"]["can_adopt"]
    v = act(private, v, "adopt_research")
    new = [r for r in v["references"] if r["source_id"] == "xhs:city-fixture"]
    assert new and all(r["review_status"] == "MODEL_CONTEXT_REVIEWED" for r in new)
    assert v["adopted"] == original
    assert provider.calls == ["select_evidence_references_v1", "review_evidence_context_v2"]
    assert reader.calls == ["connect", "search", "detail"]
    assert v["private_budget"]["used"]["model"] == 2


@pytest.mark.parametrize(
    "role", ["serve", "worker", "job-worker", "extract-worker", "review-worker"]
)
def test_role_fence_blocks_other_hosts_before_transport(tmp_path, role):
    code = """
import sys,json,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
from travel_agent.planning.network import install
install(sys.argv[1],Path(sys.argv[2]))
try: urllib.request.urlopen('https://not-authorized.invalid/unrelated',timeout=1)
except PermissionError: pass
else: raise AssertionError('NOT_BLOCKED')
v=json.loads(Path(sys.argv[2]).read_text())
assert v['blocked_external']==1 and v['external_dns']==0 and v['external_socket']==0
print('DENIED_BEFORE_NETWORK')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, role, str(tmp_path / "metrics.json")],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "DENIED_BEFORE_NETWORK" in result.stdout


def test_source_policy_change_after_response_blocks_adoption(private):
    v = act(private, chosen(private), "suggest")

    class Fake:
        def structured(self, task, data, schema):
            return response(data)

    run_worker(private.db.path, v["job"]["job_id"], Fake())
    v = private.get(v["session_id"])
    assert v["job"]["status"] == "COMPLETED"
    private.db.connection.execute("UPDATE extraction_candidates SET context_status='REJECTED'")
    with pytest.raises(ValueError, match="REFERENCE_UNAVAILABLE|STALE_PROPOSAL"):
        act(private, v, "use_proposal")
    assert private.get(v["session_id"])["adopted"] is None


def test_failed_transport_proposal_keeps_draft_and_no_retry_offer(private):
    v = act(private, chosen(private), "suggest")

    class WrongTransport:
        def structured(self, task, data, schema):
            result = response(data)
            result["proposals"][0]["transport"] = "WALKING"
            return result

    run_worker(private.db.path, v["job"]["job_id"], WrongTransport())
    result = private.get(v["session_id"])
    assert result["job"]["reason"] == "PLANNING_LOCKED_TRANSPORT"
    assert result["draft"] == v["draft"] and not result["model_available"]


def test_city_area_outbound_context_cannot_satisfy_early_stop_target():
    from travel_agent.planning.materials import scope_gaps

    rows = [dict(text="合成园→合成街", conditions=["从合成城的市区出发，去邻县玩。"])]
    assert scope_gaps(True, rows)
    assert not scope_gaps(False, rows)
    assert not scope_gaps(True, [dict(text="合成园→合成街", conditions=["市区内公交游览。"])])


def test_city_scope_gap_keeps_research_available_when_budget_allows(private, monkeypatch):
    v = create(private, "合成青谷", request="市区一天公共交通")
    assert len(v["activity_candidates"]) >= 2 and not v["research_available"]
    monkeypatch.setattr("travel_agent.planning.materials.scope_gaps", lambda *_: ["区域待核实"])
    result = private.get(v["session_id"])
    assert result["research_available"] and "区域待核实" in result["gaps"]


def test_second_source_error_does_not_discard_first_independent_result(private):
    from test_workbench_pipeline import Provider, Reader, dispatches
    from travel_agent.preview.worker import run_job
    from travel_agent.research.models import Candidate, ResearchStopped

    private.db.connection.execute(
        "UPDATE research_questions SET request_json=?", ('{"destination":"无关区域"}',)
    )
    v = act(private, create(private, "合成青谷", request="一天，公共交通"), "research")
    jid = private.db.connection.execute(
        "SELECT job_id FROM preview_jobs WHERE continuation_id=?", (IDENTIFIER,)
    ).fetchone()[0]

    class PartialReader(Reader):
        def search(self, query):
            return (
                Candidate("xhs:partial-city-a", "合成青谷一天市区小镇路线", "normal", True),
                Candidate("xhs:partial-city-b", "合成青谷一天市区公园路线", "normal", True),
            )

        def detail(self, c, n):
            if n == 2:
                raise ResearchStopped("ERROR", "AUTHORED_SECOND_SOURCE_FAILURE")
            return super().detail(c, n)

    provider = Provider()
    extract, review = dispatches(provider)
    run_job(
        private.db.path,
        jid,
        reader=PartialReader(),
        provider=provider,
        extract_dispatch=extract,
        review_dispatch=review,
    )
    result = private.get(v["session_id"])
    assert result["research_job"]["status"] == "PARTIAL" and result["research_job"]["can_adopt"]
    assert result["private_budget"]["used"]["detail"] == 2
    assert result["private_budget"]["used"]["model"] == 2
