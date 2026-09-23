"""Synthetic gap and metadata planning; no model or browser calls."""

import json

import pytest

from travel_agent.domain.models import EvidenceBundle
from travel_agent.research.models import Candidate, ResearchRequest
from travel_agent.research.planning import CandidateSelector, QueryPlanner, SufficiencyEvaluator


def bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT"), **changes):
    data = fixture_data("evidence.json")
    template = data["claims"][0]
    texts = {"ROUTE": "合成路线甲沿河", "EXPERIENCE": "作者体验了合成徒步",
             "DURATION": "作者行程共7天", "TRANSPORT": "作者采用自驾"}
    data["claims"] = [{**template, "claim_id": "claim-" + topic, "topic": topic,
                       "text": texts[topic], "confidence": 0.8} for topic in topics]
    data.update(changes)
    return EvidenceBundle(data)


def test_r02_partial_cache_yields_only_missing_coverage_gap(fixture_data):
    gaps = SufficiencyEvaluator().gaps(ResearchRequest(), (
        bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION")),
    ))
    assert [gap.gap_id for gap in gaps] == ["TRANSPORT"]


def test_r03_queries_are_bounded_gap_specific_and_not_repeated(fixture_data):
    request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
    evaluator, planner = SufficiencyEvaluator(), QueryPlanner()
    first = planner.plan(request, (), evaluator.gaps(request, ()), set())
    assert first[0].text == "成都 川西 国庆 攻略" and len(first) <= 3
    evidence = (bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION")),)
    gaps = evaluator.gaps(request, evidence)
    partial = planner.plan(request, evidence, gaps, {" 成都   川西 国庆 攻略 "})
    assert len(partial) == 1 and partial[0].gap_ids == ("TRANSPORT",)
    assert "交通" in partial[0].text and "攻略" not in partial[0].text
    assert planner.plan(request, evidence, gaps, {partial[0].text}) == ()


def test_r04_selector_deduplicates_sources_and_near_identical_titles():
    candidates = (
        Candidate("source-a", "川西路线攻略", "normal", True),
        Candidate("source-a", "川西不同显示标题", "normal", True),
        Candidate("source-b", "川西 路线攻略！", "normal", True),
        Candidate("source-seen", "川西新路线", "normal", True),
        Candidate("source-video", "川西视频路线", "video", True),
        Candidate("source-no-locator", "川西图文路线", "normal", False),
        Candidate("source-other", "合成其他目的地路线", "normal", True),
    )
    choices = CandidateSelector().select(candidates, ResearchRequest(destination="川西"), (), {"source-seen"})
    assert [choice.candidate.source_id for choice in choices] == ["source-a"]
    assert "未读正文" in choices[0].reason
    assert not {"summary", "travel_time", "destination"} & set(choices[0].metadata_used)


@pytest.mark.parametrize("output", [None, {"ids": ["invented-source"]}, {"ids": ["0", "0"]}])
def test_r05_model_failure_or_bad_order_uses_deterministic_fallback(output):
    class Provider:
        def structured(self, *args):
            if output is None:
                raise TimeoutError("synthetic model failure")
            return output
    selector = CandidateSelector(Provider(), allow_external=True)
    candidates = (Candidate("source-a", "川西路线攻略", "normal", True),
                  Candidate("source-b", "川西游玩体验", "normal", True))
    result = selector.select(candidates, ResearchRequest(destination="川西"), (), set())
    assert selector.last_mode == "DETERMINISTIC_FALLBACK"
    assert [choice.candidate.source_id for choice in result] == ["source-a", "source-b"]


def test_optional_model_sees_only_observed_metadata_and_opaque_ids():
    payloads = []
    class Provider:
        def structured(self, task, payload, schema):
            payloads.append(payload)
            return {"ids": ["1", "0"]}
    selector = CandidateSelector(Provider(), allow_external=True)
    result = selector.select((Candidate("private-a", "川西路线攻略", "normal", True),
                              Candidate("private-b", "川西游玩体验", "normal", True)),
                             ResearchRequest(destination="川西"), (), set())
    assert selector.last_mode == "LLM_METADATA_ONLY"
    assert result[0].candidate.source_id == "private-b"
    assert all(set(item) == {"id", "title", "note_type"} for item in payloads[0]["candidates"])
    assert "private-a" not in json.dumps(payloads)


def test_r13_r14_incremental_conditions_preserve_base_coverage_and_add_gaps(fixture_data):
    evidence = (bundle(fixture_data),)
    evaluator = SufficiencyEvaluator()
    assert evaluator.gaps(ResearchRequest(), evidence) == ()
    gaps = evaluator.gaps(ResearchRequest(days=5, no_self_drive=True), evidence)
    assert {gap.gap_id for gap in gaps} == {"DAYS_FIT", "NON_SELF_DRIVE"}
    assert len(evidence[0]["claims"]) == 4


def test_negative_mentions_cannot_prove_five_days_or_non_self_drive_fit(fixture_data):
    data = bundle(fixture_data).to_dict()
    for claim in data["claims"]:
        if claim["topic"] == "DURATION":
            claim["text"] = "作者不建议5天完成"
        elif claim["topic"] == "TRANSPORT":
            claim["text"] = "作者表示没有公共交通也没有班车"
    gaps = SufficiencyEvaluator().gaps(ResearchRequest(days=5, no_self_drive=True), (EvidenceBundle(data),))
    assert {gap.gap_id for gap in gaps} == {"DAYS_FIT", "NON_SELF_DRIVE"}


def test_low_confidence_or_missing_locators_cannot_close_gaps(fixture_data):
    data = bundle(fixture_data).to_dict()
    for claim in data["claims"]:
        claim["confidence"] = 0.25
    assert len(SufficiencyEvaluator().gaps(ResearchRequest(), (EvidenceBundle(data),))) == 4
    for claim in data["claims"]:
        claim.update(confidence=0.9, locator="")
    assert len(SufficiencyEvaluator().gaps(ResearchRequest(), (EvidenceBundle(data),))) == 4


def test_vague_request_leaves_unasked_conditions_unknown():
    request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
    assert request.budget_cny_fen is None and request.transport is None
    assert request.days is None and request.traveler_count is None
