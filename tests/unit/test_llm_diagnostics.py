"""Untrusted transport/envelope/validation errors never become diagnostic text."""
import json
import ssl
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from travel_agent.providers.llm import LLMError, OpenAICompatibleProvider
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.domain.source_policy import private_policy

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ok"],
          "properties": {"ok": {"type": "boolean"}}}
SECRET = "SECRET_ERROR_PAYLOAD"


class Response:
    status = 200
    headers = {"x-request-id": SECRET}
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.data[:limit]


def invoke(monkeypatch, outcome, payload=None):
    calls = []
    class Opener:
        def open(self, req, timeout):
            calls.append(json.loads(req.data))
            if isinstance(outcome, Exception):
                raise outcome
            return Response(outcome)
    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    p = OpenAICompatibleProvider("https://model.invalid", "synthetic-model", SecretStr(SECRET),
                                response_format="json_object")
    try:
        p.structured("extract_evidence", payload or {"blocks": []}, SCHEMA)
    except LLMError as e:
        assert e.diagnostic is p.last_diagnostic
        assert SECRET not in str(e) + repr(e) + json.dumps(e.diagnostic.safe_dict())
    return p.last_diagnostic.safe_dict(), calls


@pytest.mark.parametrize("status,category", [(400,"BAD_REQUEST"),(401,"UNAUTHORIZED"),
    (403,"FORBIDDEN"),(429,"RATE_LIMITED"),(500,"SERVER_ERROR"),(503,"SERVER_ERROR")])
def test_http_classification(monkeypatch,status,category):
    from io import BytesIO
    d, calls = invoke(monkeypatch,HTTPError("https://invalid/"+SECRET,status,SECRET,{},BytesIO(SECRET.encode())))
    assert d["stage"] == "HTTP" and d["category"] == category and d["http_status"] == status
    assert d["http_attempts"] == len(calls) == 1 and d["retry_count"] == 0


@pytest.mark.parametrize("error,category", [(TimeoutError(SECRET),"TIMEOUT"),
    (URLError(TimeoutError(SECRET)),"TIMEOUT"),(ssl.SSLError(SECRET),"TLS_ERROR"),
    (URLError(ssl.SSLError(SECRET)),"TLS_ERROR"),(URLError(SECRET),"NETWORK_ERROR"),
    (RuntimeError(SECRET),"UNEXPECTED_ERROR")])
def test_transport_and_internal_are_distinct(monkeypatch,error,category):
    d,_ = invoke(monkeypatch,error)
    assert d["category"] == category and d["http_status"] is None


def envelope(content='{"ok":true}',finish="stop"):
    return json.dumps({"model":"synthetic-response", "choices":[{"finish_reason":finish,
        "message":{"content":content,"reasoning_content":SECRET}}]}).encode()


@pytest.mark.parametrize("raw,stage,category", [(b"invalid", "ENVELOPE","INVALID_ENVELOPE"),
    (b'{}',"ENVELOPE","INVALID_ENVELOPE"), (envelope(None),"COMPLETION","MISSING_CONTENT"),
    (envelope(""),"COMPLETION","EMPTY_CONTENT"),(envelope(SECRET),"CONTENT_JSON","INVALID_JSON"),
    (envelope('{"ok":"'+SECRET+'"}'),"SCHEMA","SCHEMA_INVALID"),
    (envelope('{"'+SECRET+'":true}'),"SCHEMA","SCHEMA_INVALID"),
    (envelope(finish="length"),"COMPLETION","TRUNCATED"),
    (envelope(finish="content_filter"),"COMPLETION","REFUSED"),
    (envelope(finish="aborted"),"COMPLETION","ABORTED"),
    (envelope(),"COMPLETE","SUCCESS")])
def test_response_layers(monkeypatch,raw,stage,category):
    d,calls = invoke(monkeypatch,raw)
    assert (d["stage"],d["category"],d["http_status"]) == (stage,category,200)
    assert len(calls)==1 and calls[0]["response_format"] == {"type":"json_object"}
    assert "Required JSON Schema" in calls[0]["messages"][0]["content"]
    assert d["request_id"] is None and SECRET not in json.dumps(d)


def test_policy_does_not_count_http(monkeypatch):
    d,calls = invoke(monkeypatch,envelope(), {"xsec_token":SECRET})
    assert d["stage"] == "POLICY" and d["http_attempts"] == 0 and calls == []


def test_deepseek_default_format_matches_documented_json_object_without_changing_model():
    env = {"LLM_BASE_URL": "https://api.deepseek.com", "LLM_MODEL": "deepseek-v4-flash", "LLM_API_KEY": SECRET}
    provider = OpenAICompatibleProvider.from_env(env)
    assert provider.response_format == "json_object" and provider.model == env["LLM_MODEL"]
    assert OpenAICompatibleProvider.from_env(env | {"LLM_RESPONSE_FORMAT": "json_schema"}).response_format == "json_schema"
    assert OpenAICompatibleProvider.from_env(env | {"LLM_BASE_URL": "https://model.invalid"}).response_format == "json_schema"


def test_error_survives_extractor_without_fallback_claims(monkeypatch,clock):
    class Opener:
        def open(self,*args,**kwargs): raise TimeoutError(SECRET)
    monkeypatch.setattr("travel_agent.providers.llm.build_opener",lambda *args:Opener())
    p=OpenAICompatibleProvider("https://model.invalid","synthetic-model",SecretStr(SECRET))
    r=EvidenceExtractor(p,clock=clock, protocol_version=2).extract(source_id="xhs:synthetic",source_title=None,
        body="虚构旅行路线连接合成山谷。",completeness="PARTIAL_TEXT",fetched_at=clock().isoformat(),
        policy=private_policy("owner",now=clock()),allow_fallback=False)
    assert r.diagnostic.category == "TIMEOUT" and not r.bundle["claims"]
    assert r.safe_summary()["diagnostic"]["http_attempts"] == 1
