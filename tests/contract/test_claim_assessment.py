"""Optional quality metadata extends the existing evidence contract compatibly."""

from copy import deepcopy

import pytest

from travel_agent.domain.models import EvidenceBundle, validator


def assessment():
    return {
        "source_block_ids": [0], "body_origin": "STATE", "extraction_method": "MOCK",
        "extraction_basis": "合成引文已逐字核对", "confidence_level": "MEDIUM",
        "applicable_conditions": [], "canonical_relation": "STATE_ONLY", "truncation_risk": True,
        "block_locators": ["note-body:v2:STATE:" + "a" * 64 + ":chars:0-10"],
    }


def test_legacy_bundle_without_assessments_remains_accepted(fixture_data):
    data = fixture_data("evidence.json")
    assert "claim_metadata" not in EvidenceBundle(data).to_dict()


def test_optional_assessment_round_trips_through_existing_bundle(fixture_data):
    data = fixture_data("evidence.json")
    claim = data["claims"][0]
    claim["confidence"] = 0.6
    claim["locator"] = "note-body:v2:STATE:" + "a" * 64 + f":chars:0-{len(claim['text'])}"
    meta = assessment()
    meta["block_locators"] = ["note-body:v2:STATE:" + "a" * 64 + ":chars:0-100"]
    data["claim_metadata"] = {claim["claim_id"]: meta}
    assert EvidenceBundle(data).to_dict()["claim_metadata"] == data["claim_metadata"]


@pytest.mark.parametrize("changes", [
    {"confidence_level": 0.95}, {"confidence_level": "CERTAIN"},
    {"source_block_ids": []}, {"source_block_ids": [0, 0]}, {"source_block_ids": [-1]},
    {"body_origin": "ASSUMED"}, {"body": "whole private source body"},
    {"block_locators": ["https://example.invalid/?xsec_token=SECRET_XSEC_T06"]},
    {"block_locators": ["note-body:v2:" + "a" * 64 + ":chars:0-10"]},
    {"applicable_conditions": ["x" * 121]},
])
def test_quality_metadata_rejects_unbounded_or_untraceable_fields(changes):
    data = deepcopy(assessment())
    data.update(changes)
    assert not validator("ClaimAssessment").is_valid(data)


@pytest.mark.parametrize("change", [
    "unknown_claim", "confidence_mismatch", "block_count", "wrong_origin", "wrong_version",
    "outside_block", "reversed_span", "local_high", "private_basis", "partial_high",
])
def test_quality_metadata_cross_field_inconsistencies_are_rejected(fixture_data, change):
    data = fixture_data("evidence.json")
    claim = data["claims"][0]
    claim["text"], claim["confidence"] = "合成路线", 0.6
    claim["locator"] = "note-body:v2:STATE:" + "a" * 64 + ":chars:0-4"
    meta = assessment()
    data["claim_metadata"] = {claim["claim_id"]: meta}
    if change == "unknown_claim":
        data["claim_metadata"] = {"absent": meta}
    elif change == "confidence_mismatch":
        claim["confidence"] = 0.9
    elif change == "block_count":
        meta["source_block_ids"] = [0, 1]
    elif change == "wrong_origin":
        meta["body_origin"] = "DOM"
    elif change == "wrong_version":
        claim["locator"] = claim["locator"].replace("a" * 64, "b" * 64)
    elif change == "outside_block":
        claim["locator"] = claim["locator"].replace("0-4", "10-14")
    elif change == "reversed_span":
        meta["block_locators"][0] = meta["block_locators"][0].replace("0-10", "10-0")
    elif change in {"local_high", "partial_high"}:
        claim["confidence"] = 0.8
        meta["confidence_level"] = "HIGH"
        if change == "local_high":
            meta["extraction_method"] = "LOCAL_EXTRACTIVE"
        else:
            data["completeness"] = "PARTIAL_TEXT"
    elif change == "private_basis":
        meta["extraction_basis"] = "xsec_token=SECRET_XSEC_T06"
    with pytest.raises(ValueError):
        EvidenceBundle(data)
