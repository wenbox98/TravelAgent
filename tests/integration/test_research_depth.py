# ruff: noqa: F811
"""Authored input only: complementary research, isolated reviews and local points."""

import json

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.planning import CandidateSelector
from travel_agent.research.models import Candidate, ResearchGap, ResearchRequest
from travel_agent.planning.materials import activities
from travel_agent.planning.automatic import run_task
from travel_agent.research.context_review import reserve_review, run_review
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.store import EvidenceStore
from test_automatic_planning import automatic as automatic_fixture, start  # noqa: F401
from automatic_fakes import Model, Reader, research
from test_workbench_pipeline import Provider, add_source


def reference(text, topic="EXPERIENCE", index="1", **extra):
    return dict(
        claim_id="claim-" + index,
        source_id="source-" + index,
        text=text,
        topic=topic,
        conditions=[],
        reference_kind="GUIDE_SUGGESTION",
        review_status="MODEL_CONTEXT_REVIEWED",
        locator="text:" + index,
        source_version="v1",
        source_title="自编来源",
        **extra,
    )


def test_play_gap_selects_complementary_body_without_requiring_itinerary_title():
    candidates = tuple(
        Candidate(str(i), title, "normal", True)
        for i, title in enumerate(
            [
                "不相关商品",
                "合成远谷七日环线攻略",
                "湖边怎么玩：散步与观鸟",
                "住宿片区选择与取舍",
            ]
        )
    )
    gaps = (
        ResearchGap("PLAY", "玩法", ("EXPERIENCE",)),
        ResearchGap("LODGING", "住宿片区", ("TRADEOFF",)),
    )
    selected = CandidateSelector().select(
        candidates,
        ResearchRequest(destination="合成远谷"),
        gaps,
        set(),
        query_context="合成远谷 玩法 住宿",
    )
    assert {c.candidate.source_id for c in selected[:2]} == {"2", "3"}
    assert all(c.candidate.source_id != "0" for c in selected)


def test_natural_public_names_are_exact_and_negative_or_macro_routes_are_not_places():
    rows = [reference("在合成南园散步看花，再去合成北馆参观展陈。")]
    values = activities(rows, "合成城市")
    assert {a.name for a in values} == {"合成南园", "合成北馆"}
    assert all(a.evidence_ids == ["claim-1"] for a in values)
    assert not activities([reference("不推荐去合成南园散步。")], "合成城市")
    assert not activities([reference("北部大环线", topic="ROUTE")], "合成区域")


def test_one_overlong_review_stays_pending_without_discarding_valid_sibling(tmp_path, clock):
    class Verbose(Provider):
        def structured(self, task, data, schema):
            result = super().structured(task, data, schema)
            if task.startswith("review_"):
                result["reviews"][1]["explanation"] = "说明" * 101
            return result

    with Database(tmp_path / "review.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        attempts = [add_source(store, str(i), Provider()) for i in range(2)]
        budget = BoundedBudget(store, "offline-depth")
        from pydantic import SecretStr
        from travel_agent.providers.llm import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            "http://127.0.0.1", "synthetic", SecretStr("fixture"), 120
        )
        budget.grant("owner", "partial", provider, attempts)
        rid = reserve_review(store, budget, attempts[0], "owner", {}, evaluation=True)
        result = run_review(store, Verbose(), rid)
        assert result["status"] == "COMPLETED"
        assert result["accepted"] == 1 and result["pending"] == 2
        saved = db.connection.execute(
            "SELECT results_json FROM context_review_runs WHERE review_id=?", (rid,)
        ).fetchone()[0]
        entries = json.loads(saved)
        assert entries[1]["proposal"] is None
        assert entries[1]["schema_errors"] == [
            {"path": ["reviews", 0, "explanation"], "validator": "maxLength"}
        ]
        assert "说明" * 101 not in saved


