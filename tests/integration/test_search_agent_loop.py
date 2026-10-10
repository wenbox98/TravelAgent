# ruff: noqa: F811
"""Production wire and workers, with authored responses and network denied."""

from copy import deepcopy
from uuid import uuid4
import pytest

from test_goal_agent import service, Wire, intake, choose  # noqa: F401
from test_goal_research_budget import MultiModel, MultiReader
from test_workbench_pipeline import dispatches
from automatic_fakes import config
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CONSENT
from travel_agent.planning.automatic_models import AutomaticStart


@pytest.mark.parametrize("first_body_invalid", [False, True])
def test_invalid_topic_is_isolated_through_http_200_and_valid_siblings_are_reviewed(service, monkeypatch, first_body_invalid):
    oracle = MultiModel()
    body_calls = 0

    def respond(task, data):
        nonlocal body_calls
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            if not data["previous_results"]:
                return choose("RESEARCH_GAP", query="合成青谷 玩法 交通", gap_key="PLAY")
            return choose("GENERATE")
        result = oracle.structured(task, data, {})
        if task == "select_evidence_references_v1":
            body_calls += 1
            bad = deepcopy(result["claims"][0])
            bad["topic"] = "INVALID_TOPIC_AUTHORED"
            if first_body_invalid and body_calls == 1:
                result["claims"] = [bad]
            else:
                result["claims"].append(bad)
        return result

    wire = Wire(monkeypatch, respond)
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=MultiReader(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(first["session_id"])
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    assert final["references"] and all(r["topic"] != "INVALID_TOPIC_AUTHORED" for r in final["references"])
    assert any(r["task"] == "review_evidence_context_v2" for r in wire.sent)
    attempts = service.db.connection.execute("SELECT diagnostic_json FROM extraction_attempts WHERE batch_id=?",
        (final["automatic_task"]["task_id"],)).fetchall()
    # Attempt batches use grants; inspect the actual job's grant, never assert only UI counts.
    if not attempts:
        grant = service.db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?",
            (first["automatic_task"]["task_id"],)).fetchone()[0]
        attempts = service.db.connection.execute("SELECT diagnostic_json FROM extraction_attempts WHERE batch_id=?", (grant,)).fetchall()
    import json
    diagnostics = [json.loads(r[0]) for r in attempts]
    assert diagnostics and all(d["http_status"] == 200 and d["retry_count"] == 0 for d in diagnostics)
    assert all(d["schema_errors"] and d["schema_errors"][0]["path"][-1] == "topic" for d in diagnostics)
    assert body_calls == 2  # A different body succeeds; no replay of the invalid request.


def test_invalid_private_sibling_contaminates_whole_extraction(fixture_data, clock):
    from travel_agent.research.extractor import EvidenceExtractor
    from travel_agent.domain.models import SourcePolicy

    good = dict(topic="ROUTE", kind="AUTHOR_OPINION", claim="路线甲沿河出发", quote="路线甲沿河出发",
        source_block_ids=[0], confidence="HIGH", applicable_conditions=[], extraction_basis="逐字引用合成正文")

    class PrivateResponse:
        is_external = False
        is_mock = True

        def structured(self, *args):
            return {"claims": [good, {"topic": "BAD", "claim": "xsec_token=SECRET_AUTHORED"}]}

    result = EvidenceExtractor(PrivateResponse(), clock=clock, protocol_version=2).extract(
        source_id="synthetic:private-row", source_title="自编资料", body="路线甲沿河出发。",
        completeness="PARTIAL_TEXT", fetched_at="2026-09-22T00:00:00+00:00",
        policy=SourcePolicy(fixture_data("policies.json")["policies"][0]), source_type="SYNTHETIC", allow_fallback=False)
    assert result.mode == "POLICY_BLOCKED" and result.bundle["claims"] == []
    assert result.candidate_rows == () and result.diagnostic.category == "POLICY_BLOCKED"


def test_v5_unbounded_model_counts_and_finite_source_ceilings_are_durable(service):
    from travel_agent.planning.agent_contract import CURRENT_CONSENT
    from travel_agent.planning.workbench import DailyBudget

    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT), str(uuid4()))
    tid = first["automatic_task"]["task_id"]
    task = service.db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
    assert first["automatic_task"]["limits"]["model"] is None
    assert first["automatic_task"]["limits"]["search"] == 5
    assert first["automatic_task"]["limits"]["detail"] == 20
    service.db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (tid,))
    budget = DailyBudget(service.db, task[0])
    for i in range(60):
        budget.reserve("MODEL", f"synthetic-model-{i}")
    for kind, limit in [("SEARCH", 5), ("DETAIL", 20)]:
        for i in range(limit):
            budget.reserve(kind, f"synthetic-{kind}-{i}")
        with pytest.raises(ValueError, match="BUDGET_OR_DUPLICATE"):
            budget.reserve(kind, "synthetic-overflow")
    assert budget.summary()["remaining"]["model"] is None
    assert budget.summary()["used"]["model"] == 60
    with pytest.raises(ValueError, match="BUDGET_OR_DUPLICATE"):
        budget.reserve("MODEL", "synthetic-model-0")


