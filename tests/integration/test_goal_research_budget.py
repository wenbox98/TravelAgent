# ruff: noqa: F811
"""Default entry costs and multi-source research through production workers/wire."""

from uuid import uuid4
import pytest

from test_goal_agent import service, Wire, intake, choose  # noqa: F401
from automatic_fakes import Model, Reader, config
from test_workbench_pipeline import dispatches
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CONSENT, LEGACY_CONSENT, limits
from travel_agent.planning.automatic_models import AutomaticStart
from travel_agent.planning.conversation import action, ConversationAction
from travel_agent.research.models import Candidate, DetailMaterial
from test_reference_selection import choice
from test_model_context_review import proposal
from test_planning_conversation import conversation, send  # noqa: F401

BODY_A = "我计划秋季自驾，还没出发。\n行程草案。\nDay1：合成青谷→合成镜湖。\n我想在湖边散步和观察湿地鸟类。\n计划在合成镜湖停留两小时。\n计划租车到合成镜湖后再步行。\n计划在合成青谷老城片区住宿以减少搬运行李。"
BODY_B = "去年秋季自驾去了合成青谷。\n旅行记录。\nDay1：合成南园→合成北馆。\n我在展馆参观建筑模型和民俗展陈。\n我在合成北馆停留两小时。\n我乘坐公共交通到合成北馆再步行。\n我住在合成青谷老城片区，前往合成北馆比较方便。"


class MultiModel(Model):
    def structured(self, task, data, schema):
        if task == "select_evidence_references_v1":
            recorded = "去年" in data["spans"][0]["text"]
            role = "AUTHOR_RECORDED_TRIP" if recorded else "AUTHOR_PROPOSED_PLAN"
            return {"claims": [choice(data["spans"], n, (0, 1), topic, kind=role)
                for n, topic in ((2, "ROUTE"), (3, "EXPERIENCE"), (4, "DURATION"), (5, "TRANSPORT"), (6, "TRADEOFF"))]}
        if task == "review_evidence_context_v2":
            role = "AUTHOR_RECORDED_TRIP" if "去年" in data["spans"][0]["text"] else "AUTHOR_PROPOSED_PLAN"
            reviews = []
            for i, c in enumerate(data["candidates"]):
                item = proposal(data, i)
                item.update(reference_scope=role, duration_scope="DAY_SEGMENT" if c["topic"] == "DURATION" else "NONE")
                reviews.append(item)
            return {"reviews": reviews}
        return super().structured(task, data, schema)


class MultiReader(Reader):
    def __init__(self):
        super().__init__()
        self.read_ids = []

    def search(self, query):
        self.calls.append("SEARCH")
        candidates = [Candidate("xhs:" + (self.prefix + str(i).zfill(14)), "无关随手拍" + str(i), "normal", True)
                      for i in range(20)]
        candidates[0] = Candidate(candidates[0].source_id, "合成青谷攻略视频", "video", True)
        candidates[5] = Candidate(candidates[5].source_id, "合成青谷路线行程与游玩", "normal", True)
        candidates[17] = Candidate(candidates[17].source_id, "合成青谷交通住宿片区与游玩", "normal", True)
        candidates[19] = candidates[5]  # repeated metadata cannot become another source
        self.candidates = candidates
        return tuple(candidates)

    def detail(self, candidate, number):
        result = super().detail(candidate, number)
        self.read_ids.append(candidate.source_id)
        return DetailMaterial(candidate.source_id, candidate.title, BODY_A if number == 1 else BODY_B,
                              "PARTIAL_TEXT", result.fetched_at)


