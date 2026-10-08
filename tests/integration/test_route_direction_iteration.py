"""Synthetic route objects, not destination-specific acceptance branches."""

from copy import deepcopy
from pathlib import Path
import json
import sys
from uuid import uuid4
import pytest
from travel_agent.planning import reference_overview
from travel_agent.planning.conversation import LOOP_CONSENT, submission_intent
from travel_agent.persistence.database import Database
from test_planning_conversation import send
from test_cached_questions_and_overview import AnswerModel


def route_rows():
    rows = []
    for number, title in enumerate(["合成甲区—合成乙区", "合成丙区—合成丁区", "合成戊区—合成己区"]):
        relation = dict(object_quote=title, scope="SEGMENT")
        common = dict(
            source_id="synthetic-one-source",
            source_version="v1",
            conditions=[],
            locator="synthetic-location",
            reference_kind="GUIDE_SUGGESTION",
            review_status="MODEL_CONTEXT_REVIEWED",
            route_association=relation,
        )
        rows.append(dict(common, claim_id=f"route-{number}", topic="ROUTE", text=title))
        rows.append(
            dict(
                common,
                claim_id=f"duration-{number}",
                topic="DURATION",
                text=f"自编第{number + 1}段留两天作参考",
                duration_scope="DAY_SEGMENT",
            )
        )
    rows.append(
        dict(rows[-1], claim_id="unbound-duration", text="未证明对象的三天", route_association=None)
    )
    return rows


def test_one_source_multiple_proven_objects_are_distinct_choices_not_distinct_sources():
    rows = route_rows()
    p = dict(draft=dict(activities=[]))
    data = reference_overview.project(rows, p)
    assert len(data["cards"]) == 3
    assert data["source_count"] == 1
    assert {c["title"] for c in data["cards"]} == {r["text"] for r in rows if r["topic"] == "ROUTE"}
    for c in data["cards"]:
        assert len(c["entries"]) == 2 and c["source_count"] == 1
        assert all(r["route_association"]["object_quote"] == c["title"] for r in c["entries"])
    assert "unbound-duration" not in {r["citation_id"] for c in data["cards"] for r in c["entries"]}


def test_equal_object_text_in_different_sources_does_not_attach_duration():
    rows = route_rows()[:2]
    rows[1]["source_id"] = "different-source"
    data = reference_overview.project(rows, dict(draft=dict(activities=[])))
    assert len(data["cards"]) == 1 and len(data["cards"][0]["entries"]) == 1
    changed = deepcopy(rows)
    changed[0]["route_association"] = None
    assert len(reference_overview.project(changed, dict(draft=dict(activities=[])))["cards"]) == 1


def test_same_named_objects_at_different_locations_are_not_joined_and_changes_expire_choices():
    rows = route_rows()[:2]
    rows[0]["route_association"] = dict(rows[0]["route_association"], object_locator="first")
    rows[1]["route_association"] = dict(rows[1]["route_association"], object_locator="second")
    p = dict(draft=dict(activities=[]))
    card = reference_overview.project(rows, p)["cards"][0]
    assert len(card["entries"]) == 1
    p["selected_reference_overview"] = dict(card, rule_version=reference_overview.VERSION)
    assert reference_overview.choices(rows, p)["selected_reference"]
    rows[0]["source_version"] = "v2"
    assert reference_overview.choices(rows, p)["selected_reference"] is None


@pytest.mark.parametrize(
    "region,days,count", [("合成海区", 3, 1), ("合成山区", 9, 3), ("合成湖区", 12, 5)]
)
def test_objects_and_source_counts_do_not_depend_on_destination_days_or_count(region, days, count):
    rows = []
    for i in range(count):
        pair = deepcopy(route_rows()[:2])
        for j, r in enumerate(pair):
            r.update(claim_id=f"{i}-{j}", source_id="one-authored-source")
            r["route_association"]["object_quote"] = f"{region}自编方向{i}"
        rows.extend(pair)
    p = dict(destination=region, draft=dict(days=days, activities=[]))
    cards = reference_overview.project(rows, p)["cards"]
    assert len(cards) == count and reference_overview.project(rows, p)["source_count"] == 1
    p["selected_reference_overview"] = dict(cards[-1], rule_version=reference_overview.VERSION)
    p["draft"]["days"] = days + 1
    assert (
        reference_overview.choices(rows, p)["selected_reference"]["option_id"]
        == cards[-1]["option_id"]
    )


