"""Synthetic DOM/state comparison never asserts that more text is complete."""

import json

import pytest

from travel_agent.research.canonical import canonicalize, evidence_key, normalize_body


def test_q03_normalization_preserves_block_provenance_and_exact_versioned_offsets():
    state = "  Cafe\u0301  路线\r\n\r\n 徒步\t两天  "
    result = canonicalize(state, "Café 路线\n徒步 两天")
    assert result.relation == "EQUAL" and result.origin == "STATE"
    assert result.text == normalize_body(state)
    assert all(result.text[b.start:b.end] == b.text == b.normalized_text for b in result.blocks)
    assert all(b.origin == "STATE" and b.locator.startswith("note-body:v2:STATE:") for b in result.blocks)
    assert [b.block_index for b in result.blocks] == [0, 1]
    assert "路线" not in repr(result) + repr(result.blocks) + json.dumps(result.safe_summary())


@pytest.mark.parametrize("state,dom,origin,relation", [
    ("路线甲", "路线甲\n停留两天", "DOM", "DOM_CONTAINS_STATE"),
    ("路线甲\n停留两天", "路线甲", "STATE", "STATE_CONTAINS_DOM"),
    (None, "路线甲", "DOM", "DOM_ONLY"),
    ("路线甲", None, "STATE", "STATE_ONLY"),
])
def test_q03_contains_selects_one_body_without_upgrading_partial(state, dom, origin, relation):
    result = canonicalize(state, dom)
    assert result.origin == origin and result.relation == relation
    assert result.text == (normalize_body(dom) if origin == "DOM" else normalize_body(state))
    assert result.completeness == "PARTIAL_TEXT" and result.truncation_risk


@pytest.mark.parametrize("dom,relation", [
    ("路线甲沿河出发，停留五天", "OVERLAP"), ("住宿费用八十元", "CONFLICT"),
])
def test_q03_disagreement_keeps_state_without_merging_or_full_claim(dom, relation):
    state = "路线甲沿河出发，停留两天"
    result = canonicalize(state, dom, completeness="FULL_TEXT")
    assert result.relation == relation and result.text == state
    assert result.completeness == "PARTIAL_TEXT" and result.truncation_risk


def test_longer_dom_does_not_inherit_state_full_text_assertion():
    assert canonicalize("路线甲", "路线甲\n停留两天", completeness="FULL_TEXT").completeness == "PARTIAL_TEXT"
    equal = canonicalize("路线甲", "路线甲", completeness="FULL_TEXT")
    assert equal.completeness == "FULL_TEXT" and not equal.truncation_risk


def test_q08_duplicate_key_normalizes_units_without_erasing_opposition():
    assert evidence_key("五天，比较宽松。") == evidence_key("5天比较宽松")
    assert evidence_key("十一天") == evidence_key("11天")
    assert evidence_key("两小时") == evidence_key("2小时")
    assert evidence_key("五天宽松") != evidence_key("五天不宽松")
    assert evidence_key("五天宽松") != evidence_key("五天很赶")
