"""Fake reader/provider for the opt-in live ledger; no actual browser or network."""

from datetime import datetime, timezone
import json
import logging
from types import SimpleNamespace

from pydantic import SecretStr

from travel_agent.research import private_smoke
from travel_agent.research.models import Candidate, DetailMaterial
from xhs_sidecar.live_observability import LiveNetworkObserver


def test_private_live_harness_charges_once_keeps_ledger_and_closes_without_disconnect(monkeypatch, tmp_path):
    readers = []
    class Reader:
        text_first = False
        def __init__(self, project, *, resource_policy, login_prompt):
            assert resource_policy.value == "OBSERVE_ONLY"
            self.closed = False
            self.connect_calls = 0
            self.profile_present_at_start = True
            self.login_state = "SESSION_PRESENT_UNVERIFIED"
            self.browser = SimpleNamespace(sessions_created=0)
            self.browser_info = {}
            self.observer = LiveNetworkObserver()
            self.profile = SimpleNamespace(exists=lambda: True)
            self.login = SimpleNamespace(audit=SimpleNamespace(logger=logging.getLogger("fake-private-smoke")))
            self.detail_summaries = []
            readers.append(self)
        def connect(self):
            self.connect_calls += 1
            self.browser.sessions_created += 1
            self.login_state = "AUTHENTICATED"
        def search(self, query):
            assert query == "成都 川西 国庆 攻略"
            return tuple(Candidate(f"xhs:synthetic-{i}", f"川西合成方向{i}路线", "normal", True) for i in range(20))
        def detail(self, candidate, number):
            self.detail_summaries.append({"identity_match": True})
            return DetailMaterial(candidate.source_id, candidate.title, "合成路线经过虚构湖泊。", "PARTIAL_TEXT",
                                  datetime.now(timezone.utc).isoformat())
        def disable_text_first(self): raise AssertionError("no optimization fallback")
        def close(self): self.closed = True
    class Provider:
        is_external = True
        is_mock = False
        model = "synthetic-model"
        response_format = "json_object"
        api_key = SecretStr("SECRET_API_KEY")
        def structured(self, task, payload, schema):
            text = payload["blocks"][0]["text"]
            return {"claims": [{"topic": "ROUTE", "kind": "AUTHOR_OPINION", "claim": text, "quote": text,
                                "source_block_ids": [0], "confidence": "MEDIUM", "applicable_conditions": [],
                                "extraction_basis": "合成夹具"}]}
    monkeypatch.setattr("travel_agent.research.live.LiveResearchReader", Reader)
    monkeypatch.setattr(private_smoke.OpenAICompatibleProvider, "from_env", lambda: Provider())
    result = private_smoke.run_live(tmp_path)
    assert result["status"] == "FIRST_ROUND_RECORDED", result
    assert result["operations"] == {"search": 1, "detail": 3}
    assert len(result["source_contents"]) == 3 and all(r["unsupported"] == 0 for r in result["source_contents"])
    assert result["closed"] and result["profile_preserved"]
    assert result["g1"] == "NOT_EVALUATED"  # Cross-process and human review still outstanding.
    assert "SECRET_API_KEY" not in json.dumps(result)
    again = private_smoke.run_live(tmp_path)
    assert again["status"] == "BLOCKED" and len(readers) == 1


def test_private_smoke_without_opt_in_has_no_live_side_effects(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["private_research_smoke"])
    def never(*args, **kwargs): raise AssertionError("must not invoke live setup")
    monkeypatch.setattr(private_smoke, "run_live", never)
    assert private_smoke.main() == 0
    assert json.loads(capsys.readouterr().out)["live_operations"] == 0


def test_legacy_unreviewed_mode_still_blocks_external_research():
    from travel_agent.research.benchmark import live_preflight
    assert live_preflight({"LLM_MODEL": "synthetic", "LLM_API_KEY": "synthetic"},
                          usage_mode="SOURCE_POLICY")["status"] == "G1_LIVE_SOURCE_POLICY_BLOCKED"