def test_v5_http_workers_research_and_generate_without_null_arithmetic(service, monkeypatch):
    from travel_agent.planning.agent_contract import CURRENT_CONSENT
    oracle = MultiModel()
    errors = []
    from travel_agent.preview.worker import failure_diagnostic
    def diagnose(exc, phase):
        errors.append((type(exc).__name__, str(exc), phase))
        return failure_diagnostic(exc, phase)
    monkeypatch.setattr("travel_agent.preview.worker.failure_diagnostic", diagnose)
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            strategy = data["search_strategy"]
            if strategy["missing_angles"] and data["available_tools"]["RESEARCH_GAP"]["allowed"]:
                recommendation = strategy["recommended"]
                return choose("RESEARCH_GAP", query=recommendation["query"], gap_key=recommendation["gap_key"])
            return choose("GENERATE")
        return oracle.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=MultiReader(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(first["session_id"])
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors, errors)
    assert final["automatic_task"]["budget"]["remaining"]["model"] is None
    assert final["automatic_task"]["budget"]["used"]["model"] >= 8
    rounds = final["automatic_task"]["agent_rounds"]
    researched = [r for r in rounds if r["tool"] == "RESEARCH_GAP"]
    assert {r["search_angle"] for r in researched} == {"DIRECT", "LATERAL"}
    assert len({r["query"] for r in researched}) == len(researched)


def test_v5_progress_crosses_six_rounds_and_no_progress_still_generates(service, monkeypatch):
    from travel_agent.planning.agent_contract import CURRENT_CONSENT
    from travel_agent.research.models import DetailMaterial

    class EvolvingReader(MultiReader):
        searches = 0
        def search(self, query):
            self.searches += 1
            self.prefix = f"{self.searches:010x}"
            return super().search(query)
        def detail(self, candidate, number):
            result = super().detail(candidate, number)
            token = "甲乙丙丁戊"[self.searches - 1]
            body = result.body.replace("合成镜湖", f"合成{token}湖").replace("合成南园", f"合成{token}园").replace("合成北馆", f"合成{token}馆")
            return DetailMaterial(result.source_id, result.title, body, result.completeness, result.fetched_at)

    oracle = MultiModel()
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            n = len(data["previous_results"])
            if n < 5:
                rec = data["search_strategy"]["recommended"]
                return choose("RESEARCH_GAP", query=rec["query"] + f" 方向{n}", gap_key=rec["gap_key"])
            return choose("CACHE" if n == 5 else "DECOMPOSE")
        return oracle.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    reader = EvolvingReader()
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=reader,
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(first["session_id"])
    task = final["automatic_task"]
    assert task["generated"], (task["reason"], wire.errors)
    assert len(task["agent_rounds"]) > 6
    assert task["agent_rounds"][-1]["decision_origin"] == "PROGRAM_NO_PROGRESS_RECOVERY"
    assert reader.searches == task["budget"]["used"]["search"] == 5
    assert task["budget"]["used"]["detail"] <= 20
    assert task["budget"]["used"]["model"] > 20


def test_v5_verification_stops_entire_loop_before_other_requests(service, monkeypatch):
    from travel_agent.planning.agent_contract import CURRENT_CONSENT
    from travel_agent.research.models import ResearchStopped
    class Challenged(MultiReader):
        def search(self, query):
            self.calls.append("SEARCH")
            raise ResearchStopped("VERIFICATION_REQUIRED", "VERIFICATION_REQUIRED")
    wire = Wire(monkeypatch, lambda task, data: intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_intake_v1" else choose("RESEARCH_GAP", query="合成青谷 具体玩法", gap_key="PLAY"))
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT), str(uuid4()))
    reader = Challenged()
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(first["session_id"])
    assert not final["automatic_task"]["generated"]
    assert "VERIFICATION_REQUIRED" in final["automatic_task"]["reason"]
    assert reader.calls == ["CONNECT", "SEARCH"]
    assert [v["task"] for v in wire.sent] == ["travel_intake_v1", "travel_supervisor_v1"]


