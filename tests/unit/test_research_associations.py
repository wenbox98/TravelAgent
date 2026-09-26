"""Validated synthetic extraction proves direction and freshness boundaries."""

from datetime import datetime, timezone

import pytest

from travel_agent.domain.models import SourcePolicy
from travel_agent.providers.mock.llm import MockLLMProvider
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.freshness import assess_freshness
from travel_agent.research.models import ResearchRequest
from travel_agent.research.planning import SufficiencyEvaluator
from travel_agent.research.quality import evaluate_coverage
from travel_agent.research.reporting import build_directions

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def output(topic, quote, block=0, **changes):
    return {
        "topic": topic, "kind": "AUTHOR_OPINION", "claim": quote, "quote": quote,
        "source_block_ids": [block], "confidence": "MEDIUM", "applicable_conditions": [],
        "extraction_basis": "合成正文逐字定位", **changes,
    }


def extract(fixture_data, source_id, body, rows):
    provider = MockLLMProvider({"extract_evidence": {"claims": rows}})
    result = EvidenceExtractor(provider, clock=lambda: NOW, protocol_version=2).extract(
        source_id=source_id, source_title="合成材料", body=body,
        completeness="PARTIAL_TEXT", fetched_at=NOW.isoformat(),
        policy=SourcePolicy(fixture_data("policies.json")["policies"][0]),
        source_type="SYNTHETIC",
    )
    assert result.mode == "MOCK" and result.rejected_claims == 0
    assert len(result.bundle["claims"]) == len(rows)
    return result.bundle


def test_explicit_other_direction_wins_over_shared_paragraph(fixture_data):
    source = extract(fixture_data, "synthetic:association-a",
                     "甲环线可到山谷。乙环线需要五天。", [
        output("ROUTE", "甲环线可到山谷"), output("DURATION", "乙环线需要五天"),
    ])
    directions = build_directions((source,), now=NOW)
    assert len(directions) == 1 and directions[0]["direction"] == "甲环线"
    assert directions[0]["duration_clues"] == []


def test_unassociated_topics_do_not_finish_research_for_a_different_direction(fixture_data):
    first = extract(fixture_data, "synthetic:association-a",
                    "甲环线可到山谷。\n甲环线体验徒步。", [
        output("ROUTE", "甲环线可到山谷"), output("EXPERIENCE", "甲环线体验徒步", 1),
    ])
    other = extract(fixture_data, "synthetic:association-b",
                    "乙环线需要五天。\n乙环线可以乘班车。\n旅行日期：2025-10-02", [
        output("DURATION", "乙环线需要五天"), output("TRANSPORT", "乙环线可以乘班车", 1),
    ])
    evidence = (first, other)
    coverage = {row.question_id: row.status for row in evaluate_coverage(evidence, now=NOW)}
    assert coverage["Q1_ROUTES"] == coverage["Q2_EXPERIENCES"] == "SUPPORTED"
    assert coverage["Q3_DURATION"] != "SUPPORTED" and coverage["Q4_LIMITATIONS"] != "SUPPORTED"
    gaps = SufficiencyEvaluator(lambda: NOW).gaps(ResearchRequest(), evidence)
    assert {"DURATION", "TRANSPORT"}.issubset({gap.gap_id for gap in gaps})
    direction = build_directions(evidence, now=NOW)[0]
    assert not direction["duration_clues"] and not direction["limitations"]


def test_future_travel_date_is_not_historical_experience(fixture_data):
    source = extract(fixture_data, "synthetic:future-trip",
                     "甲环线可到山谷。甲环线可以乘班车。\n旅行日期：2027-10-02", [
        output("ROUTE", "甲环线可到山谷"), output("TRANSPORT", "甲环线可以乘班车"),
    ])
    transport = next(claim for claim in source["claims"] if claim["topic"] == "TRANSPORT")
    assessment = assess_freshness(transport, source, now=NOW)
    assert assessment.status == "CURRENT_UNVERIFIED"
    coverage = {row.question_id: row.status for row in evaluate_coverage((source,), now=NOW)}
    assert coverage["Q4_LIMITATIONS"] != "SUPPORTED"


@pytest.mark.parametrize("condition_on", ["route", "experience"])
def test_condition_reference_does_not_masquerade_as_primary_quote_block(fixture_data, condition_on):
    if condition_on == "route":
        body = "甲环线可到山谷。\n仅夏季，湖区能泛舟。"
        route = output("ROUTE", "甲环线可到山谷", source_block_ids=[0, 1], applicable_conditions=[
            {"text": "仅夏季", "quote": "仅夏季", "source_block_id": 1},
        ])
        experience = output("EXPERIENCE", "湖区能泛舟", 1)
    else:
        body = "甲环线可到山谷，仅夏季。\n湖区能泛舟。"
        route = output("ROUTE", "甲环线可到山谷")
        experience = output("EXPERIENCE", "湖区能泛舟", 1, source_block_ids=[1, 0], applicable_conditions=[
            {"text": "仅夏季", "quote": "仅夏季", "source_block_id": 0},
        ])
    source = extract(fixture_data, "synthetic:condition-ref", body, [route, experience])
    direction = build_directions((source,), now=NOW)[0]
    assert direction["experiences"] == []
