"""Authored regression for scope and independently checked arrangements; no live data."""

import pytest
import json
import subprocess
import sys
from pathlib import Path
from copy import deepcopy
from test_private_planning import private as private_fixture, chosen
from test_planning_flow import create, act, response

from travel_agent.planning.spatial import parse_intent, classify
from travel_agent.planning.arrangements import validate_arrangements

private = private_fixture


def inputs():
    return dict(
        protocol_version=2,
        purpose="PRIVATE_PLANNING",
        first_start="10:00",
        first_day=1,
        days=1,
        transport="PUBLIC_TRANSIT",
        walking_allowed=True,
        driving="NO",
        charter="NO",
        return_deadline="21:00",
        activity_end=None,
        allowed_citation_ids=["e1"],
        references=[{"claim_id": "e1"}],
        spatial_intent="CITY_CORE",
        activities=[
            dict(
                activity_id=i,
                name=i,
                day=1,
                locked_start=None,
                evidence_ids=["e1"],
                spatial_status="MATCH",
            )
            for i in ["a", "b"]
        ],
    )


def proposal():
    return dict(
        title="先公园后展馆",
        reason="为两处活动留出休息。",
        activities=[
            dict(activity_id=i, day=1, stay_min=40, stay_max=70, rest_minutes=10)
            for i in ["a", "b"]
        ],
        citation_ids=["e1"],
        assumptions=["停留和休息是建议"],
        unknowns=["交通与开放尚未核实"],
        impacts=["两项活动节奏较松"],
    )


def test_spatial_city_is_not_city_core_and_mixed_note_is_per_activity():
    assert parse_intent("合成青谷", "CITY", False).intent == "UNDECIDED"
    assert parse_intent("合成青谷市区一天", "CITY", True).intent == "CITY_CORE"
    rows = [
        dict(
            claim_id="e1",
            text="甲园→乙馆",
            conditions=["甲园位于市区内。乙馆在近郊。"],
            source_title="城市游",
        )
    ]
    assert classify("甲园", rows, "CITY_CORE")[0] == "MATCH"
    assert classify("乙馆", rows, "CITY_CORE")[0] == "MISMATCH"
    assert (
        classify(
            "甲园", [dict(rows[0], conditions=["甲园可能位于市区。"])], "CITY_AND_SURROUNDINGS"
        )[0]
        == "UNKNOWN"
    )
    assert (
        classify(
            "甲园", [dict(rows[0], conditions=["从市区出发。"], source_title="市区游")], "CITY_CORE"
        )[0]
        == "UNKNOWN"
    )


def test_fixed_constraints_not_repeated_and_one_invalid_proposal_is_isolated():
    a = proposal()
    a["activities"][0]["activity_id"] = "invalid"
    out = validate_arrangements(
        dict(protocol_version=2, proposals=[a, proposal()], grounded_activities=[]), inputs()
    )
    assert out["accepted_count"] == 1 and out["rejected_count"] == 1
    accepted = out["proposals"][0]
    assert accepted["first_start"] == "10:00" and accepted["transport"] == "PUBLIC_TRANSIT"
    assert accepted["fixed_origin"] == "PROGRAM_INPUT" and accepted["proposal_id"].endswith("-2")


def test_implicit_driving_rejected_while_transit_walking_is_compatible():
    bad = proposal()
    bad["reason"] = "租车自驾前往第二处。"
    good = proposal()
    good["reason"] = "公共交通与步行结合，接驳时间未知。"
    good["unknowns"].append("无法保证抵达时间，等待地图参考。")
    out = validate_arrangements(dict(protocol_version=2, proposals=[bad, good]), inputs())
    assert out["accepted_count"] == 1
    assert out["decisions"][0]["reason"] == "PLANNING_LOCKED_TRANSPORT"


def test_schema_problem_is_local_but_credentials_are_global_failure():
    a = proposal()
    a["activities"][0]["stay_min"] = "many"
    out = validate_arrangements(dict(protocol_version=2, proposals=[a, proposal()]), inputs())
    assert out["accepted_count"] == 1 and out["decisions"][0]["field"]
    a = proposal()
    a["reason"] = "authorization: Bearer SECRET_SENTINEL"
    with pytest.raises(ValueError, match="PLANNING_UNSAFE_RESPONSE"):
        validate_arrangements(dict(protocol_version=2, proposals=[a, proposal()]), inputs())


