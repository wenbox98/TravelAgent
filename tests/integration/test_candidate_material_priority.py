"""Candidate bounds apply after material quality and lock priority; authored only."""

import pytest
from travel_agent.planning.materials import activities
from travel_agent.planning.automatic import _activities
from travel_agent.planning.flow_models import PlanDraft
from test_research_depth import reference


def authored_rows(count):
    names = ["虚构" + c + "园" for c in "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳"[:count]]
    route = reference("→".join(names), "ROUTE", "route")
    detail = reference("在虚构末馆参观主题展陈，按兴趣决定观看顺序与休息。", index="detail")
    route["source_id"] = detail["source_id"] = "authored-same-source"
    return [route, detail]


@pytest.mark.parametrize("count,region,days", [(12, "合成海港", 2), (16, "合成山谷", 6)])
def test_late_content_is_available_before_bounded_name_only_catalog(count, region, days, monkeypatch):
    rows = authored_rows(count)
    bounded = activities(rows, region)
    assert len(bounded) == 12 and "虚构末馆" in {a.name for a in bounded}
    full = activities(rows, region, limit=None)
    assert len(full) == count + 1
    state = dict(planning=dict(draft=PlanDraft(days=days).model_dump(), destination=region))
    monkeypatch.setattr("travel_agent.planning.materials.references", lambda *a: rows)
    _activities(None, "owner", "authored-trip", state)
    assert state["planning"]["draft"]["days"] == days
    assert "虚构末馆" in {a["name"] for a in state["planning"]["draft"]["activities"]}


def test_late_locked_candidate_is_not_lost_before_automatic_prioritization(monkeypatch):
    rows = authored_rows(16)
    locked = next(a for a in activities(rows, "合成海港", limit=None) if a.name == "虚构巳园")
    locked.locked = True
    draft = PlanDraft(activities=[locked], days=4)
    state = dict(planning=dict(draft=draft.model_dump(), destination="合成海港"))
    monkeypatch.setattr("travel_agent.planning.materials.references", lambda *a: rows)
    _activities(None, "owner", "authored-trip", state)
    selected = state["planning"]["draft"]["activities"]
    assert len(selected) == 12 and selected[0]["activity_id"] == locked.activity_id
    assert selected[0]["locked"]
