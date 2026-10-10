"""Exact delimiter recovery from verified card text; never mutate old knowledge."""

from copy import deepcopy

import pytest

from travel_agent.knowledge.planning import templates
from travel_agent.planning.materials import activities


@pytest.mark.parametrize("destination", ["北方某省", "南方某城"])
def test_research_query_keeps_destination_and_sensitive_argument_fences(destination):
    from travel_agent.planning.agent import research_query

    value = research_query(destination, "公开公园 玩法 住宿落脚", "LODGING", {"LODGING"})
    assert value == destination + " 公开公园 玩法 住宿落脚"
    assert research_query(destination, value, "LODGING", {"LODGING"}) == value
    for query, gap in [
        ("", "LODGING"),
        ("公园", "PLAY"),
        ("某小区私址", "LODGING"),
        ("https://example.com", "LODGING"),
        ("甲路12号", "LODGING"),
    ]:
        with pytest.raises(ValueError, match="AGENT_INVALID_RESEARCH_ARGUMENT"):
            research_query(destination, query, gap, {"LODGING"})


def test_explicit_body_cap_only_recognizes_current_asserted_limit():
    from travel_agent.planning.agent import requested_body_cap

    assert requested_body_cap("先用缓存。本次最多读取1篇新正文，随后生成建议。") == 1
    assert requested_body_cap("这次最多阅读2篇新资料") == 2
    assert requested_body_cap("不要最多读取1篇新正文") is None
    assert requested_body_cap("如果最多读取1篇新正文会怎样") is None


@pytest.mark.parametrize("arrow", ["→", "➝", "➞", "➔", "➡", "->"])
@pytest.mark.parametrize("names", [["甲木公园", "乙桥街"], ["蓝湖", "南岚镇", "松峰"]])
def test_route_delimiters_keep_exact_names_and_original_evidence(arrow, names):
    ref = dict(
        claim_id="accepted-route",
        topic="ROUTE",
        text=arrow.join(names),
        conditions=["作者攻略整理；冬季适用未知"],
        reference_kind="GUIDE_SUGGESTION",
    )
    result = activities([ref], "不同目的地")
    assert [a.name for a in result] == names
    assert all(a.evidence_ids == ["accepted-route"] for a in result)
    card = dict(
        card_id="card-" + "b" * 28,
        version=1,
        card_hash="a" * 64,
        kind="SOURCE_REFERENCE",
        destination="不同目的地",
        spatial_status="UNKNOWN",
        review_scope="GUIDE_SUGGESTION",
        conditions=ref["conditions"],
        text=ref["text"],
        tags=["ROUTE"],
        activities=[],
        entities=[],
    )
    before = deepcopy(card)
    selected = templates(card)
    assert [a.name for a in selected] == names
    assert all(a.knowledge_refs[0].card_hash == card["card_hash"] for a in selected)
    assert card == before
    card["kind"] = "PLAN_PATTERN"
    assert templates(card) == []


def test_only_proven_added_alias_keeps_route_selection():
    from travel_agent.planning.reference_overview import project, choices

    r = dict(
        claim_id="route",
        source_id="public-source",
        source_version="v1",
        locator="v1:chars:0-9",
        topic="ROUTE",
        text="甲木公园→乙桥街",
        conditions=["雨天未知"],
        reference_kind="GUIDE_SUGGESTION",
        review_status="MODEL_CONTEXT_REVIEWED",
    )
    base = dict(draft=dict(activities=[]))
    card = project([r], base)["cards"][0]
    state = dict(base, selected_reference_overview=dict(card, rule_version="local-route-overview-3"))
    alias = dict(r, claim_id="card-alias", knowledge_kind="SOURCE_REFERENCE")
    assert choices([r, alias], state)["selected_reference"]
    for change in (
        dict(conditions=["雨天推荐"]),
        dict(source_version="v2"),
        dict(locator="v1:chars:10-19"),
    ):
        selected = choices([r, dict(alias, **change)], state)["selected_reference"]
        # A separate object may coexist without invalidating the unchanged
        # selection, but it must never be adopted as its citation alias.
        assert selected is None or set(selected["bindings"]) == {"route"}
    assert choices([dict(r, text="甲木公园→南岚镇")], state)["selected_reference"] is None
