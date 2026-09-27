"""Normal page contracts, immutable grants and production workers with authored fakes."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.flow_models import PlanDraft, PlanAction, OperationAuthorization
from travel_agent.planning.private_budget import PrivatePlanningBudget
from travel_agent.planning.suggestions import run_worker
from travel_agent.preview.api import PreviewConfig
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.main import create_app
from travel_agent.settings import Settings
from test_cached_overview import seed
from test_planning_flow import act, create
from test_plan_revisions import Model, adjust
from test_place_discovery import discovery as discovery_fixture, discover_and_check, Planner

discovery = discovery_fixture


@pytest.fixture
def normal(tmp_path, monkeypatch):
    provider = OpenAICompatibleProvider(
        "https://api.deepseek.com", "authored", SecretStr("fixture"), 120, "json_object"
    )
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", lambda: provider)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", lambda: provider)
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "authored-map-key")
    with Database(tmp_path / "daily.sqlite3") as db:
        seed(db, db.clock)
        old = PlanningService(db, "owner")
        v = create(old, "合成青谷")
        v = act(
            old,
            v,
            "use_activities",
            activity_ids=[a["activity_id"] for a in v["activity_candidates"][:2]],
        )
        draft = PlanDraft.model_validate(v["draft"])
        draft.inputs.activity_start = "09:30"
        draft.transport = "SELF_DRIVE"
        for a in draft.activities:
            a.stay_min, a.stay_max, a.rest_minutes = 45, 75, 15
        v = act(old, act(old, v, "save", draft=draft), "adopt")
        assert (
            db.connection.execute("SELECT count(*) FROM research_continuations").fetchone()[0] == 0
        )
        yield PlanningService(db, "owner", daily_workbench=True), v


def reuse(s, old):
    v = create(s, "合成青谷", request="一天，公共交通和步行，10点开始首项")
    assert v["draft"]["activities"] == [] and v["adopted"] is None
    choice = next(o for o in v["reuse_options"] if o["session_id"] == old["session_id"])
    v = act(
        s,
        v,
        "reuse_activities",
        reuse_key=choice["key"],
        activity_ids=[a["activity_id"] for a in choice["activities"]],
    )
    assert (
        v["draft"]["transport"] == "PUBLIC_TRANSIT"
        and v["draft"]["inputs"]["activity_start"] == "10:00"
    )
    return act(s, v, "adopt")


def permit(s, v, model=3, **values):
    return act(
        s,
        v,
        "authorize",
        authorization=OperationAuthorization(
            confirm=True,
            tasks=["PLANNING", "REVISION", *(["MAP"] if values.get("map_place") else [])],
            model=model,
            **values,
        ),
    )


def revise(s, v, intent, model):
    v = adjust(s, v, intent)
    assert v["model_available"], v["model_status"]
    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], model)
    run_worker(s.db.path, v["job"]["job_id"], model)
    v = s.get(v["session_id"])
    assert v["job"]["status"] == "COMPLETED", v["job"]
    before = deepcopy(v["adopted"])
    v = act(s, v, "use_proposal")
    assert v["adopted"] == before
    v = act(s, v, "cancel")
    assert v["draft"] == before
    return act(s, act(s, v, "use_proposal"), "adopt")


def test_reverse_intent_third_operation_append_revoke_recover(normal):
    s, old = normal
    unchanged = s.db.connection.execute(
        "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
    ).fetchone()[0]
    v = permit(s, reuse(s, old))
    model = Model()
    v = revise(s, v, "FEWER", model)
    assert len(v["adopted"]["activities"]) == 1
    v = revise(s, v, "LONGER_FIRST", model)
    v = revise(s, v, "LONGER_FIRST", model)
    assert model.calls == 3 and v["operation"]["cumulative_used"]["model"] == 3
    assert v["adopted"]["activities"][0]["stay_min"] == 75
    assert not v["model_available"] and v["model_status"] == "BUDGET_EXHAUSTED"
    previous = dict(s.db.connection.execute("SELECT * FROM research_continuations").fetchone())
    v = permit(s, v, 1)
    rows = s.db.connection.execute("SELECT * FROM research_continuations ORDER BY rowid").fetchall()
    assert len(rows) == 2 and rows[1]["predecessor"] == previous["continuation_id"]
    assert rows[0]["limits_json"] == previous["limits_json"] and rows[0]["finished_at"]
    assert v["operation"]["cumulative_used"]["model"] == 3
    v = act(s, v, "revoke_authorization")
    assert v["model_status"] == "OPERATION_CLOSED"
    d = PlanDraft.model_validate(v["draft"])
    d.activities[0].rest_minutes = 20
    v = act(s, v, "save", draft=d)
    assert v["draft"]["activities"][0]["rest_minutes"] == 20
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
        ).fetchone()[0]
        == unchanged
    )
    code = """
