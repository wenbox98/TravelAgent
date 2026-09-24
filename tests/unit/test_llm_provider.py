"""Stubbed HTTP transport only; never call a model or an external API."""

import json
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from travel_agent.providers.llm import LLMError, OpenAICompatibleProvider, validate_structured
from travel_agent.providers.mock.llm import MockLLMProvider

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


def test_no_environment_configuration_does_not_invent_a_model():
    assert OpenAICompatibleProvider.from_env({}) is None
    with pytest.raises(LLMError, match="^LLM_NOT_CONFIGURED$"):
        OpenAICompatibleProvider.from_env({"OPENAI_API_KEY": "SECRET_API_KEY"})


def test_explicit_environment_is_private_and_bounded():
    provider = OpenAICompatibleProvider.from_env({
        "TRAVEL_LLM_API_KEY": "SECRET_API_KEY", "TRAVEL_LLM_MODEL": "synthetic-model",
        "TRAVEL_LLM_BASE_URL": "https://model.invalid/v1", "TRAVEL_LLM_TIMEOUT_SECONDS": "7",
    })
    assert provider.timeout == 7
    assert "SECRET_API_KEY" not in repr(provider)
    assert provider.response_format == "json_schema"


@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_explicit_response_format_from_environment(mode):
    provider = OpenAICompatibleProvider.from_env({
        "LLM_API_KEY": "SECRET_API_KEY", "LLM_MODEL": "synthetic-model",
        "LLM_BASE_URL": "https://model.invalid/v1", "LLM_RESPONSE_FORMAT": mode,
    })
    assert provider.response_format == mode


@pytest.mark.parametrize("mode", ["text", "auto", "SECRET_API_KEY"])
def test_unknown_response_format_fails_closed_without_echoing_value(mode):
    with pytest.raises(LLMError, match="^LLM_NOT_CONFIGURED$"):
        OpenAICompatibleProvider.from_env({
            "LLM_API_KEY": "SECRET_API_KEY", "LLM_MODEL": "synthetic-model",
            "LLM_RESPONSE_FORMAT": mode,
        })


def test_q14_llm_environment_aliases_take_precedence_without_network():
    provider = OpenAICompatibleProvider.from_env({
        "LLM_API_KEY": "SECRET_NEW_KEY", "LLM_MODEL": "new-model",
        "LLM_BASE_URL": "https://new-model.invalid/v1", "LLM_TIMEOUT_SECONDS": "8",
        "TRAVEL_LLM_API_KEY": "old-key", "TRAVEL_LLM_MODEL": "old-model",
        "TRAVEL_LLM_BASE_URL": "https://old-model.invalid/v1", "TRAVEL_LLM_TIMEOUT_SECONDS": "7",
        "OPENAI_API_KEY": "older-key", "OPENAI_MODEL": "older-model",
    })
    assert provider.model == "new-model" and provider.timeout == 8
    assert provider.base_url == "https://new-model.invalid/v1"
    assert provider.api_key.get_secret_value() == "SECRET_NEW_KEY"
    assert "SECRET_NEW_KEY" not in repr(provider)
    with pytest.raises(LLMError, match="^LLM_NOT_CONFIGURED$"):
        OpenAICompatibleProvider.from_env({"LLM_API_KEY": "SECRET_NEW_KEY"})


@pytest.mark.parametrize("base", [
    "http://model.invalid/v1", "https://user:secret@model.invalid/v1",
    "https://model.invalid/v1?token=secret", "https://model.invalid/v1#fragment",
])
def test_remote_plain_http_or_credentials_in_base_url_are_rejected(base):
    with pytest.raises(LLMError, match="^LLM_NOT_CONFIGURED$"):
        OpenAICompatibleProvider(base, "model", SecretStr("key"))


def test_strict_schema_refuses_extra_fields_nonfinite_values_and_non_objects():
    for value in ({"ok": True, "secret": "x"}, {"ok": float("nan")}, "text", []):
        with pytest.raises(LLMError, match="^LLM_INVALID_OUTPUT$"):
            validate_structured(value, SCHEMA)


