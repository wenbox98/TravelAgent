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
    output = {"topic": "ROUTE", "claim": "路线甲沿河出发", "quote": "路线甲沿河出发",
              "block_index": 0, "confidence": 0.95}
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
    result = EvidenceExtractor(provider, clock=clock).extract(**arguments(fixture_data))
    data = result.bundle.to_dict()
    assert validator("EvidenceBundle").is_valid(data)
    assert result.mode == "MOCK" and result.provider_called is True
    claim = data["claims"][0]
    assert claim["text"] == "路线甲沿河出发"
    assert claim["locator"].startswith("note-body:v1:") and claim["locator"].endswith(":chars:0-7")
    assert claim["source_id"] == data["source_id"] == "xhs:synthetic-note"
    assert claim["kind"] == "AUTHOR_OPINION" and claim["confidence"] == 0.6
    assert claim["valid_from"] is None and claim["valid_until"] is None


@pytest.mark.parametrize("changed", [
    {"block_index": 999}, {"quote": "正文没有这一句", "claim": "正文没有这一句"},
    {"claim": "模型擅自补充的客观事实"},
])
def test_ungrounded_or_invented_claims_are_rejected(fixture_data, clock, changed):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(**changed)]}})
    result = EvidenceExtractor(provider, clock=clock).extract(**arguments(fixture_data))
    assert result.bundle["claims"] == [] and result.rejected_claims == 1
    assert "UNSUPPORTED_CLAIMS_REJECTED" in result.gaps


@pytest.mark.parametrize("injected", [
    {"locator": "https://example.invalid?xsec_token=SECRET_XSEC_T05"},
    {"source_id": "injected-source"}, {"travel_time": "2026-10-01"},
    {"kind": "OFFICIAL_FACT"}, {"confidence": float("nan")},
])
def test_invalid_structured_output_falls_back_without_importing_injected_fields(
    fixture_data, clock, injected,
):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row(**injected)]}})
    result = EvidenceExtractor(provider, clock=clock).extract(**arguments(fixture_data))
    assert result.mode == "LOCAL_EXTRACTIVE" and result.provider_called is True
    assert all(c["kind"] == "AUTHOR_OPINION" for c in result.bundle["claims"])
    assert "SECRET_XSEC_T05" not in json.dumps(result.bundle.to_dict())


def test_r07_image_reference_creates_gap_not_invented_image_evidence(fixture_data):
    result = EvidenceExtractor().extract(**arguments(
        fixture_data, body="路线见图2，价格看图片。", image_count=2
    ))
    assert "IMAGE_INFORMATION_REQUIRED" in result.gaps
    assert "IMAGE_NOT_ANALYZED" in result.gaps and result.bundle["claims"] == []


def test_r08_r21_published_date_never_becomes_travel_date_or_full_text(fixture_data):
    result = EvidenceExtractor().extract(**arguments(fixture_data))
    assert result.bundle["source_published_at"] == "2025-10-20T02:00:00+08:00"
    assert result.bundle["travel_occurred_at"] is None
    assert result.bundle["completeness"] == "PARTIAL_TEXT"
    assert all(c["support"] == "PARTIAL" for c in result.bundle["claims"])


def test_local_fallback_is_literal_low_confidence_and_retains_useful_topics(fixture_data):
    result = EvidenceExtractor().extract(**arguments(fixture_data))
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
    extractor = EvidenceExtractor(NeverCalled())
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
    result = EvidenceExtractor(provider, clock=clock).extract(**arguments(
        fixture_data, policy=SourcePolicy(policy)
    ))
    assert result.mode == "POLICY_BLOCKED" and not result.provider_called


def test_real_source_never_uses_mock_material_even_with_allowed_policy(fixture_data, clock):
    provider = MockLLMProvider({"extract_evidence": {"claims": [row()]}})
    result = EvidenceExtractor(provider, clock=clock).extract(**arguments(fixture_data, source_type="XHS"))
    assert result.mode == "LOCAL_EXTRACTIVE" and not result.provider_called
    assert result.bundle["source_type"] == "XHS" and not result.bundle["is_synthetic"]


@pytest.mark.parametrize("completeness", ["METADATA_ONLY", "SUMMARY_ONLY"])
def test_title_or_summary_is_not_treated_as_a_read_body(fixture_data, completeness):
    result = EvidenceExtractor().extract(**arguments(fixture_data, completeness=completeness))
    assert result.bundle["claims"] == [] and result.blocks == () and result.mode == "NO_BODY"


def test_secret_input_is_not_sent_or_returned_as_evidence(fixture_data):
    result = EvidenceExtractor().extract(**arguments(
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
    result = EvidenceExtractor(FailingProvider(), clock=clock).extract(**arguments(fixture_data))
    assert result.mode == "LOCAL_EXTRACTIVE" and result.provider_called
    captured = capsys.readouterr()
    assert "SECRET_COOKIE_T05" not in captured.out + captured.err + repr(result)