def test_remaining_gaps_override_premature_generation_with_distinct_queries(service, monkeypatch):
    from travel_agent.planning.agent_contract import CURRENT_CONSENT
    from travel_agent.research.models import DetailMaterial

    class NewSources(MultiReader):
        count = 0
        def search(self, query):
            self.count += 1
            self.prefix = f"{self.count:010x}"
            return super().search(query)
        def detail(self, candidate, number):
            value = super().detail(candidate, number)
            return DetailMaterial(value.source_id, value.title,
                value.body.replace("合成镜湖", "合成" + "甲乙丙丁戊"[self.count-1] + "湖"),
                value.completeness, value.fetched_at)

    oracle = MultiModel()
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            # A model tries to end after every source: the program must check actual gaps.
            return choose("GENERATE")
        return oracle.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    reader = NewSources()
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=reader,
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(first["session_id"])
    assert final["automatic_task"]["generated"], (final["automatic_task"]["reason"], wire.errors)
    researched = [r for r in final["automatic_task"]["agent_rounds"] if r["tool"] == "RESEARCH_GAP"]
    assert len(researched) >= 3 and len({r["query"] for r in researched}) == len(researched)
    assert all(r["decision_origin"] == "MODEL_WITH_GOAL_GUARD" for r in researched)
    assert {r["search_angle"] for r in researched} == {"DIRECT", "LATERAL"}
    assert any(r["gap_key"] == "PLAY_DETAIL" and "湖" in r["query"] for r in researched)


def test_material_pool_keeps_named_play_diversity_and_locked_steps():
    from travel_agent.planning.automatic import material_pool
    class Cards:
        def get(self, ref):
            return dict(sources=[dict(source_id=ref["source"])])
    def activity(name, source="one", locked=False):
        return dict(name=name, activity_id=name, knowledge_refs=[dict(card_id=name, source=source)], locked=locked)
    items = [activity("机场", locked=True), activity("游客中心"), activity("景交车"),
             *[activity(f"合成第{i}园") for i in range(14)], activity("合成北馆", "two")]
    selected = material_pool(items, Cards(), 20)
    assert selected[0]["name"] == "机场" and any(a["name"] == "合成北馆" for a in selected)
    assert not {"游客中心", "景交车"} & {a["name"] for a in selected}
    assert len(selected) == 12


def test_later_play_card_wins_duplicate_name_without_cross_source_attribution(monkeypatch):
    from travel_agent.planning.automatic import material_pool
    from test_research_depth import reference
    rows = [dict(reference("合成青谷公园→合成南馆", "ROUTE", "route"), claim_id="route"),
            dict(reference("在合成青谷公园散步观鸟，按兴趣欣赏沿途景色。", index="play"), claim_id="play")]
    class Cards:
        def get(self, ref):
            return dict(kind="SOURCE_REFERENCE", sources=[dict(source_id="source-" + ref["card_id"])])
    monkeypatch.setattr("travel_agent.knowledge.planning.card_references", lambda cards: rows)
    items = [dict(name="合成青谷公园", activity_id=key, provenance="SOURCE_REFERENCE",
                  knowledge_refs=[dict(card_id=key)], locked=False) for key in ("route", "play")]
    selected = material_pool(items, Cards(), 20)
    assert [a["activity_id"] for a in selected] == ["play"]


def test_generated_day_play_and_lodging_gaps_are_goal_feedback():
    from travel_agent.planning.search_strategy import proposal_gaps
    draft = dict(days=7, trip_budget=dict(lodging_scope="AUTO", nights=None))
    partial = dict(assessment=dict(coverage=dict(missing_days=[5,6]), content_limited=True), lodging=dict(area_ids=[]))
    assert {g["key"] for g in proposal_gaps([partial], draft)} == {"DURATION", "PLAY_DETAIL", "LODGING"}
    complete = dict(assessment=dict(coverage=dict(missing_days=[]), content_limited=False), lodging=dict(area_ids=["authored-area"]))
    assert not proposal_gaps([partial, complete], draft)
    assert "LODGING" not in {g["key"] for g in proposal_gaps([partial], dict(draft, trip_budget=dict(nights=0)))}


def test_diversity_cannot_evict_a_second_reviewed_play_for_route_only_names(monkeypatch):
    from travel_agent.planning.automatic import material_pool
    monkeypatch.setattr("travel_agent.knowledge.planning.card_references", lambda cards: [])
    monkeypatch.setattr("travel_agent.planning.activity_content.content_references", lambda a, refs: ["reviewed"] if a["activity_id"].startswith("play") else [])
    class Cards:
        def get(self, ref):
            return dict(kind="SOURCE_REFERENCE", sources=[dict(source_id=ref["source"])])
    def item(key, source):
        return dict(name="合成" + key + "公园", activity_id=key, knowledge_refs=[dict(card_id=key, source=source)])
    items = [item("playA", "one"), item("playB", "one"), *[item("route" + str(i), str(i)) for i in range(14)]]
    selected = material_pool(items, Cards(), 20)
    assert [a["activity_id"] for a in selected[:2]] == ["playA", "playB"]
    assert len(selected) == 12
