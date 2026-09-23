"""Synthetic helper benchmarks: grounding, coverage and source-aware reports."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from travel_agent.research.freshness import assess_freshness
from travel_agent.research.models import Candidate, ResearchGap, ResearchReport, ResearchRequest
from travel_agent.research.planning import CandidateSelector, SufficiencyEvaluator
from travel_agent.research.quality import (
    claim_clusters, evaluate_coverage, evidence_conflicts, has_locator, source_independence,
)
from travel_agent.research.reporting import build_directions, render_material_report

NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)
LOCATOR = "note-body:v2:STATE:" + "a" * 64 + ":chars:0-24"


def claim(cid, topic, text, **changes):
    return {"claim_id": cid, "topic": topic, "text": text, "locator": LOCATOR,
            "support": "SUPPORTED", "kind": "AUTHOR_OPINION", "confidence": 0.6,
            "valid_from": None, "valid_until": None, **changes}


def bundle(source, claims, *, confidence="MEDIUM", travel=None):
    # Helpers operate on Mapping semantics; contract validation has separate tests.
    copied = deepcopy(claims)
    body = "。".join(c["text"] for c in copied)
    prefix = "note-body:v2:STATE:" + sha256(body.encode()).hexdigest() + ":chars:"
    block_locator = prefix + f"0-{len(body)}"
    offset = 0
    for entry in copied:
        if entry["locator"] == LOCATOR:
            entry["locator"] = prefix + f"{offset}-{offset + len(entry['text'])}"
        offset += len(entry["text"]) + 1
    return {"source_id": source, "source_title": "合成来源", "claims": copied,
            "completeness": "PARTIAL_TEXT", "fetched_at": NOW.isoformat(),
            "source_published_at": "2026-09-23T00:00:00+00:00",
            "travel_occurred_at": travel, "missing_fields": [], "is_synthetic": True,
            "claim_metadata": {c["claim_id"]: {
                "confidence_level": confidence, "source_block_ids": [0],
                "block_locators": [block_locator], "body_origin": "STATE",
                "extraction_method": "MOCK", "extraction_basis": "正文直接表达",
                "applicable_conditions": [],
            } for c in copied}}


def coverage_by_question(evidence):
    return {row.question_id: row for row in evaluate_coverage(evidence, now=NOW)}


def test_q09_opposing_duration_claims_remain_distinct_and_unaveraged():
    first = bundle("xhs:a", [claim("a-five", "DURATION", "甲环线五天比较宽松")])
    second = bundle("xhs:b", [claim("b-five", "DURATION", "甲环线5天很赶")])
    conflicts = evidence_conflicts((first, second))
    assert len(conflicts) == 1
    assert set(conflicts[0].claim_ids) == {"a-five", "b-five"}
    assert set(conflicts[0].source_ids) == {"xhs:a", "xhs:b"}
    assert coverage_by_question((first, second))["Q3_DURATION"].status == "PARTIAL"
    assert "五天比较宽松" in first["claims"][0]["text"]
    assert "5天很赶" in second["claims"][0]["text"]
    assert all("适中" not in c["text"] for b in (first, second) for c in b["claims"])


def test_different_duration_conditions_are_not_silently_declared_same_conflict():
    first = bundle("xhs:a", [claim("a-five", "DURATION", "甲环线五天比较宽松")])
    second = bundle("xhs:b", [claim("b-two", "DURATION", "甲环线两天很赶")])
    assert evidence_conflicts((first, second)) == ()


def test_opposing_transport_claims_are_preserved_as_potential_conflict():
    first = bundle("xhs:a", [claim("a-bus", "TRANSPORT", "甲区域没有班车")])
    second = bundle("xhs:b", [claim("b-bus", "TRANSPORT", "甲区域可以乘班车")])
    assert len(evidence_conflicts((first, second))) == 1


def test_q08_different_note_ids_never_claim_confirmed_source_independence():
    first = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线涉及甲谷")])
    second = bundle("xhs:b", [claim("b-route", "ROUTE", "乙区域涉及乙镇")])
    result = source_independence((first, second))
    assert result.distinct_sources == result.group_count == 2
    assert result.confirmed_independent_sources == 0 and result.status == "UNKNOWN"


def test_q07_same_source_repeated_blocks_never_count_as_multiple_sources():
    source = bundle("xhs:a", [claim("a-five", "DURATION", "甲环线五天"),
                              claim("a-5", "DURATION", "甲环线5天")])
    result = source_independence((source, source))
    assert result.distinct_sources == result.group_count == 1
    clusters = claim_clusters((source, source))
    assert len(clusters) == 1
    assert clusters[0].source_ids == ("xhs:a",)
    assert len(clusters[0].claim_ids) == 2
    assert "SOURCE_CORROBORATION" in {g.gap_id for g in SufficiencyEvaluator(lambda: NOW).gaps(
        ResearchRequest(), (source, source),
    )}


def test_shared_claim_cluster_retains_source_lineage_without_independence_upgrade():
    first = bundle("xhs:a", [claim("a-five", "DURATION", "甲环线五天")])
    second = bundle("xhs:b", [claim("b-five", "DURATION", "甲环线5天")])
    cluster = claim_clusters((first, second))[0]
    assert cluster.source_ids == ("xhs:a", "xhs:b")
    assert set(cluster.claim_ids) == {"a-five", "b-five"}
    assert cluster.independence == "UNKNOWN"
    assert source_independence((first, second)).status == "POSSIBLE_REPUBLICATION"


def test_q10_many_weak_claims_produce_partial_coverage_and_explicit_gap():
    evidence = (bundle("xhs:a", [claim(f"a-{i}", "ROUTE", f"合成{i}路线")
                                   for i in range(10)], confidence="LOW"),)
    assert coverage_by_question(evidence)["Q1_ROUTES"].status == "PARTIAL"
    gaps = SufficiencyEvaluator(lambda: NOW).gaps(ResearchRequest(), evidence)
    assert "ROUTES" in {gap.gap_id for gap in gaps}


@pytest.mark.parametrize("locator", [None, "", "note-body:anywhere", LOCATOR[:-4] + "8-2"])
def test_q03_missing_or_invalid_body_locator_never_supports_coverage(locator):
    entry = claim("a-route", "ROUTE", "甲环线", locator=locator)
    assert not has_locator(entry)
    evidence = (bundle("xhs:a", [entry]),)
    assert coverage_by_question(evidence)["Q1_ROUTES"].status == "UNSUPPORTED"
    assert build_directions(evidence, now=NOW) == []


def test_legacy_without_block_metadata_stays_weak_for_coverage():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线")])
    source.pop("claim_metadata")
    assert coverage_by_question((source,))["Q1_ROUTES"].status == "PARTIAL"


def test_freshness_uses_three_different_semantics_instead_of_fixed_30_day_ttl():
    source = bundle("xhs:a", [])
    source["fetched_at"] = (NOW - timedelta(days=31)).isoformat()
    stable = assess_freshness(claim("a-view", "EXPERIENCE", "甲谷可看山景"), source, now=NOW)
    temporal = assess_freshness(claim("a-queue", "TRADEOFF", "国庆曾经排队"), source, now=NOW)
    dynamic = assess_freshness(claim("a-price", "PRICE", "作者票价100元"), source, now=NOW)
    assert stable.category == "STABLE_EXPERIENCE" and stable.status == "USABLE_REFERENCE"
    assert stable.expires_at == (NOW + timedelta(days=149)).isoformat()
    assert temporal.category == "TIME_SENSITIVE" and temporal.status == "CURRENT_UNVERIFIED"
    assert dynamic.category == "HIGHLY_DYNAMIC" and dynamic.status == "CURRENT_UNVERIFIED"
    assert temporal.expires_at is dynamic.expires_at is None


def test_publication_and_fetch_dates_never_become_author_travel_time():
    source = bundle("xhs:a", [claim("a-time", "TRADEOFF", "国庆堵车两小时")])
    freshness = assess_freshness(source["claims"][0], source, now=NOW)
    assert freshness.status == "CURRENT_UNVERIFIED"
    assert source["travel_occurred_at"] is None
    source["travel_occurred_at"] = "2025-10-02T00:00:00+00:00"
    assert assess_freshness(source["claims"][0], source, now=NOW).status == "HISTORICAL"


@pytest.mark.parametrize("topic", ["PRICE", "OPENING", "RESERVATION"])
def test_dynamic_validity_window_alone_does_not_prove_current_verification(topic):
    entry = claim("a-dynamic", topic, "作者提供的历史动态信息",
                  valid_from=(NOW - timedelta(days=2)).isoformat(),
                  valid_until=(NOW + timedelta(days=30)).isoformat())
    result = assess_freshness(entry, bundle("xhs:a", [entry]), now=NOW)
    assert result.category == "HIGHLY_DYNAMIC"
    assert result.status == "CURRENT_UNVERIFIED"


def test_expired_and_future_observations_do_not_support_current_route_coverage():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线")])
    source["fetched_at"] = (NOW - timedelta(days=181)).isoformat()
    assert assess_freshness(source["claims"][0], source, now=NOW).status == "STALE"
    assert coverage_by_question((source,))["Q1_ROUTES"].status == "PARTIAL"
    source["fetched_at"] = (NOW + timedelta(days=1)).isoformat()
    assert assess_freshness(source["claims"][0], source, now=NOW).status == "CURRENT_UNVERIFIED"


def test_q15_directions_only_come_from_routes_and_each_statement_has_lineage():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线：连接甲谷和乙镇"),
                              claim("a-view", "EXPERIENCE", "甲谷有山景"),
                              claim("a-time", "DURATION", "作者体验五天"),
                              claim("a-limit", "TRANSPORT", "作者使用班车")])
    unrelated = bundle("xhs:b", [claim("b-view", "EXPERIENCE", "另有丙湖方向的体验")])
    result = build_directions((source, unrelated), now=NOW)
    assert len(result) == 1 and result[0]["direction"] == "甲环线"
    for field in ("route_evidence", "experiences", "duration_clues", "limitations"):
        assert result[0][field]
        for statement in result[0][field]:
            assert statement["source_id"] == "xhs:a"
            original = next(c for c in source["claims"] if c["claim_id"] == statement["claim_id"])
            assert statement["source_locator"] == original["locator"]
            assert statement["source_block_ids"] == [0]
            assert statement["extraction_method"] == "MOCK"
            assert statement["content_completeness"] == "PARTIAL_TEXT"
            assert statement["travel_time"] is None


def test_no_route_evidence_cannot_be_padded_into_three_directions():
    source = bundle("xhs:a", [claim("a-view", "EXPERIENCE", "甲区域体验不错"),
                              claim("a-time", "DURATION", "五天")])
    assert build_directions((source,), now=NOW) == []


def test_unsupported_route_cannot_become_formal_candidate_direction():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线", support="UNSUPPORTED")])
    assert build_directions((source,), now=NOW) == []


def test_unsupported_experience_cannot_attach_to_valid_route_direction():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线"),
                              claim("a-view", "EXPERIENCE", "猜测体验", support="UNSUPPORTED")])
    assert build_directions((source,), now=NOW)[0]["experiences"] == []


def test_unrelated_blocks_are_not_attached_to_route_by_same_source_alone():
    source = bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线"),
                              claim("a-view", "EXPERIENCE", "另一地区的特殊体验")])
    source["claim_metadata"]["a-view"]["source_block_ids"] = [1]
    # Split the synthetic paragraph into two quote blocks; there are no condition blocks.
    source["claim_metadata"]["a-route"]["block_locators"] = [source["claims"][0]["locator"]]
    source["claim_metadata"]["a-view"]["block_locators"] = [source["claims"][1]["locator"]]
    direction = build_directions((source,), now=NOW)[0]
    assert direction["experiences"] == [] and direction["unknown"]


def test_unknown_budget_and_party_do_not_block_readable_grounded_directions():
    request = ResearchRequest(departure="合成城", destination="合成地区")
    assert request.budget_cny_fen is request.traveler_count is None
    evidence = (bundle("xhs:a", [claim("a-route", "ROUTE", "甲环线：连接甲谷")]),)
    gaps = SufficiencyEvaluator(lambda: NOW).gaps(request, evidence)
    report = ResearchReport("quality-test", 0, "run-local", request, evidence, gaps,
                            "BUDGET_EXHAUSTED", {"search": 0, "detail": 0}, 1,
                            assessed_at=NOW.isoformat())
    rendered = render_material_report(report.material_view())
    assert "甲环线" in rendered and "预算和人数未知不妨碍先看方向" in rendered
    assert "合成 benchmark" in rendered
    assert "xhs:a" in rendered and "a-route" in rendered
    assert all(g.gap_id not in {"BUDGET_REQUIRED", "PARTY_REQUIRED"} for g in gaps)


def test_q12_candidate_selection_diversifies_observed_titles_deterministically():
    candidates = (Candidate("xhs:a", "合成地区五天环线路线攻略", "normal", True),
                  Candidate("xhs:b", "合成地区5天环线路线攻略", "normal", True),
                  Candidate("xhs:c", "合成地区班车公共交通游玩体验", "normal", True))
    selector = CandidateSelector()
    request = ResearchRequest(destination="合成地区")
    selected = selector.select(candidates, request, (), set())
    assert [choice.candidate.source_id for choice in selected[:2]] == ["xhs:a", "xhs:c"]
    assert selector.select(candidates, request, (), set()) == selected
    assert all("summary" not in choice.metadata_used for choice in selected)


def test_q13_invalid_llm_selector_falls_back_without_changing_observed_metadata():
    class BadProvider:
        def __init__(self):
            self.calls = []

        def structured(self, task, payload, schema):
            self.calls.append(deepcopy(payload))
            return {"ids": ["fabricated-source"]}
    provider = BadProvider()
    candidates = (Candidate("xhs:a", "合成地区线路攻略", "normal", True),
                  Candidate("xhs:b", "合成地区班车体验", "normal", True))
    request = ResearchRequest(destination="合成地区")
    baseline = CandidateSelector().select(candidates, request, (), set())
    selector = CandidateSelector(provider, allow_external=True)
    assert selector.select(candidates, request, (), set()) == baseline
    assert selector.last_mode == "DETERMINISTIC_FALLBACK"
    assert all(set(row) == {"id", "title", "note_type"}
               for row in provider.calls[0]["candidates"])


def test_incremental_constraints_remain_gaps_without_mutating_existing_evidence():
    evidence = (bundle("xhs:a", [claim("a-time", "DURATION", "作者自驾五天")]),)
    original = deepcopy(evidence)
    request = ResearchRequest(days=5, no_self_drive=True)
    gaps = SufficiencyEvaluator(lambda: NOW).gaps(request, evidence)
    assert {"DAYS_FIT", "NON_SELF_DRIVE"}.issubset({g.gap_id for g in gaps})
    assert evidence == original


def test_same_title_seen_source_unreadable_and_video_candidates_are_filtered():
    candidates = (Candidate("xhs:a", "合成地区路线", "normal", True),
                  Candidate("xhs:b", "合成地区路线", "normal", True),
                  Candidate("xhs:c", "合成地区交通", "normal", False),
                  Candidate("xhs:d", "合成地区体验", "video", True))
    result = CandidateSelector().select(candidates, ResearchRequest(destination="合成地区"),
                                        (ResearchGap("ROUTES", "缺路线"),), {"xhs:a"})
    assert [choice.candidate.source_id for choice in result] == ["xhs:b"]