import sys,socket
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def denied(*a,**k): raise AssertionError('NETWORK')
socket.getaddrinfo=denied;socket.socket.connect=denied
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner',daily_workbench=True).get(sys.argv[2])
 assert len(v['adopted']['activities'])==1 and v['draft']['activities'][0]['rest_minutes']==20
 assert v['operation']['cumulative_used']['model']==3 and not v['operation']['active']
 assert v['adopted']['inputs']['activity_start']=='10:00'
 print('NORMAL_NONEMPTY_RECOVERY_ZERO_EXTERNAL')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(s.db.path), v["session_id"]],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_scope_missing_authorization_defaults_and_destination_isolation(normal):
    s, old = normal
    v = permit(s, reuse(s, old))
    b = PrivatePlanningBudget.for_trip(s.db, v["session_id"])
    for destination, kind in [
        ("合成青谷", "CITY"),
        ("合成青谷", "REGIONAL"),
        ("另一城市", "CITY"),
        ("缓存未命中", "CITY"),
    ]:
        other = create(s, destination, kind=kind)
        assert not other["model_available"] and other["private_budget"] is None
        assert other["draft"]["activities"] == [] and other["draft"]["days"] is None
        assert other["draft"]["inputs"]["activity_start"] is None
        assert (
            other["draft"]["transport"] == "UNKNOWN"
            and other["draft"]["inputs"]["charter"] == "UNKNOWN"
        )
        if destination != "合成青谷" or kind != "CITY":
            assert other["reuse_options"] == []
        with pytest.raises(ValueError, match="SCOPE"):
            b.check_trip("owner", other["session_id"])
        with pytest.raises(ValueError):
            act(s, other, "suggest")
    assert b.summary()["used"]["model"] == 0


@pytest.mark.parametrize("action", ["revoke", "expire", "edit", "cancel"])
def test_late_result_rejected_without_budget_refund(normal, action, monkeypatch):
    s, old = normal
    v = adjust(s, permit(s, reuse(s, old)), "FEWER")
    v = act(s, v, "suggest")
    initial = deepcopy(v["adopted"])

    class Late(Model):
        def structured(self, task, data, schema):
            result = super().structured(task, data, schema)
            current = s.get(v["session_id"])
            if action == "revoke":
                act(s, current, "revoke_authorization")
            elif action == "cancel":
                act(s, current, "cancel_job")
            elif action == "edit":
                act(s, current, "save", draft=PlanDraft.model_validate(current["draft"]))
            else:
                # Move only the authored test clock on all worker Database instances.
                import travel_agent.planning.workbench as module

                real = module.check_active

                def expired(db, state):
                    db.clock = lambda: datetime.now(timezone.utc) + timedelta(days=9)
                    return real(db, state)

                monkeypatch.setattr(module, "check_active", expired)
            return result

    run_worker(s.db.path, v["job"]["job_id"], Late())
    out = s.get(v["session_id"])
    assert out["job"]["status"] in {"FAILED", "CANCELED"}
    assert out["adopted"] == initial
    assert out["operation"]["cumulative_used"]["model"] == 1


def test_failed_task_not_permanent_lock_idempotence_and_concurrent_receipt(normal):
    s, old = normal
    v = adjust(s, permit(s, reuse(s, old)), "FEWER")
    key = str(uuid4())
    request = PlanAction(action="suggest", expected_revision=v["revision"])
    first = s.mutate(v["session_id"], request, key)
    second = s.mutate(v["session_id"], request, key)
    assert first == second and first["operation"]["cumulative_used"]["model"] == 1
    with pytest.raises(ValueError, match="STALE_REVISION"):
        s.mutate(v["session_id"], request, str(uuid4()))

    class Failure:
        def structured(self, *args):
            raise TimeoutError("authored timeout")

    run_worker(s.db.path, first["job"]["job_id"], Failure())
    failed = s.get(v["session_id"])
    assert failed["job"]["status"] == "FAILED" and failed["model_available"]
    completed = revise(s, failed, "FEWER", Model())
    assert completed["operation"]["cumulative_used"]["model"] == 2