def test_http_200_transport_preserves_valid_review_siblings(tmp_path, clock, monkeypatch):
    from pydantic import SecretStr
    from io import BytesIO as FakeResponse
    from travel_agent.providers.llm import OpenAICompatibleProvider

    requests = []

    class Opener:
        def open(self, request, timeout):
            value = json.loads(request.data)
            requests.append(value)
            data = json.loads(value["messages"][1]["content"])["input"]
            result = Provider().structured("review_evidence_context_v2", data, {})
            result["reviews"][1]["explanation"] = "说明" * 101
            response = FakeResponse(
                json.dumps(
                    dict(
                        choices=[
                            dict(finish_reason="stop", message=dict(content=json.dumps(result)))
                        ]
                    )
                ).encode()
            )
            response.status = 200
            return response

    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    provider = OpenAICompatibleProvider(
        "http://127.0.0.1", "authored", SecretStr("fixture"), 120, "json_object"
    )
    with Database(tmp_path / "transport.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        attempts = [add_source(store, str(i), Provider()) for i in range(2)]
        budget = BoundedBudget(store, "offline-transport")
        budget.grant("owner", "partial", provider, attempts)
        rid = reserve_review(store, budget, attempts[0], "owner", {}, evaluation=True)
        result = run_review(store, provider, rid)
        assert result["status"] == "COMPLETED" and result["accepted"] == 1
        assert result["pending"] == 2 and len(requests) == 1
        assert result["diagnostic"]["http_status"] == 200
        assert "at most 200 characters" in requests[0]["messages"][0]["content"]


def test_source_failure_exposes_already_qualified_material_without_planning_retry(
    automatic_fixture,
):
    from travel_agent.research.models import ResearchStopped

    class Stops(Reader):
        def detail(self, c, n):
            if n == 2:
                self.calls.append("DETAIL")
                raise ResearchStopped("SOURCE_UNAVAILABLE", "IDENTITY_MISMATCH")
            return super().detail(c, n)

    s = automatic_fixture
    v = start(s)
    model, reader = Model(), Stops()
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=lambda *_: pytest.fail("failed research must not invoke planning"),
    )
    v = s.plans.get(v["session_id"])
    assert v["automatic_task"]["status"] == "BLOCKED"
    assert v["automatic_task"]["reason"] == "RESEARCH_IDENTITY_MISMATCH"
    assert v["references"] and v["reference_overview"]["available"]
    assert v["automatic_task"]["accepted_source_count"] == 1
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL", "DETAIL"]
    assert len(model.calls) == 2


def test_qualified_experience_is_a_cited_point_without_fabricating_a_route():
    from travel_agent.planning.reference_overview import project

    p = dict(draft=dict(activities=[]))
    data = project([reference("在合成南园散步看花，可以轻松体验沿岸景色。")], p)
    assert not data["cards"] and data["direction_count"] == 0
    assert len(data["points"]) == 1
    assert data["points"][0]["entries"][0]["citation_id"] == "claim-1"
    assert data["points"][0]["source_count"] == data["source_count"] == 1


@pytest.mark.parametrize(
    "text,names",
    [
        ("我在湖畔公园散步。", ["湖畔公园"]),
        ("推荐去星河展馆看展。", ["星河展馆"]),
        ("在湖畔公园散步，然后去星河展馆看展。", ["湖畔公园", "星河展馆"]),
        ("这篇攻略建议在合成镜湖拍照。", ["合成镜湖"]),
        ("不要在湖畔公园散步。", []),
        ("北部大环线，一天很轻松。", []),
        ("在未命名的地方随便逛逛。", []),
    ],
)
def test_natural_prefix_and_unknown_names(text, names):
    from travel_agent.planning.materials import natural_names

    assert natural_names(text) == names


class DeepReader(Reader):
    def search(self, query):
        self.calls.append("SEARCH")
        return tuple(
            Candidate("xhs:" + (self.prefix + str(i) * 24)[:24], title, "normal", True)
            for i, title in enumerate(
                [
                    "合成青谷游玩路线",
                    "合成青谷湖边玩法",
                    "合成青谷住宿取舍",
                ],
                1,
            )
        )

    def detail(self, candidate, number):
        from datetime import datetime, timezone
        from travel_agent.research.models import DetailMaterial

        self.calls.append("DETAIL")
        pair, experience = {
            "1": ("合成南园→合成北馆", "在合成南园散步看花，再去合成北馆参观展陈。"),
            "2": ("合成镜湖→合成远谷", "在合成镜湖观鸟，再去合成远谷游玩。"),
            "3": ("合成西园→合成东馆", "住宿可优先选择沿湖片区，少搬行李，但离展馆较远。"),
        }[candidate.source_id[-1]]
        body = f"我计划秋季自驾，还没出发。\n行程草案。\nDay1：{pair}。\n{experience}\n景区大巴每天八点发车。"
        return DetailMaterial(
            candidate.source_id,
            candidate.title,
            body,
            "PARTIAL_TEXT",
            datetime.now(timezone.utc).isoformat(),
        )