def test_unknown_fields_remain_suggestions_and_locked_time_is_not_moved():
    data = inputs()
    data["transport"] = "UNKNOWN"
    data["first_start"] = None
    p = proposal()
    p["unresolved_suggestions"] = {"transport": "WALKING", "first_start": "09:00"}
    out = validate_arrangements(dict(protocol_version=2, proposals=[p]), data)
    assert (
        out["proposals"][0]["transport"] == "UNKNOWN" and out["proposals"][0]["first_start"] is None
    )
    data = inputs()
    data["activities"][1]["locked_start"] = "10:20"
    out = validate_arrangements(dict(protocol_version=2, proposals=[proposal()]), data)
    assert out["accepted_count"] == 0


def test_shared_catalog_isolated_without_rescuing_dependent_proposals():
    data = inputs()
    data.update(
        destination="合成青谷",
        activities=[],
        spatial_intent="UNDECIDED",
        references=[
            dict(
                claim_id="e1",
                text="甲园→乙馆",
                conditions=["合成攻略整理"],
                topic="ROUTE",
                reference_kind="GUIDE_SUGGESTION",
            )
        ],
    )
    a, b = proposal(), proposal()
    a["activities"] = [dict(a["activities"][0], activity_id="candidate-0")]
    b["activities"] = [dict(b["activities"][0], activity_id="candidate-1")]
    raw = dict(
        protocol_version=2,
        proposals=[a, b],
        grounded_activities=[
            dict(candidate_key="candidate-0", place_name="虚构外来名", evidence_ids=["e1"]),
            dict(candidate_key="candidate-1", place_name="甲园", evidence_ids=["e1"]),
        ],
    )
    out = validate_arrangements(raw, data)
    assert out["accepted_count"] == 1 and out["rejected_count"] == 1
    assert len(out["activity_catalog"]) == 1 and out["proposals"][0]["proposal_id"].endswith("-2")


@pytest.mark.parametrize("field,value", [("transport", "SELF_DRIVE"), ("first_start", "08:00")])
def test_fixed_field_in_response_rejected_not_relabelled(field, value):
    a = proposal()
    a[field] = value
    out = validate_arrangements(dict(protocol_version=2, proposals=[a, proposal()]), inputs())
    assert out["accepted_count"] == 1 and out["decisions"][0]["field"] == field


def test_deadline_and_locked_day_protected():
    data = inputs()
    data["return_deadline"] = "10:30"
    assert (
        validate_arrangements(dict(protocol_version=2, proposals=[proposal()]), data)[
            "accepted_count"
        ]
        == 0
    )
    data = inputs()
    data["days"] = 2
    data["activities"][1]["locked_start"] = "14:00"
    p = proposal()
    p["activities"][1]["day"] = 2
    assert (
        validate_arrangements(dict(protocol_version=2, proposals=[p]), data)["accepted_count"] == 0
    )


def test_title_and_request_region_are_not_location_observation():
    from travel_agent.planning.materials import activities

    rows = [
        dict(
            claim_id="e1",
            source_title="合成水城市区一日游",
            text="甲园（市区）→乙馆（近郊）",
            conditions=[],
            topic="ROUTE",
            reference_kind="GUIDE_SUGGESTION",
        )
    ]
    items = activities(rows, "合成水城", "CITY_CORE")
    assert [a.spatial_status for a in items] == ["MATCH", "MISMATCH"]
    assert all(a.region_origin == "REQUEST_FILTER" for a in items)
    plain = [dict(rows[0], text="甲园→乙馆")]
    assert all(
        a.spatial_status == "UNKNOWN" and not a.source_locations
        for a in activities(plain, "合成水城", "CITY_CORE")
    )
    assert parse_intent("去合成水城和周边", "CITY", False).intent == "UNDECIDED"
    assert parse_intent("城市与周边", "CITY", False).intent == "CITY_AND_SURROUNDINGS"


def test_rounded_display_does_not_change_seconds_or_fixed_appointments():
    from travel_agent.planning.flow import timeline
    from travel_agent.planning.flow_models import Activity, PlanDraft

    d = PlanDraft(
        activities=[
            Activity(
                activity_id="a",
                name="甲园",
                provenance="USER_INPUT",
                stay_min=60,
                stay_max=90,
                rest_minutes=15,
            ),
            Activity(activity_id="b", name="乙馆", provenance="USER_INPUT"),
        ]
    )
    d.inputs.activity_start = "10:00"
    rows, _ = timeline(d, {"a--b": 2763 / 60})
    assert rows[1]["start"] == "12:01:03—12:31:03" and rows[1]["display_start"] == "约 12:00—12:35"
    assert rows[0]["display_start"] == "10:00" and rows[1]["movement_minutes"] * 60 == 2763
    d.activities[1].locked_start = "13:02"
    rows, _ = timeline(d, {"a--b": 2763 / 60})
    assert rows[1]["display_start"] == "13:02"
    rows, _ = timeline(d)
    assert rows[1]["movement_minutes"] is None


