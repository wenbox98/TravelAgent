"""Synthetic evidence boundaries; run with the unified offline gate, never a live model."""

import json

import pytest

from travel_agent.domain.models import SourcePolicy, validator
from travel_agent.providers.mock.llm import MockLLMProvider
from travel_agent.research.extractor import EvidenceExtractor, body_blocks


def arguments(fixture_data, **changes):
    values = dict(
        source_id="xhs:synthetic-note", source_title="合成旅行记录",
        body="路线甲沿河出发。\n作者这次停留两天。\n去往乙地需要换乘公交。",
        completeness="PARTIAL_TEXT", fetched_at="2026-09-24T02:00:00+08:00",
        source_published_at="2025-10-20T02:00:00+08:00",
        policy=SourcePolicy(fixture_data("policies.json")["policies"][0]),
        source_type="SYNTHETIC",
    )
    values.update(changes)
    return values


def row(**changes):
    output = {"topic": "ROUTE", "kind": "AUTHOR_OPINION",
              "claim": "路线甲沿河出发", "quote": "路线甲沿河出发",
              "source_block_ids": [0], "confidence": "HIGH", "applicable_conditions": [],
              "extraction_basis": "逐字引用合成正文"}
    output.update(changes)
    return output


def test_body_blocks_preserve_exact_source_offsets_and_version():
    body = "  第一段  \r\n\n第二段\n" + "长" * 705
    blocks = body_blocks(body)
    assert [b.block_index for b in blocks] == list(range(4))
    assert all(body[b.start:b.end] == b.text for b in blocks)
    assert all(len(b.text) <= 700 and b.locator.endswith(f":chars:{b.start}-{b.end}") for b in blocks)
    assert blocks[0].locator == body_blocks(body)[0].locator
    assert blocks[0].locator != body_blocks(body + "新")[0].locator
    assert "第一段" not in repr(blocks)


def test_r06_strict_claim_uses_program_locator_not_model_source_or_dates(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    data = result.bundle.to_dict()
    assert validator("EvidenceBundle").is_valid(data)
    assert result.mode == "MOCK" and result.provider_called is True
    claim = data["claims"][0]
    assert claim["text"] == "路线甲沿河出发"
    assert claim["locator"].startswith("note-body:v2:STATE:") and claim["locator"].endswith(":chars:0-7")
    assert claim["source_id"] == data["source_id"] == "xhs:synthetic-note"
    assert claim["kind"] == "AUTHOR_OPINION" and claim["confidence"] == 0.6
    assert claim["valid_from"] is None and claim["valid_until"] is None


@pytest.mark.parametrize("changed", [
    {"source_block_ids": [999]}, {"quote": "正文没有这一句", "claim": "正文没有这一句"},
    {"claim": "模型擅自补充的客观事实"},
])
def test_ungrounded_or_invented_claims_are_rejected(fixture_data, clock, changed):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(**changed)]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    assert result.bundle["claims"] == [] and result.rejected_claims == 1
    assert "UNSUPPORTED_CLAIMS_REJECTED" in result.gaps


@pytest.mark.parametrize("injected", [
    {"locator": "https://example.invalid?xsec_token=SECRET_XSEC_T05"},
    {"source_id": "injected-source"}, {"travel_time": "2026-10-01"},
    {"kind": "OFFICIAL_FACT"}, {"confidence": float("nan")}, {"confidence": 0.97},
])
def test_invalid_structured_output_falls_back_without_importing_injected_fields(
    fixture_data, clock, injected,
):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(**injected)]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    assert result.mode == "LOCAL_EXTRACTIVE" and result.provider_called is True
    assert all(c["kind"] == "AUTHOR_OPINION" for c in result.bundle["claims"])
    assert "SECRET_XSEC_T05" not in json.dumps(result.bundle.to_dict())


def test_r07_image_reference_creates_gap_not_invented_image_evidence(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(
        fixture_data, body="路线见图2，价格看图片。", image_count=2
    ))
    assert "IMAGE_INFORMATION_REQUIRED" in result.gaps
    assert "IMAGE_NOT_ANALYZED" in result.gaps and result.bundle["claims"] == []


def test_r08_r21_published_date_never_becomes_travel_date_or_full_text(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(fixture_data))
    assert result.bundle["source_published_at"] == "2025-10-20T02:00:00+08:00"
    assert result.bundle["travel_occurred_at"] is None
    assert result.bundle["completeness"] == "PARTIAL_TEXT"
    assert all(c["support"] == "PARTIAL" for c in result.bundle["claims"])


