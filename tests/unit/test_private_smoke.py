"""Fake reader/provider for the opt-in live ledger; no actual browser or network."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
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
            assert task == 'select_evidence_references_v1'
            span = payload['spans'][0]['span_id']
            return {'claims':[{'topic':'ROUTE','statement_span_id':span,'condition_span_ids':[span],
                                'proposed_reference_kind':'GUIDE_SUGGESTION'}]}
    monkeypatch.setattr("travel_agent.research.live.LiveResearchReader", Reader)
    monkeypatch.setattr(private_smoke.OpenAICompatibleProvider, "from_env", lambda: Provider())
    def review(outcome):
        from travel_agent.persistence.database import Database
        from travel_agent.research.store import EvidenceStore
        from travel_agent.research.candidate_review import review_candidates
        from travel_agent.research.grounding import REVIEW_DIMENSIONS
        with Database(tmp_path / ".local/t06.1-private/research.sqlite3") as db:
            review_candidates(EvidenceStore(db), attempt_id=outcome["attempt_id"], account_scope=private_smoke.SCOPE,
                decisions={c["candidate_index"]: {"action":"ACCEPT", "reason_code":"WORK_CONTEXT_VERIFIED",
                    "dimension_checks":{k:True for k in REVIEW_DIMENSIONS},'reference_scope':'GUIDE_SUGGESTION'}
                    for c in outcome["candidate_checks"] if c["context_status"] == "PENDING"})
    result = private_smoke.run_live(tmp_path, after_extraction=review)
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


def test_standalone_entry_loads_sidecar_without_pytest_pythonpath(tmp_path):
    project = Path(__file__).resolve().parents[2]
    entry = project / "scripts/private_research_smoke.py"
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LLM_", "TRAVEL_LLM_", "OPENAI_")) and key != "PYTHONPATH"}
    # Match the real entry's script path, while denying network in this child too.
    child = """
import pathlib, runpy, sys
def deny(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        raise AssertionError('OFFLINE_ONLY')
sys.addaudithook(deny)
entry = sys.argv[1]
sys.path.insert(0, str(pathlib.Path(entry).parent))
from _bootstrap import enter
enter()
from travel_agent.research import private_smoke
private_smoke.PROJECT_ROOT = pathlib.Path(sys.argv[2])
sys.argv = [entry, '--live']
runpy.run_path(entry, run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", child, str(entry), str(tmp_path)], cwd=project,
                            env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert json.loads(result.stdout) == {"status": "BLOCKED", "reason": "LLM_NOT_CONFIGURED"}