def research_then_plan(wire, service, view, reader):
    oracle = MultiModel()

    def respond(task, data):
        if task == "travel_intake_v1":
            text = data["user_text"]
            return intake(text, [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            if data["proposed"]:
                return choose("FINISH", stop="PARTIAL")
            if not data["previous_results"]:
                return choose("RESEARCH_GAP", query="合成青谷 玩法 交通", gap_key="PLAY")
            assert data["previous_results"][-1]["result"]["accepted"] > 0
            return choose("GENERATE")
        return oracle.structured(task, data, {})

    wire.respond = respond
    extract, review = dispatches(config())
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader,
        extract_dispatch=extract, review_dispatch=review)
    return service.plans.get(view["session_id"])


def test_default_followup_cold_gap_can_research_and_offer_new_advice(service, monkeypatch):
    text = "去合成青谷7天"
    wire = Wire(monkeypatch, lambda task, data: intake(text, [("destination", "合成青谷", "合成青谷")])
                if task == "travel_intake_v1" else choose("FINISH", stop="PARTIAL"))
    first = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=Reader())
    first = service.plans.get(first["session_id"])
    view = action(service.db, "owner", first["session_id"], ConversationAction(
        action="submit", text="合成青谷继续查玩法和交通", consent=CONSENT,
        expected_revision=first["revision"],
        expected_conversation_version=first["conversation"]["version"],
    ), str(uuid4()))
    wire.sent.clear()
    reader = MultiReader()
    final = research_then_plan(wire, service, view, reader)
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], [r["task"] for r in wire.sent], wire.errors)
    assert final["job"]["proposals"] and final["job"]["can_preview"]
    assert reader.calls.count("SEARCH") == 1 and reader.calls.count("DETAIL") == 2
    assert final["automatic_task"]["limits"]["model"] == 8
    assert final["automatic_task"]["budget"]["used"]["model"] == 8
    assert [r["task"] for r in wire.sent] == [
        "travel_intake_v1", "travel_supervisor_v1", "select_evidence_references_v1",
        "review_evidence_context_v2", "select_evidence_references_v1", "review_evidence_context_v2",
        "travel_supervisor_v1", "planning_advisory_v4",
    ]
    assert len({r["source_ref"] for r in wire.sent[-2]["input"]["references"]}) == 2
    import subprocess
    import json
    import sys
    from pathlib import Path

    restored = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "helpers/agent_restore.py"),
        str(service.db.path), view["session_id"]], capture_output=True, text=True, encoding="utf8", timeout=30)
    assert restored.returncode == 0, restored.stderr
    state = json.loads(restored.stdout)
    assert state["source_count"] == 2 and state["reference_count"] == 10
    assert state["external_attempts"] == 0 and state["proposals"] > 0
    assert state["remaining_model"] == 0 and state["used_model"] == 8


def test_one_search_reads_multiple_distinct_candidates_then_feedback_and_plan(service, monkeypatch):
    wire = Wire(monkeypatch, lambda *_: None)
    view = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    reader = MultiReader()
    final = research_then_plan(wire, service, view, reader)
    assert reader.calls.count("SEARCH") == 1 and reader.calls.count("DETAIL") > 1, reader.calls
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    assert len(set(reader.read_ids)) == 2
    assert reader.candidates[0].source_id not in reader.read_ids
    assert set(reader.read_ids) == {reader.candidates[i].source_id for i in (5, 17)}
    assert final["automatic_task"]["candidate_count"] == 20
    assert final["automatic_task"]["unique_candidate_count"] == 19
    supervisors = [r["input"] for r in wire.sent if r["task"] == "travel_supervisor_v1"]
    assert len({r["source_ref"] for r in supervisors[1]["references"]}) >= 2
    assert {r["topic"] for r in supervisors[1]["references"]} >= {"ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT", "TRADEOFF"}
    assert supervisors[1]["content_points"] and supervisors[1]["route_options"]
    assert final["reference_overview"]["available"]
    assert final["automatic_task"]["budget"]["used"]["model"] <= final["automatic_task"]["limits"]["model"]


@pytest.mark.parametrize("days,regional,followup,expected", [(None,False,False,13),(1,False,False,13),(7,False,False,18),(1,True,False,18),(7,True,True,8)])
def test_new_contract_costs_cover_all_allowed_body_pairs_and_final_advice(days, regional, followup, expected):
    cap = limits(days, regional, followup=followup)
    assert cap["model"] == expected == 1 + cap["search"] + 2 * cap["detail"] + 1 + 1
    assert cap["model"] <= 20


def test_legacy_page_consent_keeps_five_and_does_not_dispatch_doomed_research(service, monkeypatch):
    from travel_agent.planning.automatic import invalidate
    first = service.start(AutomaticStart(request="合成青谷7天", consent=LEGACY_CONSENT), str(uuid4()))
    invalidate(service.db, first["session_id"])
    first = service.plans.get(first["session_id"])
    v = action(service.db, "owner", first["session_id"], ConversationAction(
        action="submit", text="合成青谷继续查玩法", consent=LEGACY_CONSENT,
        expected_revision=first["revision"], expected_conversation_version=first["conversation"]["version"],
    ), str(uuid4()))
    before = [tuple(r) for r in service.db.connection.execute("SELECT limits_json FROM research_continuations ORDER BY continuation_id")]
    wire = Wire(monkeypatch, lambda task, data: intake(data["user_text"], []) if task == "travel_intake_v1"
                else choose("RESEARCH_GAP", query="合成青谷 玩法", gap_key="PLAY"))
    reader = MultiReader()
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader)
    after = service.plans.get(v["session_id"])
    assert v["automatic_task"]["limits"]["model"] == 5
    assert not wire.sent[1]["input"]["available_tools"]["RESEARCH_GAP"]["allowed"]
    assert reader.calls == [] and len(wire.sent) == 2
    assert before == [tuple(r) for r in service.db.connection.execute("SELECT limits_json FROM research_continuations ORDER BY continuation_id")]
    assert after["automatic_task"]["generated"] is False