def test_local_fallback_is_literal_low_confidence_and_retains_useful_topics(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(fixture_data))
    assert result.mode == "LOCAL_EXTRACTIVE" and result.provider_called is False
    assert {c["topic"] for c in result.bundle["claims"]} == {"ROUTE", "DURATION", "TRANSPORT"}
    assert all(c["text"] in arguments(fixture_data)["body"] for c in result.bundle["claims"])
    assert all(c["confidence"] <= 0.25 for c in result.bundle["claims"])
    assert "LOCAL_EXTRACTIVE_ONLY" in result.gaps


def test_unknown_policy_never_calls_model_and_explicit_temporary_read_is_local(fixture_data):
    class NeverCalled:
        is_external = True
        is_mock = False
        def structured(self, *args):
            raise AssertionError("unknown policy must not send data")
    policy = SourcePolicy(fixture_data("policies.json")["policies"][1])
    extractor = EvidenceExtractor(NeverCalled(), protocol_version=2)
    blocked = extractor.extract(**arguments(fixture_data, policy=policy, source_type="XHS"))
    assert blocked.mode == "POLICY_BLOCKED" and blocked.bundle["claims"] == []
    still_blocked = extractor.extract(**arguments(
        fixture_data, policy=policy, source_type="XHS", temporary_read_allowed=True
    ))
    assert still_blocked.mode == "POLICY_BLOCKED"
    temporary_policy = policy.to_dict()
    temporary_policy.update(allow_read=True, allow_inference=True)
    local = extractor.extract(**arguments(
        fixture_data, policy=SourcePolicy(temporary_policy), source_type="XHS", temporary_read_allowed=True
    ))
    assert local.mode == "LOCAL_EXTRACTIVE" and not local.provider_called
    assert local.bundle["is_synthetic"] is False


def test_expired_inference_policy_does_not_call_external_model(fixture_data, clock):
    policy = fixture_data("policies.json")["policies"][0]
    policy["expires_at"] = "2026-09-21T00:00:00+08:00"
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(
        fixture_data, policy=SourcePolicy(policy)
    ))
    assert result.mode == "POLICY_BLOCKED" and not result.provider_called


def test_real_source_never_uses_mock_material_even_with_allowed_policy(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data, source_type="XHS"))
    assert result.mode == "LOCAL_EXTRACTIVE" and not result.provider_called
    assert result.bundle["source_type"] == "XHS" and not result.bundle["is_synthetic"]


@pytest.mark.parametrize("completeness", ["METADATA_ONLY", "SUMMARY_ONLY"])
def test_title_or_summary_is_not_treated_as_a_read_body(fixture_data, completeness):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(fixture_data, completeness=completeness))
    assert result.bundle["claims"] == [] and result.blocks == () and result.mode == "NO_BODY"


def test_secret_input_is_not_sent_or_returned_as_evidence(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(
        fixture_data, body="xsec_token=SECRET_XSEC_T05", source_title="SECRET_XSEC_T05"
    ))
    assert result.mode == "POLICY_BLOCKED" and not result.provider_called
    assert result.blocks == () and result.bundle["source_title"] is None
    assert "SECRET_XSEC_T05" not in json.dumps(result.bundle.to_dict()) + repr(result)


def test_provider_exception_falls_back_without_logging_private_exception(fixture_data, clock, capsys):
    class FailingProvider:
        is_external = True
        is_mock = False
        def structured(self, *args):
            raise TimeoutError("SECRET_COOKIE_T05")
    result = EvidenceExtractor(FailingProvider(), clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    assert result.mode == "LOCAL_EXTRACTIVE" and result.provider_called
    captured = capsys.readouterr()
    assert "SECRET_COOKIE_T05" not in captured.out + captured.err + repr(result)


def test_q04_metadata_has_grounded_blocks_but_no_body_or_model_basis(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(extraction_basis="IGNORE_PRIVATE_MODEL_BASIS")]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    claim = result.bundle["claims"][0]
    assessment = result.bundle["claim_metadata"][claim["claim_id"]]
    assert assessment["source_block_ids"] == [0] and assessment["body_origin"] == "STATE"
    assert assessment["confidence_level"] == "MEDIUM" and assessment["extraction_method"] == "MOCK"
    assert assessment["block_locators"] == [result.blocks[0].locator]
    assert assessment["canonical_relation"] == "STATE_ONLY" and assessment["truncation_risk"]
    assert "IGNORE_PRIVATE_MODEL_BASIS" not in json.dumps(result.bundle.to_dict())
    assert arguments(fixture_data)["body"] not in json.dumps(assessment, ensure_ascii=False)


@pytest.mark.parametrize("condition", [
    {"text": "五天非自驾", "quote": "五天非自驾", "source_block_id": 0},
    {"text": "作者这次停留两天", "quote": "作者这次停留两天", "source_block_id": 99},
    {"text": "两天适合所有人", "quote": "作者这次停留两天", "source_block_id": 1},
])
def test_q05_user_constraints_or_unquoted_conditions_cannot_become_source_facts(fixture_data, clock, condition):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(
        source_block_ids=[0, 1], applicable_conditions=[condition],
    )]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    assert not result.bundle["claims"] and result.rejected_claims == 1


