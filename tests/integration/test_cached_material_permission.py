# ruff: noqa: F811
"""Reviewed cache refresh through production workers and permission checks."""

from copy import deepcopy
import json
from uuid import uuid4

import pytest

from test_cached_body_reprocess import cached_trip  # noqa: F401
from test_goal_agent import service, intake, choose  # noqa: F401
from automatic_fakes import config
from travel_agent.knowledge.organize import prepare, commit
from travel_agent.knowledge.planning import templates
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CURRENT_CONSENT
from travel_agent.planning.automatic import save, _cached, _bind_cached_knowledge
from travel_agent.planning.conversation import action, ConversationAction
from travel_agent.planning.workbench import DailyBudget
from travel_agent.planning.suggestions import payload_for


def setup_refresh(cached_trip, text="请仅用已审核资料重新生成，不再搜索或读取新正文。"):
    service, view, wire, oracle = cached_trip
    db, sid = service.db, view["session_id"]
    prepared = prepare(db, "owner", sid, False)
    cards = commit(db, "owner", sid, prepared["preview_hash"], False)["cards"]
    items = [a.model_dump() for c in cards for a in templates(c)]
    assert len(items) > 1
    _, state = service.plans.load(sid)
    p = state["planning"]
    p.update(knowledge_mode=True, knowledge_include_test=False)
    p["draft"]["activities"] = items[:1]
    p.pop("automatic_context_cards", None)
    save(db, sid, state)
    view = service.plans.get(sid)
    created = action(db, "owner", sid, ConversationAction(action="submit",
        text=text, consent=CURRENT_CONSENT,
        expected_revision=view["revision"], expected_conversation_version=view["conversation"]["version"]), str(uuid4()))
    tid = created["automatic_task"]["task_id"]
    gid = db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()[0]
    wire.sent.clear()
    wire.respond = lambda task, data: (intake(data["user_text"], []) if task == "travel_intake_v1"
        else choose("GENERATE") if task == "travel_supervisor_v1" else oracle.structured(task, data, {}))
    return service, sid, tid, gid, wire


@pytest.mark.parametrize("text", [
    "请仅用已审核资料重新生成，不再搜索或读取新正文。",
    "请仅用当前已经审核通过的资料生成预览，不再搜索、不读取新正文、不重新分析缓存正文、不调用地图。",
])
@pytest.mark.parametrize("supervisor_tool", ["GENERATE", "RESEARCH_GAP"])
def test_cache_refresh_generates_with_new_bindings_and_zero_source_operations(cached_trip, text, supervisor_tool):
    service, sid, tid, gid, wire = setup_refresh(cached_trip, text)
    generate_response = wire.respond
    wire.respond = lambda task, data: (choose("RESEARCH_GAP", query="合成青谷 玩法", gap_key="PLAY")
        if task == "travel_supervisor_v1" and supervisor_tool == "RESEARCH_GAP" else generate_response(task, data))
    db = service.db
    old_grants = {r["continuation_id"]: tuple(r) for r in db.connection.execute("SELECT * FROM research_continuations") if r["continuation_id"] != gid}
    before = dict(db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone())
    run(db.path, tid, provider=config())
    final = service.plans.get(sid)
    assert final["automatic_task"]["generated"], (final["automatic_task"], wire.errors)
    planning = [e for e in wire.sent if e["task"].startswith("planning_advisory")]
    assert len(planning) == 1
    original_gate = json.loads(before["gate_json"])
    bindings = planning[0]["input"]["knowledge_bindings"]
    assert any(b not in original_gate["knowledge_bindings"] for b in bindings)
    after = dict(db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone())
    new_gate = json.loads(after["gate_json"])
    assert all(b in new_gate["knowledge_bindings"] for b in bindings)
    assert {k: v for k, v in new_gate.items() if k != "knowledge_bindings"} == {k: v for k, v in original_gate.items() if k != "knowledge_bindings"}
    assert after["limits_json"] == before["limits_json"] and after["finished_at"]
    assert final["automatic_task"]["budget"]["used"]["model"] >= 3
    assert all(final["automatic_task"]["budget"]["used"][k] == 0 for k in ("connect", "search", "detail", "map_place", "map_route"))
    assert all(tuple(r) == old_grants[r["continuation_id"]] for r in db.connection.execute("SELECT * FROM research_continuations") if r["continuation_id"] in old_grants)
    assert not wire.errors


@pytest.mark.parametrize("damage", ["closed", "generation", "scope"])
def test_cache_binding_refresh_cannot_reopen_or_cross_task_scope(cached_trip, damage):
    service, sid, tid, gid, wire = setup_refresh(cached_trip)
    db = service.db
    db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (tid,))
    _, state = service.plans.load(sid)
    p = state["planning"]
    if damage == "closed":
        db.connection.execute("UPDATE research_continuations SET finished_at=? WHERE continuation_id=?", (db.stamp(), gid))
    elif damage == "generation":
        p["automatic_generation"] += 1
        save(db, sid, state, bump=False)
    before = tuple(db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone())
    with pytest.raises(ValueError, match="OPERATION_CLOSED|STALE_PROPOSAL|OPERATION_SCOPE_MISMATCH"):
        _bind_cached_knowledge(db, "another-owner" if damage == "scope" else "owner", sid, p)
    assert tuple(db.connection.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone()) == before
    assert not wire.sent


def test_cache_payload_is_rejected_until_explicit_running_refresh(cached_trip):
    service, sid, tid, gid, _ = setup_refresh(cached_trip)
    db = service.db
    db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (tid,))
    _, state = service.plans.load(sid)
    p = state["planning"]
    before = deepcopy(DailyBudget(db, gid).state())
    _cached(db, "owner", sid, state)
    data = payload_for(p, db, "owner", sid)
    DailyBudget(db, gid).check_payload(data)
    db.connection.execute("UPDATE research_continuations SET gate_json=? WHERE continuation_id=?", (json.dumps(before["gate"]), gid))
    with pytest.raises(ValueError, match="OPERATION_MATERIAL_CHANGED"):
        DailyBudget(db, gid).check_payload(data)
