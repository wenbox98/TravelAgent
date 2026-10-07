"""Generic advisory regressions. Authored fixtures; no live data or providers."""

from copy import deepcopy
from uuid import uuid4

import pytest

from travel_agent.planning.advisory import apply, payload, validate
from travel_agent.planning.flow_models import PlanCreate, PlanDraft
from travel_agent.planning.guide_view import project
from travel_agent.planning.guide_models import DiningAdvice
from test_advisory_guide import normal as normal_fixture, proposal, synthetic
from test_planning_flow import act

normal = normal_fixture


@pytest.mark.parametrize("destination", ["成都", "苏州", "海边小城"])
@pytest.mark.parametrize("words,days", [("一日", 1), ("两天一晚", 2), ("十二天", 12)])
def test_request_days_and_relaxed_intent_are_generic(normal, destination, words, days):
    service, _ = normal
    view = service.create(
        PlanCreate(destination=destination, request=f"{destination}{words}，轻松玩，开始时间未定"),
        str(uuid4()),
    )
    assert view["draft"]["days"] == days
    assert view["draft"].get("pace") == "RELAXED"
    assert view["draft"]["inputs"]["activity_start"] is None


def input_and_proposal(service):
    view = synthetic(service)
    _, state = service.load(view["session_id"])
    data = payload(service.db, service.scope, view["session_id"], state["planning"])
    raw = proposal(data)
    return view, state["planning"], data, raw


@pytest.mark.parametrize("days", [2, 3, 5])
def test_first_day_only_is_partial_not_lost(normal, days):
    service, _ = normal
    _, _, data, raw = input_and_proposal(service)
    data["days"] = days
    for activity in raw["proposals"][0]["activities"]:
        activity["day"] = 1
    result = validate(raw, data)
    assert result["accepted_count"] == 1  # Retain independent legal advice.
    assessment = result["proposals"][0].get("assessment", {})
    assert assessment.get("coverage", {}).get("status") == "PARTIAL"
    assert assessment["coverage"]["missing_days"] == list(range(2, days + 1))


def test_payload_does_not_confuse_names_with_play_content(normal):
    service, _ = normal
    _, _, data, _ = input_and_proposal(service)
    assert "material_support" in data and "planning_context" in data
    assert data["planning_context"]["required_days"] == [1, 2]


def test_combination_reassesses_missing_day_without_rewriting_adopted(normal):
    service, _ = normal
    view = act(service, synthetic(service), "adopt")
    original = deepcopy(view["adopted"])
    view = act(service, view, "preview_combination", activity_ids=["guide-a"])
    assert view["adopted"] == original
    assert view["guide_view"].get("assessment", {}).get("coverage", {}).get("missing_days") == [2]
    view = act(service, view, "cancel")
    assert view["draft"] == original
    assert view["guide_view"]["assessment"]["coverage"]["missing_days"] == []


def test_old_reply_projection_is_read_only_and_exposes_missing_day(normal):
    service, _ = normal
    _, state, data, raw = input_and_proposal(service)
    for activity in raw["proposals"][0]["activities"]:
        activity["day"] = 1
    result = validate(raw, data)
    state["draft"] = apply(state, result["proposals"][0])
    original = deepcopy(state)
    output = project(state)
    assert output.get("assessment", {}).get("coverage", {}).get("missing_days") == [2]
    assert state == original


def test_day_removal_cannot_leave_stale_meal_advice(normal):
    service, _ = normal
    view = synthetic(service)
    draft = PlanDraft.model_validate(view["draft"])
    draft.guide.dining = [DiningAdvice(day=2, window="LUNCH", strategy="BETWEEN_ACTIVITIES")]
    # Revalidate the typed authored fixture before submitting the normal action.
    draft = PlanDraft.model_validate(draft.model_dump())
    view = act(service, view, "save", draft=draft)
    view = act(service, view, "preview_combination", activity_ids=["guide-a"])
    assert all(m["day"] != 2 for m in view["guide_view"]["dining"])


def test_meals_do_not_fill_gap_but_intentional_rest_can_keep_meals():
    from travel_agent.planning.guide_assessment import current_dining, for_draft
    from travel_agent.planning.guide_models import GuideDayChoice

    draft = PlanDraft(days=2, planning_mode="ADVISORY")
    draft.guide.dining = [DiningAdvice(day=2, window="LUNCH", strategy="BETWEEN_ACTIVITIES")]
    assert for_draft(draft, [])["coverage"]["missing_days"] == [1, 2]
    assert current_dining(draft) == []
    draft.guide.day_choices = [
        GuideDayChoice(day=2, kind="REST", reason="留给体力恢复，不增加新项目。")
    ]
    assert for_draft(draft, [])["coverage"]["missing_days"] == [1]
    assert current_dining(draft)[0].strategy == "NEAR_SELECTED_AREA"