def test_partial_worker_adoption_revalidation_and_local_recovery(private):
    from travel_agent.planning.suggestions import run_worker

    v = act(private, chosen(private), "suggest")

    class Fake:
        def structured(self, task, data, schema):
            assert task == "planning_arrangement_v2"
            good = response(data)
            bad = deepcopy(good["proposals"][0])
            bad["activities"][0]["stay_min"] = "invalid"
            good["proposals"].insert(0, bad)
            return good

    run_worker(private.db.path, v["job"]["job_id"], Fake())
    v = private.get(v["session_id"])
    assert v["job"]["status"] == "PARTIAL" and v["job"]["accepted_count"] == 1
    assert v["job"]["proposals"][0]["proposal_id"].endswith("-2")
    v = act(private, v, "use_proposal")
    v = act(private, v, "adopt")
    assert all(a["timing_origin"] == "AI_PROPOSED" for a in v["adopted"]["activities"])
    assert v["adopted"]["transport"] == "PUBLIC_TRANSIT" and v["adopted"]["walking_allowed"]
    code = """
import sys,socket
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def deny(*a,**kw):raise AssertionError('EXTERNAL_ACCESS')
socket.getaddrinfo=deny;socket.socket.connect=deny
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 assert len(v['adopted']['activities'])==2 and v['references']
 assert v['job']['status']=='PARTIAL' and len(v['job']['decisions'])==2
 assert v['private_budget']['used']['model']==1
 print('PARTIAL_NONEMPTY_RECOVERED_ZERO_ACCESS')
"""
    r = subprocess.run(
        [sys.executable, "-c", code, str(private.db.path), v["session_id"]],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and "PARTIAL_NONEMPTY_RECOVERED_ZERO_ACCESS" in r.stdout


def test_new_grant_does_not_transfer_old_budget_or_bind_old_adopted_trip(private):
    from travel_agent.planning.private_budget import (
        PrivatePlanningBudget,
        IDENTIFIER,
        CURRENT_IDENTIFIER,
        CURRENT_LIMITS,
    )

    old = chosen(private)
    b = PrivatePlanningBudget(private.db)
    b.reserve_for_trip("owner", old["session_id"], "MODEL", "old")
    before = tuple(
        private.db.connection.execute(
            "SELECT * FROM research_continuations WHERE continuation_id=?", (IDENTIFIER,)
        ).fetchone()
    )
    private.db.connection.execute(
        "INSERT INTO research_continuations SELECT ?,account_scope,continuation_id,config_json,created_at,started_at,NULL,?,? FROM research_continuations WHERE continuation_id=?",
        (
            CURRENT_IDENTIFIER,
            json.dumps(CURRENT_LIMITS),
            json.dumps(dict(status="PASS", destination="合成青谷", session_id=None)),
            IDENTIFIER,
        ),
    )
    new = create(private, "合成青谷")
    current = PrivatePlanningBudget.for_trip(private.db, new["session_id"])
    assert current.identifier == CURRENT_IDENTIFIER and current.summary()["used"]["model"] == 0
    current.reserve_for_trip("owner", new["session_id"], "MODEL", "new")
    assert (
        PrivatePlanningBudget.for_trip(private.db, old["session_id"]).summary()["used"]["model"]
        == 1
    )
    assert (
        tuple(
            private.db.connection.execute(
                "SELECT * FROM research_continuations WHERE continuation_id=?", (IDENTIFIER,)
            ).fetchone()
        )
        == before
    )
    another = create(private, "合成青谷")
    with pytest.raises(ValueError):
        current.check_trip("owner", another["session_id"])


def test_arrangement_sends_only_selected_activity_references(private):
    from travel_agent.planning.private_payload import payload

    view = chosen(private)
    _, state = private.load(view["session_id"])
    result = payload(private.db, "owner", view["session_id"], state["planning"])
    needed = {i for a in view["draft"]["activities"] for i in a["evidence_ids"]}
    assert {e["claim_id"] for e in result["references"]} == needed


def test_provider_defers_only_proposal_schema_to_program(monkeypatch):
    from travel_agent.providers.llm import OpenAICompatibleProvider
    from travel_agent.planning.flow_models import ArrangementResponse
    from pydantic import SecretStr

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return self.body[:limit]

    calls = []
    bad = proposal()
    bad["activities"][0]["stay_min"] = "bad"
    raw = dict(protocol_version=2, proposals=[bad, proposal()])

    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data))
            return FakeResponse(
                json.dumps(
                    dict(
                        choices=[dict(finish_reason="stop", message=dict(content=json.dumps(raw)))]
                    )
                ).encode()
            )

    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *a: Opener())
    provider = OpenAICompatibleProvider(
        "https://model.invalid/v1",
        "synthetic",
        SecretStr("fixture"),
        120,
        response_format="json_object",
    )
    result = provider.structured(
        "planning_arrangement_v2", inputs(), ArrangementResponse.model_json_schema()
    )
    assert validate_arrangements(result, inputs())["accepted_count"] == 1 and len(calls) == 1
    assert "program owns transport" in calls[0]["messages"][0]["content"]
    assert '"minimum": 10' in calls[0]["messages"][0]["content"]


