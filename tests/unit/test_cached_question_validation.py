"""Synthetic question output boundaries; no external calls or source text."""

import pytest
from travel_agent.planning.questions import AnswerRejected, validate


def answer(advice):
    return dict(advice=advice, citation_ids=[], gaps=["交通未知"], intent="QUESTION", proposed_conditions={})


@pytest.mark.parametrize("advice", [
    "不能完全保证交通衔接。", "无法据此保证当前开放。", "不构成未来可行性的保证。",
    "不保证开放；这里只比较两个片区。",
])
def test_precise_negative_guarantees_are_valid_disclaimers(advice):
    assert validate(answer(advice), {"references": []}).advice == advice


@pytest.mark.parametrize("advice,category", [
    ("不能完全保证开放，但保证交通可行。", "GUARANTEED_FACT"),
    ("不保证开放，肯定不会晚点。", "GUARANTEED_FACT"),
    ("详见https://example.invalid", "URL"),
    ("从合成路123号出发。", "PRIVATE_ADDRESS"),
    ("api_key=SECRET", "SENSITIVE"),
])
def test_rejection_diagnostic_names_field_and_rule_without_echoing_content(advice, category):
    with pytest.raises(AnswerRejected) as caught:
        validate(answer(advice), {"references": []})
    assert caught.value.failure == dict(field="advice", category=category, rule_version="cached-question-1.1")
    assert advice not in repr(caught.value.failure)