def test_q05_source_literal_conditions_are_preserved_without_user_query_mapping(fixture_data, clock):
    condition = {"text": "作者这次停留两天", "quote": "作者这次停留两天", "source_block_id": 1}
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(
        source_block_ids=[0, 1], applicable_conditions=[condition],
    )]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data, completeness="FULL_TEXT"))
    claim = result.bundle["claims"][0]
    meta = result.bundle["claim_metadata"][claim["claim_id"]]
    assert meta["applicable_conditions"] == ["作者这次停留两天"]
    assert meta["confidence_level"] == "HIGH" and claim["confidence"] == 0.8
    assert result.bundle["applicable_conditions"] == []


def test_q04_unrelated_block_padding_is_not_a_grounded_reference(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(source_block_ids=[0, 2])]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(fixture_data))
    assert not result.bundle["claims"] and result.rejected_claims == 1


def test_q07_disagreement_downgrades_high_proposal_and_retains_gap(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(
        fixture_data, dom_body="住宿价格八十元", completeness="FULL_TEXT",
    ))
    claim = result.bundle["claims"][0]
    assert claim["confidence"] == 0.25 and result.bundle["completeness"] == "PARTIAL_TEXT"
    assert result.bundle["claim_metadata"][claim["claim_id"]]["confidence_level"] == "LOW"
    assert "BODY_VERSIONS_CONFLICT" in result.gaps


def test_q08_duplicates_are_within_source_only_and_opposition_is_retained(fixture_data, clock):
    quotes = ["五天比较宽松", "5天比较宽松", "五天很赶"]
    provider = MockLLMProvider({"extract_evidence": {"claims": [
        row(topic="DURATION", quote=q, claim=q, source_block_ids=[i]) for i, q in enumerate(quotes)
    ]}})
    extractor = EvidenceExtractor(provider, clock=clock, protocol_version=2)
    one = extractor.extract(**arguments(fixture_data, body="\n".join(quotes)))
    two = extractor.extract(**arguments(fixture_data, body="\n".join(quotes), source_id="xhs:other-source"))
    assert len(one.bundle["claims"]) == len(two.bundle["claims"]) == 2
    assert {c["text"] for c in one.bundle["claims"]} == {"五天比较宽松", "五天很赶"}
    assert {c["claim_id"] for c in one.bundle["claims"]}.isdisjoint(c["claim_id"] for c in two.bundle["claims"])


def test_dom_only_secret_never_reaches_provider_or_result(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock, protocol_version=2).extract(**arguments(
        fixture_data, body=None, dom_body="xsec_token=SECRET_XSEC_T06",
    ))
    assert not result.provider_called and result.mode == "POLICY_BLOCKED"
    assert result.canonical is None and result.blocks == ()
    assert "SECRET_XSEC_T06" not in json.dumps(result.safe_summary()) + repr(result)


def test_dom_only_image_reference_adds_image_gap_without_invented_claims(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(fixture_data, body=None, dom_body="路线见图2"))
    assert "IMAGE_INFORMATION_REQUIRED" in result.gaps and "IMAGE_NOT_ANALYZED" in result.gaps
    assert not result.bundle["claims"] and result.canonical.origin == "DOM"


def test_travel_date_is_only_a_verified_literal_source_field_at_day_precision(fixture_data):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(
        fixture_data, body="旅行日期：2025-10-02\n路线甲沿河出发。",
    ))
    assert result.bundle["travel_occurred_at"] == "2025-10-02T00:00:00+00:00"
    assert result.bundle["source_published_at"] == "2025-10-20T02:00:00+08:00"
    assert "TRAVEL_TIME_UNKNOWN" not in result.gaps


@pytest.mark.parametrize("body", [
    "计划旅行日期：2025-10-02", "去年国庆去过", "旅行日期：2025-02-30",
    "旅行日期：2025-10-02\n旅行日期：2026-10-02", "发布日期：2025-10-02",
])
def test_ambiguous_invalid_or_non_travel_dates_remain_unknown(fixture_data, body):
    result = EvidenceExtractor(protocol_version=2).extract(**arguments(fixture_data, body=body))
    assert result.bundle["travel_occurred_at"] is None and "TRAVEL_TIME_UNKNOWN" in result.gaps
