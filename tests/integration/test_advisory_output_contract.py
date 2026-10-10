"""Authored wire contracts and safe failure shapes; no real provider requests."""

from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import SecretStr

from travel_agent.planning import advisory
from travel_agent.providers.llm import OpenAICompatibleProvider
from test_advisory_guide import proposal, synthetic
from test_daily_workbench import normal as normal_fixture, permit
from test_planning_flow import act
from travel_agent.planning.suggestions import run_worker
from travel_agent.planning.revision_diagnostics import directory

normal = normal_fixture


def bound_input(s):
    v = synthetic(s)
    _, state = s.load(v["session_id"])
    data = advisory.payload(s.db, s.scope, v["session_id"], state["planning"])
    data["allowed_citation_ids"] = ["authored-a", "authored-b"]
    data["activities"][0]["evidence_ids"] = ["authored-a", "authored-b"]
    return data


@pytest.mark.parametrize("change", ["missing", "unknown_activity", "unknown_citation"])
def test_runtime_schema_binds_exact_current_ids_and_all_activity_citations(normal, change):
    s, _ = normal
    data = bound_input(s)
    schema = advisory.response_schema(data)
    validator = Draft202012Validator(schema)
    good = proposal(data)
    assert not list(validator.iter_errors(good))
    bad = deepcopy(good)
    if change == "missing":
        bad["proposals"][0]["citation_ids"].pop()
    elif change == "unknown_activity":
        bad["proposals"][0]["activities"][0]["activity_id"] = "not-in-this-trip"
    else:
        bad["proposals"][0]["citation_ids"].append("not-in-this-input")
    if change == "missing":
        # Dependency is semantic, not a structural-schema assertion. Keep it local
        # so one bad sibling does not discard another independently valid proposal.
        assert not list(validator.iter_errors(bad))
    else:
        assert list(validator.iter_errors(bad))
    # The sibling receiver remains independent even if one output is malformed.
    assert advisory.validate(dict(protocol_version=4, proposals=[bad["proposals"][0], good["proposals"][0]]), data)["accepted_count"] == 1


def test_schema_failure_keeps_only_trusted_paths_and_codes(normal):
    s, _ = normal
    data = bound_input(s)
    bad = proposal(data)
    bad["proposals"][0]["activities"][0]["stay_min"] = "DO_NOT_RETAIN_THIS_TEXT"
    bad["proposals"][0]["untrusted-secret-field"] = "DO_NOT_RETAIN_THIS_TEXT"
    out = advisory.validate(bad, data)
    errors = out["decisions"][0]["schema_errors"]
    assert {e["field"] for e in errors} == {"activities.0.stay_min", "<unknown>"}
    assert "DO_NOT_RETAIN" not in json.dumps(out)
    assert "untrusted-secret-field" not in json.dumps(out)
    shape = advisory.shape_diagnostic(bad, data)
    assert shape["proposal_count"] == 1 and not shape["schema_valid"][0]
    assert "DO_NOT_RETAIN" not in json.dumps(shape)
    assert "untrusted-secret-field" not in json.dumps(shape)
    assert not advisory.safe_shape(bad, data)


def test_json_object_wire_sends_bound_schema_and_preserves_valid_sibling(normal, monkeypatch):
    s, _ = normal
    data = bound_input(s)
    raw = proposal(data)
    missing = deepcopy(raw["proposals"][0])
    missing["citation_ids"] = []
    raw["proposals"].insert(0, missing)
    sent = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return json.dumps(dict(choices=[dict(finish_reason="stop", message=dict(content=json.dumps(raw)))])).encode()[:limit]

    class Opener:
        def open(self, request, timeout):
            sent.append(json.loads(request.data))
            return Response()

    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *_: Opener())
    provider = OpenAICompatibleProvider("https://api.deepseek.com", "authored", SecretStr("fixture"), 120, "json_object")
    checkpoints = []
    provider.diagnostic_observer = checkpoints.append
    result = provider.structured("planning_advisory_v4", data, advisory.response_schema(data))
    assert len(sent) == 1 and sent[0]["response_format"] == {"type": "json_object"}
    prompt = sent[0]["messages"][0]["content"]
    from hashlib import sha256
    diagnostic = provider.last_diagnostic.safe_dict()
    assert diagnostic["response_format"] == "json_object"
    assert diagnostic["system_prompt_sha256"] == sha256(prompt.encode()).hexdigest()
    canonical_schema = json.dumps(advisory.response_schema(data), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert diagnostic["schema_sha256"] == sha256(canonical_schema.encode()).hexdigest()
    assert diagnostic["citation_requirement_count"] == len(data["activities"])
    assert checkpoints[0]["transport_phase"] == "OPENING"
    assert checkpoints[0]["system_prompt_sha256"] == diagnostic["system_prompt_sha256"]
    assert "ALL required_citation_ids" in prompt
    assert '"enum": ["authored-a", "authored-b"]' in prompt
    checked = advisory.validate(result, data)
    assert checked["accepted_count"] == 1 and checked["rejected_count"] == 1
    assert checked["decisions"][0]["reference_diagnostic"]["missing_required_count"] == 2


def test_production_worker_retains_safe_shape_even_when_reply_is_not_replayable(normal):
    s, _ = normal
    v = permit(s, synthetic(s), model=1)
    v = act(s, v, "suggest")

    class Model:
        calls = 0

        def structured(self, task, data, schema):
            self.calls += 1
            assert task == "planning_advisory_v4"
            assert schema["$defs"]["GuideActivity"]["properties"]["activity_id"]["enum"]
            raw = proposal(data)
            raw["proposals"][0]["activities"][0]["stay_min"] = "DO_NOT_RETAIN_THIS_TEXT"
            raw["proposals"][0]["untrusted-secret-field"] = "DO_NOT_RETAIN_THIS_TEXT"
            return raw

    model = Model()
    jid = v["job"]["job_id"]
    run_worker(s.db.path, jid, model)
    run_worker(s.db.path, jid, model)
    v = s.get(v["session_id"])
    diagnostic = v["job"]["local_diagnostic"]
    assert model.calls == 1 and not diagnostic["replayable"]
    assert diagnostic["shape_summary"]["schema_valid"] == [False]
    record = json.loads((directory(s.db) / (jid + ".json")).read_text("utf8"))
    assert record["proposals"] is None
    assert record["shape_summary"] == diagnostic["shape_summary"]
    assert "DO_NOT_RETAIN" not in json.dumps(record)
    assert "untrusted-secret-field" not in json.dumps(record)