def test_mock_does_not_supply_synthetic_output_for_real_research():
    provider = MockLLMProvider({"synthetic_task": {"ok": True}})
    with pytest.raises(LLMError, match="^LLM_POLICY_BLOCKED$"):
        provider.structured("synthetic_task", {"is_synthetic": False}, SCHEMA)
    assert provider.structured("synthetic_task", {"is_synthetic": True}, SCHEMA) == {"ok": True}


class FakeResponse:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        return self.body[:limit]


def test_one_strict_request_has_no_tools_no_storage_and_returns_validated_json(monkeypatch):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return FakeResponse(json.dumps({"choices": [{"message": {
                "content": '{"ok": true}'
            }}]}).encode())
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    provider = OpenAICompatibleProvider("https://model.invalid/v1", "synthetic", SecretStr("key"), 5)
    assert provider.structured("synthetic_task", {"text": "合成输入"}, SCHEMA) == {"ok": True}
    assert len(calls) == 1 and calls[0][1] == 5
    request = json.loads(calls[0][0].data)
    assert request["response_format"]["json_schema"]["strict"] is True
    assert request["store"] is False and "tools" not in request


@pytest.mark.parametrize("content,valid", [
    ('{"ok":true}', True), ('{"ok":true,"extra":"SECRET_API_KEY"}', False),
    ('{"ok":"true"}', False), ('{}', False), ('[]', False), ('', False),
    ('malformed SECRET_API_KEY', False),
])
def test_json_object_sends_exact_schema_and_enforces_it_locally(monkeypatch, content, valid):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data))
            return FakeResponse(json.dumps({"choices": [{"message": {
                "content": content
            }}]}).encode())
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    provider = OpenAICompatibleProvider("https://model.invalid/v1", "synthetic", SecretStr("key"),
                                        response_format="json_object")
    if valid:
        assert provider.structured("synthetic_task", {"text": "合成输入"}, SCHEMA) == {"ok": True}
    else:
        with pytest.raises(LLMError) as error:
            provider.structured("synthetic_task", {"text": "合成输入"}, SCHEMA)
        assert "SECRET_API_KEY" not in str(error.value)
    assert len(calls) == 1
    assert calls[0]["response_format"] == {"type": "json_object"}
    supplied = calls[0]["messages"][0]["content"].split("Required JSON Schema: ")[1]
    assert json.loads(supplied) == SCHEMA
    assert calls[0]["store"] is False and "tools" not in calls[0]


@pytest.mark.parametrize("mode", ["json_schema", "json_object"])
def test_http_rejection_never_switches_output_format_or_retries(monkeypatch, mode):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(json.loads(request.data)["response_format"]["type"])
            raise HTTPError("https://model.invalid", 400, "SECRET_API_KEY", {}, None)
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    provider = OpenAICompatibleProvider("https://model.invalid/v1", "synthetic", SecretStr("key"),
                                        response_format=mode)
    with pytest.raises(LLMError, match="^LLM_UNAVAILABLE$"):
        provider.structured("synthetic_task", {}, SCHEMA)
    assert calls == [mode]


def test_timeout_is_not_retried_or_logged(monkeypatch, capsys):
    calls = []
    class Opener:
        def open(self, request, timeout):
            calls.append(1)
            raise TimeoutError("SECRET_API_KEY and private prompt")
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    provider = OpenAICompatibleProvider("https://model.invalid/v1", "synthetic", SecretStr("key"))
    with pytest.raises(LLMError, match="^LLM_UNAVAILABLE$") as error:
        provider.structured("synthetic_task", {"text": "合成输入"}, SCHEMA)
    assert len(calls) == 1
    captured = capsys.readouterr()
    assert "SECRET_API_KEY" not in str(error.value) + captured.out + captured.err + repr(provider)


def test_credential_payload_is_rejected_before_transport(monkeypatch):
    def never(*args):
        raise AssertionError("transport must not be created")
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", never)
    provider = OpenAICompatibleProvider("https://model.invalid/v1", "synthetic", SecretStr("key"))
    with pytest.raises(LLMError, match="^LLM_POLICY_BLOCKED$"):
        provider.structured("synthetic_task", {"xsec_token": "SECRET_XSEC_T05"}, SCHEMA)