def test_page_api_authorization_receipt_no_prior_grants(normal, monkeypatch):
    s, old = normal
    config = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"a" * 32,
        product_flow=True,
        daily_workbench=True,
    )
    monkeypatch.setattr("travel_agent.planning.flow_api.launch", lambda *a, **kw: None)
    with TestClient(
        create_app(Settings.load(preferred_port=18768), preview=config),
        base_url="http://127.0.0.1:18768",
    ) as client:
        client.get("/bootstrap?ticket=" + config.ticket)
        headers = {
            "Origin": "http://127.0.0.1:18768",
            "X-CSRF-Token": client.get("/api/v1/preview").json()["csrf_token"],
            "Idempotency-Key": str(uuid4()),
        }
        v = client.post(
            "/api/v1/preview/planning", json={"destination": "合成青谷"}, headers=headers
        ).json()
        assert v["operation"]["status"] == "NOT_AUTHORIZED"
        assert (
            s.db.connection.execute("SELECT count(*) FROM research_continuations").fetchone()[0]
            == 0
        )
        body = dict(
            action="authorize",
            expected_revision=v["revision"],
            authorization=dict(
                confirm=True,
                tasks=["PLANNING", "REVISION", "MAP"],
                model=3,
                map_place=2,
                map_route=1,
            ),
        )
        url = "/api/v1/preview/planning/" + v["session_id"]
        assert client.post(url, json=body).status_code == 403
        headers["Idempotency-Key"] = str(uuid4())
        out = client.post(url, json=body, headers=headers)
        assert out.status_code == 200, out.text
        assert client.post(url, json=body, headers=headers).json() == out.json()
        assert (
            s.db.connection.execute("SELECT count(*) FROM research_continuations").fetchone()[0]
            == 1
        )
        for _ in range(3):
            assert client.get(url).status_code == 200
            maps = client.get("/api/v1/preview/planning-maps/" + v["session_id"])
            assert maps.status_code == 200, maps.text
            assert maps.json()["budget"]["total_limit"] == 3
            assert maps.json()["configured"]
        assert (
            s.db.connection.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            == 0
        )


def test_blank_install_and_missing_or_damaged_existing_database(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path("scripts").resolve()))
    from product_preview import prepare_runtime

    path = prepare_runtime(tmp_path / "fresh")
    with Database(path) as db:
        s = PlanningService(db, "fresh-owner", daily_workbench=True)
        v = create(s, "未知城市")
        assert v["operation"]["status"] == "NOT_AUTHORIZED" and not v["draft"]["activities"]
    path.unlink()
    with pytest.raises(ValueError, match="DATABASE_MISSING"):
        prepare_runtime(path.parent)
    path.write_text("not sqlite")
    with pytest.raises(Exception):
        prepare_runtime(path.parent)


def test_normal_research_pending_first_v3_review_second_then_planning(normal):
    from travel_agent.preview.worker import run_job
    from travel_agent.research.models import Candidate, DetailMaterial
    from test_workbench_pipeline import Provider, dispatches
    from test_model_context_review import BODY
    from test_planning_flow import response

    s, _ = normal
    v = create(s, "合成青谷", request="市区一日，公共交通，10点开始首项")
    v = act(
        s,
        v,
        "authorize",
        authorization=OperationAuthorization(
            confirm=True, tasks=["RESEARCH", "PLANNING"], connect=1, search=1, detail=2, model=5
        ),
    )
    v = act(s, v, "research")

    class Reader:
        text_first = False

        def __init__(self):
            self.details = []

        def connect(self):
            pass

        def search(self, query):
            assert "市区" in query and "公共交通" in query
            return tuple(
                Candidate("xhs:daily-" + i, "合成青谷市区一日路线" + i, "normal", True)
                for i in ["a", "b"]
            )

        def detail(self, c, n):
            self.details.append(n)
            text = (
                BODY
                if n == 1
                else "合成青谷市区一日游计划，还没出发。\n城市活动草案。\nDay1：合成南园→合成北馆。\n我想了解展馆的建筑风格。\n接驳班车每天十点发车。"
            )
            return DetailMaterial(c.source_id, c.title, text, "PARTIAL_TEXT", s.db.stamp())

    class Reviewed(Provider):
        def structured(self, task, data, schema):
            result = super().structured(task, data, schema)
            if task == "review_evidence_context_v2" and len(self.calls) == 2:
                for item in result["reviews"]:
                    item["reference_scope"] = "AUTHOR_RECORDED_TRIP"
            return result

    model, reader = Reviewed(), Reader()
    extract, review = dispatches(model)
    run_job(
        s.db.path,
        v["research_job"]["job_id"],
        reader=reader,
        provider=model,
        extract_dispatch=extract,
        review_dispatch=review,
        product=True,
    )
    v = s.get(v["session_id"])
    assert reader.details == [1, 2] and len(model.calls) == 4, v["research_job"]
    assert v["operation"]["current"]["remaining"]["model"] == 1
    assert (
        s.db.connection.execute(
            "SELECT count(*) FROM extraction_candidates WHERE context_status='PENDING'"
        ).fetchone()[0]
        > 0
    )
    v = act(s, v, "adopt_research")
    candidates = [a for a in v["activity_candidates"] if a["spatial_status"] == "MATCH"]
    assert len(candidates) >= 2
    v = act(s, v, "use_activities", activity_ids=[a["activity_id"] for a in candidates[:2]])

    class Planner:
        def structured(self, task, data, schema):
            assert task == "planning_arrangement_v2"
            out = response(data)
            p = out["proposals"][0]
            p["citation_ids"] = data["allowed_citation_ids"]
            return dict(protocol_version=2, proposals=[p])

    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], Planner())
    v = s.get(v["session_id"])
    assert v["job"]["accepted_count"] == 1, json.dumps(v["job"], ensure_ascii=False)
    v = act(s, act(s, v, "use_proposal"), "adopt")
    assert len(v["adopted"]["activities"]) == 2
    assert v["operation"]["cumulative_used"]["model"] == 5