@pytest.fixture
def route_trip(tmp_path, monkeypatch):
    """Authored local source, strict extraction + review + normal trip creation."""
    from test_candidate_grounding import prepare, candidate, accept
    from travel_agent.research.candidate_review import review_candidates
    from travel_agent.planning.automatic import AutomaticService
    from travel_agent.planning.flow_models import PlanAction, PlanDraft
    from travel_agent.planning.automatic_models import AutomaticStart, AutomaticAction, CONSENT
    from datetime import datetime, timezone

    def clock():
        return datetime.now(timezone.utc)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
    from automatic_fakes import config

    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    lines, rows, decisions = [], [], {}
    for i, name in enumerate(["甲桥片区", "乙林片区", "丙河片区"]):
        start = len(lines)
        lines += [name + "。", f"{name}东园→{name}西馆。", "这一段建议留两天慢逛。"]
        for offset, topic in [(1, "ROUTE"), (2, "DURATION")]:
            rows.append(
                candidate(
                    lines[start + offset],
                    start + offset,
                    topic,
                    [dict(text=lines[start], quote=lines[start], source_block_id=start)],
                )
            )
            rows[-1]["source_block_ids"].append(start)
            decisions[len(rows) - 1] = accept(
                reference_scope="GUIDE_SUGGESTION",
                route_association=dict(
                    object_quote=lines[start], object_block_id=start, scope="SEGMENT"
                ),
                **(dict(duration_scope="DAY_SEGMENT") if topic == "DURATION" else {}),
            )
    with Database(tmp_path / "routes.sqlite3", clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, rows, body="\n".join(lines))
        result = runner.execute(**kwargs)
        review_candidates(
            store, attempt_id=result["attempt_id"], account_scope="owner", decisions=decisions
        )
        s = AutomaticService(db, "owner")
        v = s.start(
            AutomaticStart(destination="合成青谷", request="7天先比较玩法", consent=CONSENT),
            str(uuid4()),
        )
        v = s.action(
            v["session_id"],
            AutomaticAction(action="cancel", expected_revision=v["revision"]),
            str(uuid4()),
        )
        draft = PlanDraft.model_validate(v["draft"])
        draft.activities = []
        v = s.plans.mutate(
            v["session_id"],
            PlanAction(action="save", expected_revision=v["revision"], draft=draft),
            str(uuid4()),
        )
        v = send(s, v, "derive_overview")
        assert len(v["reference_overview"]["current"]["cards"]) == 3
        yield s, v


def test_route_select_exclude_one_send_latest_conditions_and_restore(route_trip):
    from travel_agent.planning import questions

    s, v = route_trip
    cards = v["reference_overview"]["current"]["cards"]
    selected, excluded = cards[:2]
    v = send(s, v, "select_reference", option_id=selected["option_id"])
    v = send(s, v, "exclude_reference", option_id=excluded["option_id"])
    old, key = deepcopy(v), str(uuid4())
    v = send(s, v, "submit", text="只有5天，不想自驾，更新方案", consent=LOOP_CONSENT, key=key)
    assert v["draft"]["days"] == 5 and v["draft"]["driving"] == "NO"
    assert v["reference_overview"]["valid"] and v["reference_overview"]["selected_current"]
    assert v["answer_job"]["status"] == "QUEUED" and v["automatic_task"]["status"] == "CANCELED"
    assert (
        send(s, old, "submit", text="只有5天，不想自驾，更新方案", consent=LOOP_CONSENT, key=key)[
            "answer_job"
        ]
        == v["answer_job"]
    )
    model = AnswerModel()
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    v = s.plans.get(v["session_id"])
    assert len(model.calls) == 1 and v["answer_job"]["status"] == "COMPLETED"
    data = model.calls[0][1]
    assert data["conditions"]["days"] == 5 and data["conditions"]["driving"] == "NO"
    assert data["conversation"]["selected_reference"]["option_id"] == selected["option_id"]
    assert data["conversation"]["excluded_references"][0]["option_id"] == excluded["option_id"]
    assert not set(excluded["bindings"]) & {r["citation_id"] for r in data["references"]}
    assert data["iteration_decision"]["purpose"] == "CACHED_ROUTE_DISCUSSION"
    assert not v["conversation"]["proposed_conditions"].get("days")
    usage = v["operation"]["cumulative_used"]
    v = send(s, v, "restore_reference", option_id=excluded["option_id"])
    v = send(s, v, "clear_reference")
    assert (
        not v["reference_overview"]["selected_current"]
        and not v["reference_overview"]["excluded_current"]
    )
    assert v["operation"]["cumulative_used"] == usage
    with Database(s.db.path, clock=s.db.clock) as db:
        from travel_agent.planning.automatic import recover, AutomaticService

        recover(db)
        restored = AutomaticService(db, "owner").plans.get(v["session_id"])
        assert restored["reference_overview"] == v["reference_overview"]
        assert restored["conversation"] == v["conversation"]


