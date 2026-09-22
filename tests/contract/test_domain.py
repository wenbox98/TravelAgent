import pytest
from travel_agent.domain.models import DomainModel, EvidenceBundle, SourcePolicy


def test_fixture_contracts(fixture_data):
    cases = fixture_data("schema-cases.json")
    for case in cases["positive"]:
        DomainModel.parse(case["schema"], fixture_data(case["file"].split("/")[-1]))
    for case in cases["negative"]:
        with pytest.raises(ValueError):
            DomainModel.parse(case["schema"], case["data"])


def test_unknown_not_zero_and_no_coercion(fixture_data):
    data = fixture_data("trip-intent.json")
    assert DomainModel.parse("TripIntent", data)["budget_cny_fen"] is None
    for invalid in ("2", True, 0, -1):
        data["party_size"] = invalid
        with pytest.raises(ValueError):
            DomainModel.parse("TripIntent", data)


def test_policy_unknown_cannot_grant_persistence(fixture_data):
    policy = fixture_data("policies.json")["policies"][1]
    policy["allow_persist_raw"] = True
    with pytest.raises(ValueError):
        SourcePolicy(policy)


def test_range_and_evidence_semantics(fixture_data):
    with pytest.raises(ValueError):
        DomainModel.parse("AmountRange", {"min_fen": 5, "max_fen": 2, "currency": "CNY"})
    data = fixture_data("evidence.json")
    data["claims"][0]["source_id"] = "wrong-source"
    with pytest.raises(ValueError):
        EvidenceBundle(data)


@pytest.mark.parametrize("completeness", ["FULL_TEXT", "PARTIAL_TEXT", "SUMMARY_ONLY", "METADATA_ONLY"])
def test_completeness_is_preserved(fixture_data, completeness):
    data = fixture_data("evidence.json")
    data["completeness"] = completeness
    if completeness == "METADATA_ONLY":
        data["claims"] = []
    model = EvidenceBundle(data)
    assert model["completeness"] == completeness
    copied = model.to_dict()
    copied["completeness"] = "FULL"
    assert model["completeness"] == completeness


def test_sensitive_locator_rejected(fixture_data):
    data = fixture_data("evidence.json")
    data["claims"][0]["locator"] = "https://synthetic.invalid/?xsec_token=SYNTHETIC"
    with pytest.raises(ValueError):
        EvidenceBundle(data)
