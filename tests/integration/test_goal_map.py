# ruff: noqa: F811
"""Agent map bridge uses the existing grant, public identities and real map wrapper."""

from uuid import uuid4
import pytest
from test_critical_map import key_leg  # noqa: F401
from test_planning_conversation import conversation  # noqa: F401
from travel_agent.planning.agent_map import execute, AgentMapAction


def prepare(s, sid, allowed):
    with s.db.transaction():
        s._create(
            sid,
            ["authored-agent-map"],
            str(uuid4()),
            "按当前条件继续",
            followup=True,
            agent=True,
            map_consent=allowed,
        )
        v = s.plans.get(sid)
        s.db.connection.execute(
            "UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?",
            (v["automatic_task"]["task_id"],),
        )
    return s.plans.get(sid)


def body(v):
    return AgentMapAction(
        task_id=v["automatic_task"]["task_id"],
        leg_id=v["critical_map"]["pairs"][0]["leg_id"],
        expected_revision=v["revision"],
    )


def test_map_permission_required_before_queries(key_leg):
    s, v, maps, adapter = key_leg
    v = prepare(s, v["session_id"], False)
    with pytest.raises(ValueError, match="OPERATION_NOT_AUTHORIZED"):
        execute(maps, v["session_id"], body(v), str(uuid4()))
    assert adapter.calls == []


def test_agent_map_keeps_one_grant_and_does_not_auto_confirm_public_places(key_leg):
    s, v, maps, adapter = key_leg
    v = prepare(s, v["session_id"], True)
    _, state = s.plans.load(v["session_id"])
    grant = state["planning"]["operation_grant"]
    key = str(uuid4())
    outcome = execute(maps, v["session_id"], body(v), key)
    assert outcome["status"] == "PUBLIC_PLACE_CONFIRMATION_REQUIRED"
    assert len(adapter.calls) == 2 and all(c[0] == "PLACE" for c in adapter.calls)
    m = maps.get(v["session_id"])
    pair = v["critical_map"]["pairs"][0]
    assert all(not p["confirmed"] for p in m["places"] if p["place_id"] in pair["place_ids"])
    final = s.plans.get(v["session_id"])
    _, state = s.plans.load(v["session_id"])
    assert state["planning"]["operation_grant"] == grant
    assert final["operation"]["current"]["used"]["map_place"] == 2
    assert final["operation"]["current"]["used"]["map_route"] == 0
    execute(maps, v["session_id"], body(final), key)
    assert len(adapter.calls) == 2


def test_stale_map_or_bad_idempotency_key_cannot_dispatch(key_leg):
    s, v, maps, adapter = key_leg
    v = prepare(s, v["session_id"], True)
    b = body(v)
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        execute(maps, v["session_id"], b, "")
    b.expected_revision += 1
    with pytest.raises(ValueError, match="STALE_PROPOSAL"):
        execute(maps, v["session_id"], b, str(uuid4()))
    assert adapter.calls == []