@pytest.mark.parametrize("text", ["三到五天", "三天或五天", "最多七天", "大概十二天", "天数未定"])
def test_ambiguous_duration_is_not_forced(normal, text):
    service, _ = normal
    view = service.create(PlanCreate(destination="换一个目的地", request=text), str(uuid4()))
    assert view["draft"]["days"] is None


@pytest.mark.parametrize(
    "text,days", [("10月7日出发，玩三天", 3), ("7日出发", None), ("三日轻松游", 3)]
)
def test_calendar_day_is_not_trip_length(text, days):
    from travel_agent.planning.guide_context import from_request

    draft = PlanDraft()
    from_request(draft, text)
    assert draft.days == days


@pytest.mark.parametrize(
    "request_text,days,nights",
    [
        (
            "成都城市里轻松玩一天，交通还没想好，开始时间未定，往返我自己安排。先给我可以怎么玩的建议。",
            1,
            None,
        ),
        (
            "成都周边两天一晚，2个人、1间房，交通还没决定，不要排得太满。先比较怎么玩，再给住宿位置和预算预留建议。",
            2,
            1,
        ),
        ("海岛三日两晚，2个人、1间房，不赶行程", 3, 2),
    ],
)
def test_regression_requests_use_same_normal_parser(normal, request_text, days, nights):
    service, _ = normal
    view = service.create(
        PlanCreate(destination="输入所选目的地", request=request_text), str(uuid4())
    )
    assert view["draft"]["days"] == days
    assert view["draft"]["trip_budget"]["nights"] == nights
    assert view["draft"]["pace"] == "RELAXED"
    assert view["draft"]["transport"] == "UNKNOWN"


@pytest.mark.parametrize("count", [1, 2, 4, 9])
@pytest.mark.parametrize("days", [1, 2, 3, 5])
def test_day_coverage_varies_with_days_and_activity_count(count, days):
    from travel_agent.planning.guide_assessment import assess, materials
    from travel_agent.planning.guide_models import GuideDayChoice

    activities = [
        dict(
            activity_id=f"arbitrary-{i}",
            name=f"任意地点{i}",
            day=i % days + 1,
            provenance="SOURCE_MENTION",
        )
        for i in range(count)
    ]
    support = materials(activities, [])
    result = assess(activities, days, 1, [], support)
    missing = sorted(set(range(1, days + 1)) - {a["day"] for a in activities})
    assert result["coverage"]["missing_days"] == missing
    assert result["content_limited"]  # More names never manufacture usable source content.
    rest = [
        GuideDayChoice(day=d, kind="REST", reason="不增加新项目，留给恢复体力和休息。")
        for d in missing
    ]
    completed = assess(activities, days, 1, rest, support)
    assert completed["coverage"]["status"] == "COVERED"
    assert completed["status"] == "LIMITED_CONTENT"


@pytest.mark.parametrize(
    "kind,reason",
    [
        ("REST", "自由活动"),
        ("REST", "根据实际情况自由活动"),
        ("SELF_ARRANGED", "自行安排，待定"),
        ("GAP", "现有资料只有一天内容，第二天缺口保留"),
    ],
)
def test_empty_labels_cannot_manufacture_coverage(normal, kind, reason):
    service, _ = normal
    _, _, data, raw = input_and_proposal(service)
    for activity in raw["proposals"][0]["activities"]:
        activity["day"] = 1
    raw["proposals"][0]["day_choices"] = [dict(day=2, kind=kind, reason=reason)]
    result = validate(raw, data)
    assert result["accepted_count"] == 1
    assert result["proposals"][0]["assessment"]["coverage"]["missing_days"] == [2]


def test_rest_first_day_is_allowed_without_clock_but_locked_start_survives(normal):
    service, _ = normal
    _, _, data, raw = input_and_proposal(service)
    for activity in raw["proposals"][0]["activities"]:
        activity["day"] = 2
    raw["proposals"][0]["day_choices"] = [
        dict(day=1, kind="REST", reason="留给休息恢复体力，不增加抵达当天的项目。")
    ]
    assert validate(raw, data)["accepted_count"] == 1
    data["first_start"] = "10:00"
    assert validate(raw, data)["accepted_count"] == 0