class DeepModel(Model):
    def structured(self, task, data, schema):
        if task.startswith("review_") or task == "select_evidence_references_v1":
            result = Provider.structured(self, task, data, schema)
            if task == "select_evidence_references_v1":
                if any("住宿" in span["text"] for span in data["spans"]):
                    result["claims"][1]["topic"] = "TRADEOFF"
            return result
        return super().structured(task, data, schema)


def deep_run(s):
    from automatic_fakes import planning

    v = start(s)
    model, reader = DeepModel(), DeepReader()
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    return s.plans.get(v["session_id"]), model, reader


def test_multi_source_points_choice_actual_advisory_payload_and_zero_access_recovery(
    automatic_fixture,
):
    from copy import deepcopy
    from test_planning_conversation import send
    from travel_agent.planning.conversation import freeze_context
    from travel_agent.planning.suggestions import payload_for
    from travel_agent.planning.reference_overview import choices
    from travel_agent.planning.advisory import validate
    from test_advisory_guide import proposal
    from travel_agent.planning.flow import PlanningService

    s = automatic_fixture
    v, model, reader = deep_run(s)
    assert v["job"]["can_preview"] and v["automatic_task"]["new_body_count"] == 3
    points = v["reference_overview"]["projected"]["points"]
    lodging = next(p for p in points if p["topic_label"] == "选择与取舍")
    assert v["reference_overview"]["projected"]["source_count"] == 3
    assert len(v["draft"]["activities"]) >= 4
    used = deepcopy(v["operation"]["cumulative_used"])
    external = (list(model.calls), list(reader.calls))
    old_task = dict(s.db.connection.execute("SELECT * FROM planning_tasks").fetchone())

    def data(view):
        _, state = s.plans.load(view["session_id"])
        p = deepcopy(state["planning"])
        # Same production freeze performed by create_job, never a question payload.
        freeze_context(s.db, "owner", view["session_id"], p)
        return payload_for(p, s.db, "owner", view["session_id"])

    v = send(s, v, "select_point", option_id=lodging["option_id"])
    result = data(v)
    cid = lodging["entries"][0]["citation_id"]
    assert cid in result["allowed_citation_ids"]
    assert any(
        e["claim_id"] == cid and "少搬行李" in e["text"] and e["conditions"]
        for e in result["references"]
    )
    assert result["conversation"]["selected_points"][0]["citation_ids"] == [cid]
    assert result["protocol_version"] == 4 and "selected_points" in result["instructions"]
    # Authored provider outputs must make a real difference and pass the same validator.
    first = proposal(result)["proposals"][0]
    for a in first["activities"]:
        a["day"] = 1
    second = deepcopy(first)
    second.update(title="少选项目，留出休闲", reason="减少活动，保留自由安排。")
    second["activities"] = second["activities"][:2]
    checked = validate(dict(protocol_version=4, proposals=[first, second]), result)
    assert checked["accepted_count"] == 2
    assert len(checked["proposals"][0]["activities"]) != len(checked["proposals"][1]["activities"])
    v = send(s, v, "exclude_point", option_id=lodging["option_id"])
    assert cid not in data(v)["allowed_citation_ids"]
    v = send(s, v, "restore_point", option_id=lodging["option_id"])
    v = send(s, v, "select_point", option_id=lodging["option_id"])
    assert cid in data(v)["allowed_citation_ids"]
    v = send(s, v, "clear_point", option_id=lodging["option_id"])
    assert not data(v)["conversation"]["selected_points"]
    assert v["operation"]["cumulative_used"] == used
    assert external == (model.calls, reader.calls)
    assert dict(s.db.connection.execute("SELECT * FROM planning_tasks").fetchone()) == old_task
    _, state = s.plans.load(v["session_id"])
    stale = deepcopy(state["planning"])
    stale["selected_research_points"] = [
        dict(option_id=lodging["option_id"], rule_version="obsolete", bindings={})
    ]
    from travel_agent.planning.reference_overview import references

    assert not choices(references(s.db, "owner", v["session_id"], stale), stale)["selected_points"]
    with Database(s.db.path) as db:
        restored = PlanningService(db, "owner").get(v["session_id"])
        assert (
            restored["reference_overview"]["projected"]["points"]
            == v["reference_overview"]["projected"]["points"]
        )
        assert restored["operation"]["cumulative_used"] == used


