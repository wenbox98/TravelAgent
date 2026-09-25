"""The opt-in smoke harness itself is tested with offline HTTP fakes."""

import importlib.util
import json
from pathlib import Path
import sys
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
            return raw if raw is not None else json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"claims": [row or response_row()]}, ensure_ascii=False)
            }}]}).encode()
    class Opener:
        def open(self, *args, **kwargs):
            if failure is not None:
                raise failure
            return Response()
    monkeypatch.setattr(SMOKE.llm, "build_opener", lambda *args: Opener())
    return OpenAICompatibleProvider("https://model.invalid/v1", "synthetic-model", SecretStr("SECRET_KEY"))


@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_success_uses_one_provider_request_and_exact_source_locators(monkeypatch, mode):
    provider = fake_transport(monkeypatch)
    provider.response_format = mode
    result = SMOKE.run_check(provider)
    assert result["status"] == "PASS"
    assert result["provider_calls"] == result["http_attempts"] == 1
    assert result["locator_coverage"] == 1 and result["g1_pass"] is False
    assert result["xhs_connect"] == result["search"] == result["detail"] == 0
    assert result["response_format"] == mode


@pytest.mark.parametrize("row", [response_row(extra="forbidden"), response_row(
    claim="原文没有的神秘景点", quote="原文没有的神秘景点"), response_row(
        applicable_conditions=[{"text": "公交方便", "quote": "公交方便", "source_block_id": 0}])])
@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_schema_or_hallucinated_output_cannot_pass(monkeypatch, row, mode):
    provider = fake_transport(monkeypatch, row=row)
    provider.response_format = mode
    result = SMOKE.run_check(provider)
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


def test_named_attempt_preserves_history_and_is_never_automatically_repeated(monkeypatch, tmp_path):
    monkeypatch.setattr(SMOKE, "ROOT", tmp_path)
    history = tmp_path / ".local/t06.1-llm/connectivity.json"
    history.parent.mkdir(parents=True)
    history.write_text('{"status":"FAIL","http_status":404}', encoding="utf-8")
    provider = fake_transport(monkeypatch)
    monkeypatch.setattr(SMOKE.llm.OpenAICompatibleProvider, "from_env", lambda: provider)
    monkeypatch.setattr(sys, "argv", ["smoke", "--live-llm", "--attempt", "corrected-config"])
    assert SMOKE.main() == 0
    assert json.loads(history.read_text())["http_status"] == 404
    recorded = history.with_name("connectivity-corrected-config.json")
    before = recorded.read_bytes()
    assert json.loads(before)["http_attempts"] == 1
    def never(*args, **kwargs):
        raise AssertionError("an existing ledger must stop before provider configuration")
    monkeypatch.setattr(SMOKE.llm.OpenAICompatibleProvider, "from_env", never)
    assert SMOKE.main() == 2
    assert recorded.read_bytes() == before
    monkeypatch.setattr(sys, "argv", ["smoke", "--live-llm"])
    assert SMOKE.main() == 2


@pytest.mark.parametrize("attempt", ["../escape", "..\\escape", "C:\\elsewhere", "UPPER", "a" * 49])
def test_attempt_path_is_bounded_and_invalid_values_are_not_echoed(monkeypatch, capsys, attempt):
    monkeypatch.setattr(sys, "argv", ["smoke", "--live-llm", "--attempt", attempt])
    with pytest.raises(SystemExit) as error:
        SMOKE.main()
    assert error.value.code == 2
    assert attempt not in capsys.readouterr().err


def test_named_attempt_alone_does_not_opt_in(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(SMOKE, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["smoke", "--attempt", "corrected-config"])
    assert SMOKE.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "NOT_RUN"
    assert not (tmp_path / ".local").exists()