def test_normal_map_service_authorization_direction_and_revocation(normal):
    from travel_agent.planning.flow_maps import PrivateFlowMapService
    from travel_agent.planning.models import MapAction
    from test_private_planning import Maps

    s, old = normal
    v = permit(s, reuse(s, old), model=0, map_place=2, map_route=1)
    adapter = Maps()
    maps = PrivateFlowMapService(s.db.path, "owner", "CACHED_PRIVATE_PREVIEW", adapter)

    def change(action, **values):
        m = maps.get(v["session_id"])
        return maps.mutate(
            MapAction(
                action=action,
                session_id=v["session_id"],
                expected_revision=m["revision"],
                expected_preview_revision=m["preview_revision"],
                send_confirmed=True,
                **values,
            ),
            str(uuid4()),
        )

    for a in v["draft"]["activities"]:
        out = change("resolve", place_id=a["activity_id"])
        place = next(p for p in out["places"] if p["place_id"] == a["activity_id"])
        change(
            "confirm_place",
            place_id=a["activity_id"],
            candidate_id=place["candidates"][0]["candidate_id"],
            relation="SAME_OBJECT",
        )
    m = maps.get(v["session_id"])
    result = change("route", leg_id=m["legs"][0]["leg_id"])
    assert result["legs"][0]["status"] == "OK"
    assert adapter.calls == ["place", "place", "TRANSIT"]
    fresh = PrivateFlowMapService(s.db.path, "owner", "CACHED_PRIVATE_PREVIEW", Maps()).get(
        v["session_id"]
    )
    assert all(leg["duration_seconds"] is None for leg in fresh["legs"])
    v = act(s, s.get(v["session_id"]), "revoke_authorization")
    assert not maps.get(v["session_id"])["configured"]
    with pytest.raises(ValueError):
        change("route", leg_id=m["legs"][0]["leg_id"])
    assert len(adapter.calls) == 3


def test_authorization_concurrent_receipt_and_increased_limits_explicit(normal):
    from concurrent.futures import ThreadPoolExecutor

    s, old = normal
    v = reuse(s, old)
    key = str(uuid4())
    action = PlanAction(
        action="authorize",
        expected_revision=v["revision"],
        authorization=OperationAuthorization(confirm=True, tasks=["REVISION"], model=3),
    )

    def submit():
        with Database(s.db.path) as db:
            return PlanningService(db, "owner", daily_workbench=True).mutate(
                v["session_id"], action, key
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda _: submit(), range(2)))
    assert a == b and len(a["operation"]["history"]) == 1
    altered = action.model_copy(deep=True)
    altered.authorization.model = 4
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        s.mutate(v["session_id"], altered, key)


def test_explicit_mention_reuse_keeps_lineage_and_old_plan(discovery, monkeypatch):
    old_service, old = discovery
    old, _, _ = discover_and_check(old_service, old, 2)
    old = act(
        old_service,
        old,
        "use_leads",
        activity_ids=[lead["lead_id"] for lead in old["place_leads"][:2]],
    )
    old = act(old_service, old, "suggest")
    run_worker(old_service.db.path, old["job"]["job_id"], Planner())
    old = act(
        old_service, act(old_service, old_service.get(old["session_id"]), "use_proposal"), "adopt"
    )
    before = old_service.db.connection.execute(
        "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
    ).fetchone()[0]
    claims = old_service.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    old_service.db.clock = lambda: datetime.now(timezone.utc)
    config = OpenAICompatibleProvider(
        "https://api.deepseek.com", "authored", SecretStr("fixture"), 120, "json_object"
    )
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", lambda: config)
    s = PlanningService(old_service.db, "owner", daily_workbench=True)
    v = reuse(s, old)
    assert all(
        a["provenance"] == "SOURCE_MENTION" and a["timing_origin"] == "AI_PROPOSED"
        for a in v["draft"]["activities"]
    )
    assert len(v["place_leads"]) == 2 and all(
        a["spatial_status"] == "UNKNOWN" for a in v["place_leads"]
    )
    v = permit(s, v, 2)
    v = revise(s, v, "FEWER", Model())
    v = revise(s, v, "LONGER_FIRST", Model())
    assert len(v["adopted"]["activities"]) == 1
    assert s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == claims
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
        ).fetchone()[0]
        == before
    )