def test_empty_body_skips_once_then_reads_distinct_sources_in_same_budget(automatic_fixture):
    from automatic_fakes import planning

    class EmptyFirst(DeepReader):
        def detail(self, candidate, number):
            if number == 1:
                from travel_agent.research.models import ResearchStopped

                self.calls.append("DETAIL")
                self.failed = candidate.source_id
                raise ResearchStopped("SOURCE_UNAVAILABLE", "EMPTY_BODY", fallback_eligible=True)
            assert candidate.source_id != self.failed
            return super().detail(candidate, number)

    s = automatic_fixture
    v = start(s)
    model, reader = DeepModel(), EmptyFirst()
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    v = s.plans.get(v["session_id"])
    t = v["automatic_task"]
    assert t["status"] == "PARTIAL" and t["generated"]
    assert t["body_attempts"] == 3 and t["new_body_count"] == 2
    assert t["source_skips"] == [
        dict(
            reason="EMPTY_BODY",
            detail_number=1,
            next_action="NEXT_DISTINCT_CANDIDATE_WITHIN_BUDGET",
        )
    ]
    assert reader.calls.count("DETAIL") == 3 and model.calls.count("planning_advisory_v4") == 1
    assert t["budget"]["used"]["detail"] == 3 and t["accepted_source_count"] == 2


def test_region_mention_does_not_count_as_lodging_coverage():
    from travel_agent.research.advisory_coverage import assess

    rows = [reference("这片区域可以轻松散步，沿路看风景。", topic="TRADEOFF")]
    req = ResearchRequest(destination="另一合成城", days=3)
    assert any(g["key"] == "LODGING" for g in assess(rows, req)["gaps"])
    rows.append(
        reference("住宿可以选择沿湖片区，少搬行李，但离场馆较远。", topic="TRADEOFF", index="2")
    )
    assert not any(g["key"] == "LODGING" for g in assess(rows, req)["gaps"])



def test_legacy_failed_owned_research_is_projected_readonly_without_rewriting_history(
    automatic_fixture,
):
    from travel_agent.planning.automatic import save

    s = automatic_fixture
    v, _, _ = deep_run(s)
    sid = v["session_id"]
    # Reproduce the historical missing-attachment defect in this authored DB only.
    _, state = s.plans.load(sid)
    p = state["planning"]
    p["research_ids"] = p["own_research_ids"] = []
    p["reference_overview_history"] = []
    with s.db.transaction():
        save(s.db, sid, state, bump=False)
        s.db.connection.execute(
            "UPDATE preview_jobs SET status='PARTIAL' WHERE job_id=?", (p["research_job_id"],)
        )
        s.db.connection.execute(
            "UPDATE planning_tasks SET status='BLOCKED' WHERE task_id=?", (p["automatic_task_id"],)
        )
    changes = s.db.connection.total_changes
    stored = s.db.connection.execute(
        "SELECT state_json FROM preview_sessions WHERE session_id=?", (sid,)
    ).fetchone()[0]
    result = s.plans.get(sid)
    assert result["automatic_task"]["status"] == "BLOCKED"
    assert result["references"] and result["reference_overview"]["projected"]["points"]
    assert s.db.connection.total_changes == changes
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (sid,)
        ).fetchone()[0]
        == stored
    )


