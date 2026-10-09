"""Startup failures are system failures, not missing user conditions. Offline only."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from travel_agent.persistence.database import Database
from travel_agent.planning.automatic import AutomaticService, run_task, revise
from travel_agent.planning.automatic_models import AutomaticStart, CONSENT
from travel_agent.planning.conversation import ConversationAction, LOOP_CONSENT, action
from travel_agent.planning.flow_models import PlanDraft, PlanCreate
from travel_agent.preview.worker import run_job

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
from automatic_fakes import config, Reader, Model, research  # noqa: E402


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    with Database(tmp_path / "startup.sqlite3") as db:
        yield AutomaticService(db, "owner")


def test_self_drive_followup_sets_matching_map_reference_and_negative_clears_it():
    draft = revise(PlanDraft(), "想自驾")
    assert (draft.driving, draft.transport, draft.inputs.mode) == ("YES", "SELF_DRIVE", "DRIVING")
    changed = revise(draft, "不想自驾")
    assert changed.transport == changed.inputs.mode == "UNKNOWN"


def test_production_reader_constructor_failure_is_visible_and_not_a_research_gap(service, monkeypatch):
    class ProfileError(RuntimeError):
        pass

    calls = []

    def constructor(*args, **kwargs):
        calls.append("constructor")
        raise ProfileError("SECRET_SENTINEL private path and token must never persist")

    # Exercise the real run_job startup path, with no injected reader bypass.
    monkeypatch.setitem(sys.modules, "travel_agent.research.live", SimpleNamespace(LiveResearchReader=constructor))
    v = service.start(AutomaticStart(request="我想去合成青谷玩7天", consent=CONSENT), str(uuid4()))
    run_task(service.db.path, v["automatic_task"]["task_id"], research_runner=lambda path, jid: run_job(path, jid, product=True))
    value = service.plans.get(v["session_id"])
    assert calls == ["constructor"]
    assert value["automatic_task"]["reason"] == "RESEARCH_XHS_PROFILE_UNAVAILABLE"
    assert value["automatic_task"]["stage"] == "SOURCE_STARTUP"
    assert not service.db.connection.execute("SELECT * FROM continuation_operations").fetchall()
    assert not service.db.connection.execute("SELECT * FROM research_runs").fetchall()
    info = service.db.connection.execute("SELECT summary_json FROM preview_jobs").fetchone()[0]
    assert "SECRET_SENTINEL" not in info and "private path" not in info
    assert json.loads(info)["failure"]["phase"] == "SOURCE_STARTUP"
    assert not value["conversation"]["pending_question"]["choices"]


def test_empty_material_question_does_not_spend_a_model_request(service):
    v = service.plans.create(PlanCreate(destination="合成远谷", request="我想去合成远谷玩7天，想自驾"), str(uuid4()))
    assert "比较" not in "".join(v["conversation"]["pending_question"]["choices"])
    body = ConversationAction(action="submit", text="为什么推荐这些？", expected_revision=v["revision"], expected_conversation_version=v["conversation"]["version"], consent=LOOP_CONSENT)
    with pytest.raises(ValueError, match="QUESTION_MATERIAL_REQUIRED"):
        action(service.db, "owner", v["session_id"], body, str(uuid4()))
    assert not service.db.connection.execute("SELECT * FROM preview_jobs").fetchall()
    assert not service.db.connection.execute("SELECT * FROM research_continuations").fetchall()


@pytest.mark.parametrize("idea", ["我想去合成远谷玩", "我想去合成海城玩9天"])
def test_empty_cache_unknown_conditions_still_dispatch_research(service, idea):
    v = service.start(AutomaticStart(request=idea, consent=CONSENT), str(uuid4()))
    assert not v["automatic_task"]["coverage"]["sufficient"]
    assert v["draft"]["transport"] == "UNKNOWN"
    assert v["draft"]["trip_budget"]["people"] is None
    reader = Reader()
    reader.search = lambda query: reader.calls.append("SEARCH") or ()
    run_task(service.db.path, v["automatic_task"]["task_id"], research_runner=research(Model(), reader))
    assert reader.calls[0:2] == ["CONNECT", "SEARCH"]
    restored = service.plans.get(v["session_id"])
    assert restored["automatic_task"]["search_count"] > 0
    assert not restored["automatic_task"]["coverage"]["sufficient"]


def test_preflight_role_denies_browser_process_and_model_and_keeps_server_isolated(tmp_path):
    import subprocess
    code = """
import sys,subprocess,urllib.request,json
from pathlib import Path
sys.path[:0]=[str(Path('apps/api').resolve()),str(Path('integrations/xhs-sidecar').resolve())]
from travel_agent.planning.network import install
install(sys.argv[1],Path(sys.argv[2]))
if sys.argv[1]=='serve':
 try: import travel_agent.research.live
 except PermissionError: pass
 else: raise AssertionError('SERVER_LIVE_IMPORT_ALLOWED')
else:
 import travel_agent.research.live
 for action in (lambda:subprocess.run([sys.executable,'-c','pass']),lambda:urllib.request.urlopen('https://api.deepseek.com/chat/completions')):
  try: action()
  except PermissionError: pass
  else: raise AssertionError('PREFLIGHT_DISPATCH_ALLOWED')
v=json.loads(Path(sys.argv[2]).read_text())
assert v['external_dns']==v['external_socket']==v['model_http']==0
print('PASS')
"""
    for role in ("serve", "research-preflight"):
        out = subprocess.run([sys.executable, "-c", code, role, str(tmp_path / (role + ".json"))], capture_output=True, text=True, encoding="utf8", timeout=15)
        assert out.returncode == 0, out.stderr
