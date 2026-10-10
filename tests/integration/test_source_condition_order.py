"""Reference conditions are exact collections, not priority ordering."""

from copy import deepcopy

import pytest

from travel_agent.planning.advisory import pool, verify_current
from travel_agent.planning.flow_models import PlanDraft
from travel_agent.planning.materials import candidate_from_name, references
from travel_agent.planning.private_payload import payload
from test_daily_workbench import normal as normal_fixture

normal = normal_fixture


def authored(normal, monkeypatch, name, destination, days):
    s, old = normal
    sid = old["session_id"]
    _, state = s.load(sid)
    p = deepcopy(state["planning"])
    original = references(s.db, s.scope, sid)[0]
    rows = [
        dict(original, claim_id=cid, text=name, topic="ROUTE", conditions=[condition])
        for cid, condition in [("z-ref", "作者计划，尚未出发"), ("a-ref", "仅作秋季参考")]
    ]
    monkeypatch.setattr("travel_agent.planning.materials.references", lambda *args: rows)
    monkeypatch.setattr("travel_agent.planning.private_payload.references", lambda *args: rows)
    a = candidate_from_name(name, rows, destination)
    draft = PlanDraft.model_validate(p["draft"])
    draft.activities, draft.days = [a], days
    p.update(runtime_mode="DAILY", knowledge_mode=False, destination=destination,
             draft=draft.model_dump(), activity_pool=[], conversation_model_context={})
    return s, sid, p


@pytest.mark.parametrize("name,destination,days", [
    ("合成青谷", "合成城甲", 1), ("合成山馆", "合成城乙", 3),
])
def test_priority_reordering_keeps_exact_reference_conditions(normal, monkeypatch, name, destination, days):
    s, sid, p = authored(normal, monkeypatch, name, destination, days)
    before = deepcopy(p)
    data = payload(s.db, s.scope, sid, p)
    assert data["activities"][0]["conditions"] == p["draft"]["activities"][0]["conditions"]
    assert pool(s.db, s.scope, sid, p)[0].conditions == p["draft"]["activities"][0]["conditions"]
    verify_current(s.db, s.scope, sid, p)
    assert p == before


@pytest.mark.parametrize("change", ["remove", "rewrite", "add", "duplicate"])
def test_condition_changes_still_reject(normal, monkeypatch, change):
    s, sid, p = authored(normal, monkeypatch, "合成青谷", "合成城甲", 2)
    conditions = p["draft"]["activities"][0]["conditions"]
    if change == "remove":
        conditions.pop()
    elif change == "rewrite":
        conditions[0] = "作者已经完成旅行"
    elif change == "add":
        conditions.append("新条件")
    else:
        conditions.append(conditions[0])
    with pytest.raises(ValueError, match="PLANNING_REFERENCE_UNAVAILABLE"):
        payload(s.db, s.scope, sid, p)
    with pytest.raises(ValueError, match="GUIDE_REFERENCE_UNAVAILABLE"):
        verify_current(s.db, s.scope, sid, p)


def test_new_same_name_reference_does_not_invalidate_existing_bound_subset(normal, monkeypatch):
    s, sid, p = authored(normal, monkeypatch, "合成青谷", "合成城甲", 2)
    from travel_agent.planning import materials

    rows = materials.references(s.db, s.scope, sid)
    old = candidate_from_name("合成青谷", rows[:1], "合成城甲")
    p["draft"]["activities"] = [old.model_dump()]
    before = deepcopy(p)
    assert payload(s.db, s.scope, sid, p)["activities"][0]["evidence_ids"] == old.evidence_ids
    verify_current(s.db, s.scope, sid, p)
    assert p == before
    # A withdrawn original citation cannot be replaced by a same-name newer one.
    monkeypatch.setattr("travel_agent.planning.materials.references", lambda *args: rows[1:])
    with pytest.raises(ValueError, match="GUIDE_REFERENCE_UNAVAILABLE"):
        verify_current(s.db, s.scope, sid, p)