def test_last_decision_round_and_low_models_cannot_start_unfinishable_research(service):
    from travel_agent.planning.agent import tools, decision_payload
    from travel_agent.planning.workbench import DailyBudget
    v = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    service.db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (v["automatic_task"]["task_id"],))
    _, state = service.plans.load(v["session_id"])
    p = state["planning"]
    p["agent_understanding"] = {"result": {"intent": "UPDATE"}}
    p["agent_destination_confirmed"] = True
    budget = DailyBudget(service.db, p["operation_grant"])
    p["agent_rounds"] = [{}] * 5
    assert not tools(service.db, "owner", v["session_id"], p, budget, decision_cost=1)["RESEARCH_GAP"]["allowed"]
    p["agent_rounds"] = []
    for i in range(v["automatic_task"]["limits"]["model"] - 3):
        budget.reserve("MODEL", "authored-cost-" + str(i))
    data = decision_payload(service.db, "owner", v["session_id"], p, budget)
    assert data["remaining"]["model"] == 3
    assert not data["available_tools"]["RESEARCH_GAP"]["allowed"]
    # Model can choose GENERATE only when both the decision and generation fit.
    p["draft"]["activities"] = [{"activity_id": "authored-only-for-tool-gate", "name": "合成活动", "provenance": "SYNTHETIC_TEST"}]
    assert data["available_tools"]["GENERATE"]["allowed"] is False
    assert tools(service.db, "owner", v["session_id"], p, budget, decision_cost=1)["GENERATE"]["allowed"]
    p["agent_rounds"] = [{}] * 5
    # Even with ample money, last round must not dispatch a tool requiring another decision.
    assert not tools(service.db, "owner", v["session_id"], p, budget, decision_cost=1)["RESEARCH_GAP"]["allowed"]


@pytest.mark.parametrize("defect", ["EMPTY", "DUPLICATE", "VERIFICATION", "CANCEL"])
def test_failed_duplicate_or_canceled_body_never_adds_coverage_or_retries(service, monkeypatch, defect):
    from travel_agent.research.models import ResearchStopped
    from travel_agent.planning.automatic import invalidate, recover

    class DefectReader(MultiReader):
        def detail(self, candidate, number):
            if defect == "EMPTY" and number == 1:
                self.calls.append("DETAIL")
                return DetailMaterial(candidate.source_id, candidate.title, "", "PARTIAL_TEXT", service.db.stamp())
            if defect == "VERIFICATION" and number == 2:
                self.calls.append("DETAIL")
                raise ResearchStopped("VERIFICATION_REQUIRED")
            result = super().detail(candidate, number)
            if defect == "DUPLICATE" and number == 2:
                return DetailMaterial(candidate.source_id, candidate.title, BODY_A, "PARTIAL_TEXT", result.fetched_at)
            if defect == "CANCEL" and number == 2:
                invalidate(service.db, view["session_id"], "USER_CANCELED")
            return result

    wire = Wire(monkeypatch, lambda *_: None)
    view = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    reader = DefectReader()
    final = research_then_plan(wire, service, view, reader)
    claims = list(service.db.connection.execute("SELECT source_id,topic FROM claims"))
    assert len({r[0] for r in claims}) == 1 and len(claims) == 5
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL", "DETAIL"]
    assert len(set(reader.read_ids)) == len(reader.read_ids)
    assert len([r for r in wire.sent if r["task"] == "select_evidence_references_v1"]) == 1
    assert len([r for r in wire.sent if r["task"] == "review_evidence_context_v2"]) == 1
    if defect in {"VERIFICATION", "CANCEL"}:
        assert not final["automatic_task"]["generated"]
        assert not any(r["task"] == "planning_advisory_v4" for r in wire.sent)
        assert final["automatic_task"]["status"] == ("CANCELED" if defect == "CANCEL" else "PARTIAL")
        if defect == "VERIFICATION":
            assert final["references"]
            assert final["automatic_task"]["reason"] == "RESEARCH_VERIFICATION_REQUIRED"
    else:
        assert final["automatic_task"]["generated"]
        second = [r["input"] for r in wire.sent if r["task"] == "travel_supervisor_v1"][1]
        assert len({r["source_ref"] for r in second["references"]}) == 1
        assert second["previous_results"][-1]["after"]["source_count"] == 1
        if defect == "DUPLICATE":
            assert final["automatic_task"]["duplicate_body_count"] == 1
        else:
            assert final["automatic_task"]["source_skips"][0]["reason"] == "EMPTY_BODY"
    calls = len(wire.sent)
    recover(service.db)
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader)
    assert len(wire.sent) == calls