@pytest.mark.parametrize("first_review_pending", [False, True])
def test_unknown_first_source_continues_to_matching_second_and_reserves_planning(
    private, first_review_pending
):
    from travel_agent.preview.worker import run_job
    from travel_agent.planning.private_budget import IDENTIFIER, CURRENT_IDENTIFIER, CURRENT_LIMITS
    from travel_agent.research.models import Candidate, DetailMaterial
    from test_workbench_pipeline import Provider, dispatches
    from test_model_context_review import BODY

    private.db.connection.execute(
        "UPDATE research_questions SET request_json=?", ('{"destination":"其他合成区域"}',)
    )
    private.db.connection.execute(
        "INSERT INTO research_continuations SELECT ?,account_scope,continuation_id,config_json,created_at,started_at,NULL,?,? FROM research_continuations WHERE continuation_id=?",
        (
            CURRENT_IDENTIFIER,
            json.dumps(CURRENT_LIMITS),
            json.dumps(dict(status="PASS", destination="合成青谷", session_id=None)),
            IDENTIFIER,
        ),
    )
    v = act(
        private,
        create(private, "合成青谷", request="市区一日，公共交通，10点开始第一项目"),
        "research",
    )

    class Reader:
        text_first = False

        def __init__(self):
            self.details = []

        def connect(self):
            pass

        def search(self, query):
            assert "市区" in query and "公共交通" in query
            return tuple(
                Candidate("xhs:scope-" + s, "合成青谷市区一日路线" + s, "normal", True)
                for s in ["a", "b"]
            )

        def detail(self, c, n):
            self.details.append(n)
            body = (
                BODY
                if n == 1
                else "合成青谷市区一日游计划，还没出发。\n城市活动草案。\nDay1：合成南园→合成北馆。\n我想了解展馆的建筑风格。\n接驳班车每天十点发车。"
            )
            return DetailMaterial(c.source_id, c.title, body, "PARTIAL_TEXT", private.db.stamp())

    class ReviewedProvider(Provider):
        def structured(self, task, data, schema):
            result = super().structured(task, data, schema)
            if (
                first_review_pending
                and task == "review_evidence_context_v2"
                and len(self.calls) == 2
            ):
                for item in result["reviews"]:
                    item["reference_scope"] = "AUTHOR_RECORDED_TRIP"
            return result

    provider = ReviewedProvider()
    reader = Reader()
    extract, review = dispatches(provider)
    run_job(
        private.db.path,
        v["research_job"]["job_id"],
        reader=reader,
        provider=provider,
        extract_dispatch=extract,
        review_dispatch=review,
        product=True,
    )
    view = private.get(v["session_id"])
    assert reader.details == [1, 2] and len(provider.calls) == 4
    assert view["private_budget"]["remaining"]["model"] == 1
    if first_review_pending:
        assert (
            private.db.connection.execute(
                "SELECT count(*) FROM extraction_candidates WHERE context_status='PENDING'"
            ).fetchone()[0]
            >= 1
        )
    view = act(private, view, "adopt_research")
    assert sum(a["spatial_status"] == "MATCH" for a in view["activity_candidates"]) >= 2, view[
        "activity_candidates"
    ]
    assert not view["research_available"]
