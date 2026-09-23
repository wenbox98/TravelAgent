"""No real browser or network; verify the final experiment cannot silently restart."""

import json

import pytest

from travel_agent.research import smoke


def test_smoke_entrypoint_without_live_opt_in_is_local(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", ["xhs_research_smoke.py"])
    monkeypatch.setattr(smoke, "run_smoke", lambda _: pytest.fail("no live opt-in"))
    assert smoke.main(tmp_path) == 0
    assert "未启用真实访问" in capsys.readouterr().out
    assert not (tmp_path / ".local").exists()


def test_experiment_marker_precedes_setup_and_blocks_restart(monkeypatch, tmp_path):
    calls = []
    def failed_setup(project):
        calls.append(project)
        marker = project / ".local/t05-smoke/summary.json"
        assert json.loads(marker.read_text(encoding="utf-8"))["attempted"] is True
        raise RuntimeError("SECRET_COOKIE_must_not_escape")
    monkeypatch.setattr(smoke, "LiveResearchReader", failed_setup)
    monkeypatch.setattr(smoke.OpenAICompatibleProvider, "from_env", lambda: None)
    result = smoke.run_smoke(tmp_path)
    assert result["status"] == "LIVE_TEST_BLOCKED"
    assert result["business_operations"] == {"search": 0, "detail": 0}
    assert "SECRET_COOKIE" not in json.dumps(result)
    with pytest.raises(RuntimeError):
        smoke.run_smoke(tmp_path)
    assert len(calls) == 1


def test_temporary_live_policy_never_grants_durable_or_external_rights():
    policy = smoke.temporary_policy()
    assert policy["basis"] == "UNKNOWN"
    assert policy["allow_read"] and policy["allow_inference"]
    for field in ("allow_persist_raw", "allow_persist_metadata", "allow_persist_derived",
                  "allow_external_model", "allow_embed", "allow_export"):
        assert policy[field] is False