def test_extra_decisions_reduce_body_batch_before_spending_generation_reserve(service, monkeypatch):
    from travel_agent.planning.automatic import invalidate
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    invalidate(service.db, first["session_id"])
    first = service.plans.get(first["session_id"])
    v = action(service.db, "owner", first["session_id"], ConversationAction(
        action="submit", text="合成青谷补充资料", consent=CONSENT,
        expected_revision=first["revision"], expected_conversation_version=first["conversation"]["version"],
    ), str(uuid4()))
    model = MultiModel()
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [])
        if task == "travel_supervisor_v1":
            n = len(data["previous_results"])
            if n < 2:
                return choose(("CACHE", "DECOMPOSE")[n])
            if n == 2:
                assert data["available_tools"]["RESEARCH_GAP"]["max_body"] == 1
                return choose("RESEARCH_GAP", query="合成青谷 玩法", gap_key="PLAY")
            assert not data["available_tools"]["RESEARCH_GAP"]["allowed"]
            assert data["available_tools"]["GENERATE"]["allowed"]
            return choose("GENERATE")
        return model.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    extract, review = dispatches(config())
    reader = MultiReader()
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader,
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(v["session_id"])
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    assert len(wire.sent) == 8 == final["automatic_task"]["budget"]["used"]["model"]
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL"]


def test_multi_source_feedback_contains_current_selection_exclusion_and_bound_references(conversation, monkeypatch):
    s, v, _, _ = conversation
    selected = v["conversation"]["options"][0]["option_id"]
    v = send(s, v, "select", option_id=selected)
    excluded = v["draft"]["activities"][-1]["activity_id"]
    v = send(s, v, "exclude_activity", activity_id=excluded)
    v = send(s, v, "submit", text="合成青谷补充玩法资料", consent=CONSENT)
    wire = Wire(monkeypatch, lambda *_: None)
    final = research_then_plan(wire, s, v, MultiReader())
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    data = [r["input"] for r in wire.sent if r["task"] == "travel_supervisor_v1"][1]
    assert data["conversation"]["selected"]["option_id"] == selected
    assert excluded in data["conversation"]["excluded_activity_ids"]
    assert len({r["source_ref"] for r in data["references"]}) >= 3
    assert {r["topic"] for r in data["references"]} >= {"ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT", "TRADEOFF"}
    assert data["previous_results"][-1]["result"]["body_count"] == 2
    assert data["content_points"] and data["route_options"]
    assert final["adopted"] is None


def test_empty_failed_candidate_is_skipped_when_later_search_observes_it_again(service, monkeypatch):
    class RepeatedList(MultiReader):
        def search(self, query):
            candidates = list(super().search(query))
            if self.calls.count("SEARCH") == 2:
                candidates[10] = Candidate("xhs:" + self.prefix + "9" * 14,
                    "合成青谷路线行程与游玩", "normal", True)
            return tuple(candidates)

        def detail(self, candidate, number):
            if number == 1:
                self.calls.append("DETAIL")
                self.read_ids.append(candidate.source_id)
                return DetailMaterial(candidate.source_id, candidate.title, "", "PARTIAL_TEXT", service.db.stamp())
            result = super().detail(candidate, number)
            if number == 3:
                return DetailMaterial(candidate.source_id, candidate.title, BODY_A, "PARTIAL_TEXT", result.fetched_at)
            return result

    model = MultiModel()
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            n = len(data["previous_results"])
            if n < 2:
                return choose("RESEARCH_GAP", query="合成青谷 玩法 " + str(n), gap_key=data["research_gaps"][0]["key"])
            return choose("GENERATE")
        return model.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    v = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    reader = RepeatedList()
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader,
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(v["session_id"])
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL", "DETAIL", "SEARCH", "DETAIL"]
    assert len(set(reader.read_ids)) == 3
    assert final["automatic_task"]["budget"]["used"]["model"] == len(wire.sent) == 9
    assert len({r["source_id"] for r in final["references"]}) == 2