def test_hypothesis_proposal_one_click_confirm_update_and_late_exclusion(route_trip):
    from travel_agent.planning import questions

    s, v = route_trip
    original = deepcopy(v["draft"])
    v = send(s, v, "submit", text="如果只有5天，不自驾会不会太赶？", consent=LOOP_CONSENT)
    assert v["draft"] == original and v["automatic_task"]["status"] == "CANCELED"
    questions.run(s.db.path, v["answer_job"]["job_id"], AnswerModel())
    v = s.plans.get(v["session_id"])
    assert v["draft"] == original and v["conversation"]["proposed_conditions"]["days"] == 5
    v = send(s, v, "confirm_update", consent=LOOP_CONSENT)
    assert v["draft"]["days"] == 5 and v["answer_job"]["status"] == "QUEUED"
    assert v["reference_overview"]["valid"]
    option = v["reference_overview"]["current"]["cards"][0]["option_id"]
    model = AnswerModel(
        lambda: send(s, s.plans.get(v["session_id"]), "exclude_reference", option_id=option)
    )
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    v = s.plans.get(v["session_id"])
    assert v["answer_job"]["status"] == "CANCELED" and len(model.calls) == 1
    assert sum(m.get("origin") == "AI_CACHED_ADVICE" for m in v["conversation"]["messages"]) == 1


def test_explicit_update_research_focus_and_guard_use_current_bound_choices(route_trip):
    from travel_agent.planning.automatic import run_task
    from travel_agent.preview.worker import run_job
    from travel_agent.planning.flow_models import PlanDraft, PlanAction
    from travel_agent.planning.materials import activities
    from travel_agent.planning.suggestions import payload_for

    s, v = route_trip
    cards = v["reference_overview"]["current"]["cards"]
    draft = PlanDraft.model_validate(v["draft"])
    rows = reference_overview.references(
        s.db, "owner", v["session_id"], dict(draft=draft.model_dump())
    )
    candidates = activities(rows, v["destination"])[:2]
    v = s.plans.mutate(
        v["session_id"],
        PlanAction(
            action="use_activities",
            expected_revision=v["revision"],
            activity_ids=[a.activity_id for a in candidates],
        ),
        str(uuid4()),
    )
    v = send(s, v, "derive_overview")
    v = send(s, v, "select_reference", option_id=cards[0]["option_id"])
    v = send(s, v, "exclude_reference", option_id=cards[1]["option_id"])
    v = send(s, v, "submit", text="只有5天，改用公共交通，更新方案", consent=LOOP_CONSENT)
    assert v["draft"]["transport"] == "PUBLIC_TRANSIT" and v["automatic_task"]["status"] == "QUEUED"
    assert (
        v["automatic_task"]["limits"]["search"] == 1 and v["automatic_task"]["limits"]["model"] == 5
    )
    _, state = s.plans.load(v["session_id"])
    data = payload_for(state["planning"], s.db, "owner", v["session_id"])
    assert data["conversation"]["selected_reference"]["option_id"] == cards[0]["option_id"]
    assert not set(cards[1]["bindings"]) & set(data["allowed_citation_ids"])
    captured = []

    def inspect(path, jid):
        request = json.loads(
            s.db.connection.execute(
                "SELECT request_json FROM preview_jobs WHERE job_id=?", (jid,)
            ).fetchone()[0]
        )
        captured.append(request)
        fresh = s.plans.get(v["session_id"])
        send(s, fresh, "clear_reference")

        class Denied:
            def __getattr__(self, name):
                raise AssertionError("STALE_JOB_MUST_NOT_ACCESS_READER")

        run_job(path, jid, reader=Denied(), product=True)

    run_task(s.db.path, v["automatic_task"]["task_id"], research_runner=inspect)
    assert captured and cards[0]["title"] in captured[0]["focus"]
    assert captured[0]["request"]["transport"] == "PUBLIC_TRANSIT"
    assert (
        captured[0]["route_choices"]["excluded_references"][0]["option_id"] == cards[1]["option_id"]
    )


@pytest.mark.parametrize(
    "text,intent",
    [
        ("只有5天、不想自驾，更新方案", "REVISE"),
        ("如果只有3天，不自驾会不会太赶", "QUESTION"),
        ("为什么推荐这条", "QUESTION"),
        ("按当前取舍更新建议", "UPDATE"),
        ("继续补充研究", "RESEARCH"),
    ],
)
def test_primary_server_intent_is_not_destination_specific(text, intent):
    assert submission_intent(text) == intent
