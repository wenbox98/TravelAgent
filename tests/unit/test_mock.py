import pytest
from travel_agent.providers.mock.xhs import MockXhsReadonlyAdapter
from travel_agent.providers.mock.llm import MockLLMProvider


@pytest.mark.parametrize("status", ["NEED_LOGIN", "VERIFICATION_REQUIRED", "RATE_LIMITED", "NETWORK_ERROR", "CONTENT_UNAVAILABLE", "PARSE_ERROR", "CANCELED", "ACCESS_POLICY_BLOCKED"])
def test_mock_error_results_are_not_http_errors(status, clock):
    result = MockXhsReadonlyAdapter(clock=clock, scenario=status).search("合成需求")
    assert result["status"] == status
    assert result["evidence"] == []
    assert result["metrics"]["site_http_requests"] is None


def test_mock_repeatability_and_completeness(clock):
    adapter = MockXhsReadonlyAdapter(clock=clock)
    first = adapter.search("合成需求")
    assert first.to_dict() == adapter.search("合成需求").to_dict()
    assert all(note["is_synthetic"] for note in first["candidates"])
    assert "fixture_detail" not in str(first.to_dict())
    assert adapter.detail("opaque-synthetic-N01")["evidence"][0]["completeness"] == "FULL_TEXT"
    assert adapter.detail("opaque-synthetic-N08")["evidence"][0]["completeness"] == "METADATA_ONLY"
    assert adapter.detail("opaque-synthetic-N09")["status"] == "CONTENT_UNAVAILABLE"
    assert adapter.detail("unknown")["status"] == "CONTRACT_ERROR"


def test_partial_and_summary_stay_limited(clock):
    for scenario, expected in [("PARTIAL", "PARTIAL_TEXT"), ("SUMMARY_ONLY", "SUMMARY_ONLY")]:
        result = MockXhsReadonlyAdapter(clock=clock, scenario=scenario).detail("opaque-synthetic-N01")
        assert result["status"] == "PARTIAL"
        assert result["evidence"][0]["completeness"] == expected


def test_mock_model_needs_no_credentials():
    result = MockLLMProvider().overview()
    assert result["is_synthetic"] is True
    assert result["xhs_status"] == "UNSUPPORTED"
