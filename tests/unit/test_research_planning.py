"""Synthetic gap and metadata planning; no model or browser calls."""

import json
from datetime import datetime, timezone

import pytest

from travel_agent.domain.models import EvidenceBundle
from travel_agent.research.canonical import body_blocks
from travel_agent.research.models import Candidate, ResearchRequest
from travel_agent.research.planning import CandidateSelector, QueryPlanner, SufficiencyEvaluator


NOW = datetime(2026, 9, 24, tzinfo=timezone.utc)


def evaluator():
    return SufficiencyEvaluator(lambda: NOW)


def bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT"),
           *, variant="甲", text_changes=None, **changes):
    data = fixture_data("evidence.json")
    template = data["claims"][0]
    texts = ({"ROUTE": "合成路线甲沿河", "EXPERIENCE": "作者体验了合成徒步",
              "DURATION": "作者行程共7天", "TRANSPORT": "作者采用自驾"} if variant == "甲" else
             {"ROUTE": "合成乙区域环湖", "EXPERIENCE": "另一作者泡合成温泉",
              "DURATION": "另一作者停留4天", "TRANSPORT": "另一作者乘合成班车"})
    texts.update(text_changes or {})
    texts = {topic: f"{variant}环线：{text}" for topic, text in texts.items()}
    data["source_id"] = "synthetic-" + ("a" if variant == "甲" else "b")
    blocks = body_blocks("\n".join(texts[topic] for topic in topics), origin="STATE", normalized=True)
    data["claims"] = [{**template, "claim_id": data["source_id"] + "-" + topic, "topic": topic,
                       "source_id": data["source_id"], "locator": blocks[i].locator,
                       "text": texts[topic], "confidence": 0.6} for i, topic in enumerate(topics)]
    data["claim_metadata"] = {c["claim_id"]: {
        "source_block_ids": [i], "body_origin": "STATE", "extraction_method": "MOCK",
        "confidence_level": "MEDIUM", "extraction_basis": "合成正文逐字表达",
        "applicable_conditions": [], "canonical_relation": "STATE_ONLY", "truncation_risk": True,
        "block_locators": [c["locator"]],
    } for i, c in enumerate(data["claims"])}
    data["travel_occurred_at"] = "2026-09-20T00:00:00+00:00"
    data["missing_fields"] = []
    data.update(changes)
    return EvidenceBundle(data)


def test_r02_partial_cache_yields_only_missing_coverage_gap(fixture_data):
    gaps = evaluator().gaps(ResearchRequest(), (
        bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION")),
        bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION"), variant="乙"),
    ))
    assert [gap.gap_id for gap in gaps] == ["TRANSPORT", "DIRECTION_ASSOCIATION"]


def test_r03_queries_are_bounded_gap_specific_and_not_repeated(fixture_data):
    request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
    assessor, planner = evaluator(), QueryPlanner()
    first = planner.plan(request, (), assessor.gaps(request, ()), set())
    assert first[0].text == "成都 川西 国庆 攻略" and len(first) <= 3
    evidence = (bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION")),
                bundle(fixture_data, topics=("ROUTE", "EXPERIENCE", "DURATION"), variant="乙"))
    gaps = assessor.gaps(request, evidence)
    partial = planner.plan(request, evidence, gaps, {" 成都   川西 国庆 攻略 "})
    assert len(partial) == 2 and partial[0].gap_ids == ("TRANSPORT",)
    assert partial[1].gap_ids == ("DIRECTION_ASSOCIATION",)
    assert "交通" in partial[0].text and "攻略" not in partial[0].text
    assert planner.plan(request, evidence, gaps, {query.text for query in partial}) == ()


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
    evidence = (bundle(fixture_data), bundle(fixture_data, variant="乙"))
    assessor = evaluator()
    assert assessor.gaps(ResearchRequest(), evidence) == ()
    gaps = assessor.gaps(ResearchRequest(days=5, no_self_drive=True), evidence)
    assert {gap.gap_id for gap in gaps} == {"DAYS_FIT", "NON_SELF_DRIVE"}
    assert len(evidence[0]["claims"]) == 4


def test_negative_mentions_cannot_prove_five_days_or_non_self_drive_fit(fixture_data):
    negative = bundle(fixture_data, text_changes={
        "DURATION": "作者不建议5天完成", "TRANSPORT": "作者表示没有公共交通也没有班车",
    })
    gaps = evaluator().gaps(ResearchRequest(days=5, no_self_drive=True), (
        negative, bundle(fixture_data, variant="乙"),
    ))
    assert {gap.gap_id for gap in gaps} == {"DAYS_FIT", "NON_SELF_DRIVE"}


def test_low_confidence_or_missing_locators_cannot_close_gaps(fixture_data):
    data = bundle(fixture_data).to_dict()
    for claim in data["claims"]:
        claim["confidence"] = 0.25
        data["claim_metadata"][claim["claim_id"]]["confidence_level"] = "LOW"
    expected = {"ROUTES", "EXPERIENCES", "DURATION", "TRANSPORT", "SOURCE_CORROBORATION"}
    assert {g.gap_id for g in evaluator().gaps(ResearchRequest(), (EvidenceBundle(data),))} == expected
    for claim in data["claims"]:
        claim.update(locator="")
    with pytest.raises(ValueError):
        EvidenceBundle(data)  # T06 assessments cannot claim grounding without a locator.
    data.pop("claim_metadata")  # Legacy rows are displayable but never close coverage gaps.
    assert {g.gap_id for g in evaluator().gaps(ResearchRequest(), (EvidenceBundle(data),))} == (
        expected | {"CLAIM_DIVERSITY"}
    )


def test_vague_request_leaves_unasked_conditions_unknown():
    request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
    assert request.budget_cny_fen is None and request.transport is None
    assert request.days is None and request.traveler_count is None