def test_new_plan_dispatch_refreshes_post_research_context_and_selected_text(automatic_fixture):
    from copy import deepcopy
    from test_planning_conversation import send
    from automatic_fakes import planning
    from travel_agent.planning.conversation import LOOP_CONSENT

    captured = []

    class Capture(DeepModel):
        def structured(self, task, data, schema):
            if task == "planning_advisory_v4":
                captured.append(deepcopy(data))
                result = super().structured(task, data, schema)
                if data["conversation"].get("selected_points"):
                    cids = {
                        cid
                        for point in data["conversation"]["selected_points"]
                        for cid in point["citation_ids"]
                    }
                    interest = [
                        a["activity_id"]
                        for a in data["activities"]
                        if set(a["evidence_ids"]) & cids
                    ]
                    for p in result["proposals"]:
                        p["activities"] = (
                            [a for a in p["activities"] if a["activity_id"] in interest]
                            if interest
                            else p["activities"][:2]
                        )
                        p["title"] = "围绕已选兴趣的轻松建议"
                        p["reason"] = "按本次兴趣减少项目，把节奏留给已选内容。"
                return result
            return super().structured(task, data, schema)

    s = automatic_fixture
    v = start(s)
    model, reader = Capture(), DeepReader()
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    assert captured[0]["conversation"]["material_coverage"]["activity_count"] >= 4
    v = s.plans.get(v["session_id"])
    from test_planning_flow import act

    v = act(s.plans, v, "use_proposal")
    v = act(s.plans, v, "adopt")
    adopted = deepcopy(v["adopted"])
    point = next(
        p
        for p in v["reference_overview"]["projected"]["points"]
        if p["topic_label"] == "选择与取舍"
    )
    v = send(s, v, "select_point", option_id=point["option_id"])
    previous = deepcopy(v["job"]["proposals"])
    v = send(s, v, "submit", text="按当前取舍更新建议", consent=LOOP_CONSENT)
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    assert len(captured) == 2
    cid = point["entries"][0]["citation_id"]
    assert any(r["claim_id"] == cid and "少搬行李" in r["text"] for r in captured[-1]["references"])
    assert captured[-1]["conversation"]["selected_points"][0]["citation_ids"] == [cid]
    v = s.plans.get(v["session_id"])
    assert v["job"]["can_preview"]
    assert len(v["job"]["proposals"][0]["activities"]) < len(previous[0]["activities"])
    assert v["automatic_task"]["budget"]["used"]["model"] == 1
    assert v["adopted"] == adopted
    previous_ids = {a["activity_id"] for a in v["job"]["proposals"][0]["activities"]}
    second = next(
        p
        for p in v["reference_overview"]["projected"]["points"]
        if p["topic_label"] == "玩法与看点"
        and any(
            p["entries"][0]["citation_id"] in a["evidence_ids"]
            and a["activity_id"] not in previous_ids
            for a in v["draft"]["activities"]
        )
    )
    v = send(s, v, "exclude_point", option_id=point["option_id"])
    v = send(s, v, "select_point", option_id=second["option_id"])
    v = send(s, v, "submit", text="按当前取舍更新建议", consent=LOOP_CONSENT)
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    assert len(captured) == 3 and cid not in captured[-1]["allowed_citation_ids"]
    v = s.plans.get(v["session_id"])
    assert v["job"]["can_preview"] and v["adopted"] == adopted
    assert {a["activity_id"] for a in v["job"]["proposals"][0]["activities"]} != previous_ids
    assert v["automatic_task"]["budget"]["used"]["model"] == 1
    import subprocess
    import sys

    script = """import sys,json
from pathlib import Path
sys.path.insert(0, 'apps/api')
def deny(event,args):
 if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}: raise AssertionError('OUTBOUND_DENIED')
sys.addaudithook(deny)
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 print(json.dumps(dict(points=len(v['reference_overview']['projected']['points']), selected=v['reference_overview']['selected_points'], used=v['operation']['cumulative_used'], proposals=len(v['job']['proposals']))))
"""
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", script, str(s.db.path), v["session_id"]],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert child.returncode == 0, child.stderr
    restored = json.loads(child.stdout)
    assert restored["selected"] == [second["option_id"]] and restored["proposals"] > 0
    assert restored["used"] == v["operation"]["cumulative_used"] and restored["points"] > 0