def test_day_choice_facts_and_ranges_still_checked_independently(normal):
    service, _ = normal
    _, _, data, raw = input_and_proposal(service)
    good = deepcopy(raw["proposals"][0])
    raw["proposals"][0]["day_choices"] = [dict(day=3, kind="REST", reason="留给休息恢复体力")]
    raw["proposals"].append(good)
    result = validate(raw, data)
    assert result["accepted_count"] == result["rejected_count"] == 1
    for a in raw["proposals"][0]["activities"]:
        a["day"] = 1
    raw["proposals"][0]["day_choices"] = [
        dict(day=2, kind="REST", reason="留给休息，酒店已预订，房态充足")
    ]
    result = validate(raw, data)
    assert result["accepted_count"] == result["rejected_count"] == 1
    assert result["decisions"][0]["reason"] == "PLANNING_UNSUPPORTED_FACT"


def test_source_purpose_cannot_be_upgraded_by_name_quantity_or_plan():
    from travel_agent.planning.guide_assessment import materials

    a = dict(
        activity_id="arbitrary",
        name="虚构水边",
        provenance="SOURCE_REFERENCE",
        evidence_ids=["ref"],
    )
    ref = dict(
        claim_id="ref",
        text="虚构水边 → 虚构树林",
        topic="ROUTE",
        reference_kind="AUTHOR_PROPOSED_PLAN",
    )
    assert materials([a], [ref])[0]["level"] == "ROUTE_CONTEXT"
    assert materials([a], [ref])[0]["roles"] == ["AUTHOR_PROPOSED_PLAN"]
    ref.update(text="虚构水边", topic="EXPERIENCE")
    assert materials([a], [ref])[0]["level"] != "CONTENT_REFERENCE"
    ref.update(text="虚构水边 → 未选入的虚构文化广场景观区", topic="EXPERIENCE")
    assert materials([a], [ref])[0]["level"] != "CONTENT_REFERENCE"
    ref.update(text="在虚构水边观察沿岸植物，原作者条件继续保留。", topic="EXPERIENCE")
    assert materials([a], [ref])[0]["level"] == "CONTENT_REFERENCE"
    a["provenance"] = "SOURCE_MENTION"
    assert materials([a], [ref])[0]["level"] == "NAME_ONLY"
    assert materials([a], [ref])[0]["excerpts"] == []
    ref["knowledge_kind"] = "PLAN_PATTERN"
    a["provenance"] = "SOURCE_REFERENCE"
    assert materials([a], [ref])[0]["level"] == "NAME_ONLY"


def test_worker_preview_cancel_adopt_export_and_restart_with_coverage(normal):
    import json
    import subprocess
    import sys
    from travel_agent.planning.suggestions import run_worker
    from travel_agent.planning.guide_view import export
    from test_advisory_guide import GuideModel
    from test_daily_workbench import permit

    service, _ = normal
    view = act(service, permit(service, synthetic(service), 1), "suggest")

    class Model(GuideModel):
        def structured(self, task, data, schema):
            assert data["planning_context"]["required_days"] == [1, 2]
            assert schema["$defs"]["GuideDayChoice"]["properties"]["kind"]["enum"] == [
                "REST",
                "SELF_ARRANGED",
                "GAP",
            ]
            raw = super().structured(task, data, schema)
            for a in raw["proposals"][0]["activities"]:
                a["day"] = 1
            return raw

    model = Model()
    run_worker(service.db.path, view["job"]["job_id"], model)
    view = service.get(view["session_id"])
    assert view["job"]["status"] == "PARTIAL"
    old = deepcopy(view["adopted"])
    view = act(service, view, "use_proposal")
    assert view["guide_view"]["assessment"]["coverage"]["missing_days"] == [2]
    view = act(service, view, "cancel")
    assert view["adopted"] == old
    view = act(service, act(service, view, "use_proposal"), "adopt")
    markdown = export(service.db, service.scope, view["session_id"])["markdown"]
    assert "第 2 天：资料或安排待补" in markdown
    assert model.calls == 1
    # Fresh process only reads the isolated fixture DB; sockets and DNS denied.
    code = """import json,socket,sys
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.guide_view import export
def deny(*a,**k): raise AssertionError("NETWORK_FORBIDDEN")
socket.socket.connect=deny
socket.getaddrinfo=deny
with Database(sys.argv[1]) as db:
 s=PlanningService(db,"owner",daily_workbench=True)
 v=s.get(sys.argv[2])
 print(json.dumps(dict(adopted=v["adopted"],guide=v["guide_view"],markdown=export(db,"owner",sys.argv[2])["markdown"])))
"""
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code, str(service.db.path), view["session_id"]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    restored = json.loads(child.stdout)
    assert restored == dict(adopted=view["adopted"], guide=view["guide_view"], markdown=markdown)
