"""The opt-in smoke harness itself is tested with offline HTTP fakes."""

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from travel_agent.providers.llm import OpenAICompatibleProvider

FILE = Path(__file__).resolve().parents[2] / "tools/llm_connectivity_smoke.py"
SPEC = importlib.util.spec_from_file_location("connectivity_smoke", FILE)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def response_row(**changes):
    text = SMOKE.BODY.splitlines()[0]
    return {"topic": "ROUTE", "kind": "AUTHOR_OPINION", "claim": text, "quote": text,
            "source_block_ids": [0], "confidence": "MEDIUM", "applicable_conditions": [],
            "extraction_basis": "合成逐字引用", **changes}


def fake_transport(monkeypatch, *, row=None, failure=None, raw=None):
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit):
            return raw if raw is not None else json.dumps({"choices": [{"message": {
                "content": json.dumps({"claims": [row or response_row()]}, ensure_ascii=False)
            }}]}).encode()
    class Opener:
        def open(self, *args, **kwargs):
            if failure is not None:
                raise failure
            return Response()
    monkeypatch.setattr(SMOKE.llm, "build_opener", lambda *args: Opener())
    return OpenAICompatibleProvider("https://model.invalid/v1", "synthetic-model", SecretStr("SECRET_KEY"))


def test_success_uses_one_provider_request_and_exact_source_locators(monkeypatch):
    result = SMOKE.run_check(fake_transport(monkeypatch))
    assert result["status"] == "PASS"
    assert result["provider_calls"] == result["http_attempts"] == 1
    assert result["locator_coverage"] == 1 and result["g1_pass"] is False
    assert result["xhs_connect"] == result["search"] == result["detail"] == 0


@pytest.mark.parametrize("row", [response_row(extra="forbidden"), response_row(
    claim="原文没有的神秘景点", quote="原文没有的神秘景点")])
def test_schema_or_hallucinated_output_cannot_pass(monkeypatch, row):
    result = SMOKE.run_check(fake_transport(monkeypatch, row=row))
    assert result["status"] == "FAIL" and result["provider_calls"] == 1


def test_timeout_fallback_never_passes_or_leaks(monkeypatch):
    result = SMOKE.run_check(fake_transport(monkeypatch, failure=TimeoutError("SECRET_KEY")))
    assert result["status"] == "FAIL" and result["transport_error"] == "TIMEOUT"
    assert result["provider_error"] == "LLM_UNAVAILABLE" and result["provider_calls"] == 1
    assert result["accepted_synthetic_claims"] == []
    assert "SECRET_KEY" not in json.dumps(result)


def test_malformed_http_body_remains_failed(monkeypatch):
    result = SMOKE.run_check(fake_transport(monkeypatch, raw=b"malformed SECRET_KEY"))
    assert result["status"] == "FAIL" and result["http_status"] == 200
    assert "SECRET_KEY" not in json.dumps(result)


@pytest.mark.parametrize("status", [401, 404])
def test_http_error_records_status_not_response_text(monkeypatch, status):
    error = HTTPError("https://private.invalid/?token=SECRET_KEY", status, "SECRET_KEY", {}, None)
    result = SMOKE.run_check(fake_transport(monkeypatch, failure=error))
    assert result["status"] == "FAIL" and result["http_status"] == status
    assert result["transport_error"] == "HTTP_ERROR"
    assert "SECRET_KEY" not in json.dumps(result) and "private.invalid" not in json.dumps(result)
