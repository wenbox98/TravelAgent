"""Current-job card refresh and explicit finite-scope continuation; no network."""
# ruff: noqa: F811
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from test_knowledge_library import normal, organize, new  # noqa: F401
from test_goal_agent import service, Wire, intake, choose  # noqa: F401
from test_goal_research_budget import MultiModel, MultiReader
from test_workbench_pipeline import dispatches
from automatic_fakes import config
from travel_agent.knowledge.store import Library, binding
from travel_agent.planning.automatic import merge_research
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CURRENT_CONSENT
from travel_agent.planning.automatic_models import AutomaticStart, AutomaticAction
from travel_agent.planning.workbench import DailyBudget


@pytest.mark.parametrize("boundary", ["unlocked", "locked", "unrelated", "deleted", "cached_projection"])
def test_current_research_can_refresh_only_unlocked_valid_source_bindings(normal, monkeypatch, boundary):
    s, old = normal
    cards = organize(s, old)
    first = cards[0]
    view = new(s, [first])
    _, state = s.load(view["session_id"])
    p = state["planning"]
    p["draft"]["activities"][0].update(day=1, stay_min=35, stay_max=80, locked=boundary == "locked")
    original_adopted = deepcopy(s.get(old["session_id"])["adopted"])
    rid = s.db.connection.execute(
        "SELECT r.research_id FROM research_runs r JOIN research_run_contents rc USING(run_id) "
        "JOIN source_contents c USING(content_id) WHERE c.source_id=? LIMIT 1", (first["sources"][0]["source_id"],)
    ).fetchone()[0]
    data = {k: deepcopy(v) for k, v in first.items() if k not in {
        "card_id", "version", "card_hash", "raw_availability", "raw_retention", "validation_basis"}}
    if boundary == "cached_projection":
        data["activities"][0]["conditions"] = [*data["activities"][0].get("conditions", []), "保留原引用条件"]
    else:
        data["unknowns"].append("本轮整理更新的未知条件")
    newer = Library(s.db, s.scope).save("evidence:" + first["evidence_links"][0], data)
    assert newer["version"] == first["version"] + 1
    search = Library.search
    # The suite's authored catalog is explicitly selected, never real source data.
    monkeypatch.setattr(Library, "search", lambda self, *args, **kw: search(self, *args, **dict(kw, include_test=True)))
    if boundary == "deleted":
        Library(s.db, s.scope).remove([binding(newer)])
    if boundary in {"locked", "unrelated", "deleted"}:
        reason = "PLANNING_LOCKED_CONSTRAINT" if boundary == "locked" else "KNOWLEDGE_STALE_OR_DELETED"
        with pytest.raises(ValueError, match=reason):
            merge_research(s.db, s.scope, view["session_id"], state,
                           "authored-unrelated-job" if boundary == "unrelated" else rid, update_grant=False)
    else:
        merge_research(s.db, s.scope, view["session_id"], state,
                       "authored-cache-reprojection-job" if boundary == "cached_projection" else rid, update_grant=False)
        activity = next(a for a in p["draft"]["activities"] if a["name"] == view["draft"]["activities"][0]["name"])
        assert activity["knowledge_refs"] == [binding(newer)]
        assert (activity["stay_min"], activity["stay_max"]) == (35, 80)
        assert p["automatic_material_refreshes"][-1]["research_id"] == (
            "authored-cache-reprojection-job" if boundary == "cached_projection" else rid)
    assert s.get(old["session_id"])["adopted"] == original_adopted
    with pytest.raises(ValueError, match="KNOWLEDGE_STALE_OR_DELETED"):
        Library(s.db, s.scope).get(binding(first))  # Strict global stale check is retained.


@pytest.mark.parametrize("with_map", [False, True])
def test_explicit_merge_repair_reuses_saved_child_and_only_remaining_scope(service, monkeypatch, with_map):
    monkeypatch.setenv("AMAP_WEB_SERVICE_KEY", "authored-map-key")
    oracle = MultiModel()
    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷")])
        if task == "travel_supervisor_v1":
            return choose("RESEARCH_GAP", query="合成青谷 具体玩法", gap_key="PLAY")
        return oracle.structured(task, data, {})
    wire = Wire(monkeypatch, respond)
    first = service.start(AutomaticStart(request="合成青谷7天", consent=CURRENT_CONSENT,
        map_consent="PRIVATE_KEY_LEG_V1" if with_map else None), str(uuid4()))
    tid = first["automatic_task"]["task_id"]
    gid = service.db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()[0]
    def fail_merge(*args, **kwargs):
        raise ValueError("KNOWLEDGE_STALE_OR_DELETED")
    monkeypatch.setattr("travel_agent.planning.automatic.merge_research", fail_merge)
    extract, review = dispatches(config())
    run(service.db.path, tid, provider=config(), reader=MultiReader(), extract_dispatch=extract, review_dispatch=review)
    failed = service.plans.get(first["session_id"])
    assert failed["automatic_task"]["reason"] == "KNOWLEDGE_STALE_OR_DELETED", wire.errors
    original_grant = tuple(service.db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone())
    original_ops = [tuple(r) for r in service.db.connection.execute("SELECT * FROM continuation_operations WHERE continuation_id=?", (gid,))]
    remaining = DailyBudget(service.db, gid).summary()["remaining"]
    sent = len(wire.sent)
    monkeypatch.setattr("travel_agent.planning.automatic.merge_research", merge_research)
    key = str(uuid4())
    body = AutomaticAction(action="research_more", consent=CURRENT_CONSENT, expected_revision=failed["revision"])
    resumed = service.action(first["session_id"], body, key)
    new_task = service.db.connection.execute("SELECT * FROM planning_tasks WHERE task_id=?", (resumed["automatic_task"]["task_id"],)).fetchone()
    assert new_task["task_id"] != tid and len(wire.sent) == sent
    budget = DailyBudget(service.db, new_task["grant_id"])
    for name in ("search", "detail", "model", "map_place", "map_route"):
        assert json.loads(new_task["request_json"])["limits"][name] == remaining[name]
    assert budget.state()["predecessor"] == gid
    assert budget.state()["gate"]["expires_at"] == json.loads(original_grant[-1])["expires_at"]
    assert tuple(service.db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone()) == original_grant
    assert [tuple(r) for r in service.db.connection.execute("SELECT * FROM continuation_operations WHERE continuation_id=?", (gid,))] == original_ops
    _, state = service.plans.load(first["session_id"])
    recovered = state["planning"]["agent_rounds"][-1]
    assert recovered["decision_origin"] == "LOCAL_MERGE_RECOVERY" and recovered["result"]["search_count"] == 1
    assert state["planning"]["agent_research_job_ids"] == []
    assert service.action(first["session_id"], body, key)["automatic_task"]["task_id"] == new_task["task_id"]
    assert len(wire.sent) == sent
