"""Worker supervision uses synthetic processes and durable production state only."""
# ruff: noqa: F811 -- imported pytest fixture is resolved by test parameter name.

import json
from uuid import uuid4

import pytest

from travel_agent.persistence.database import Database
from travel_agent.planning.agent_contract import CONSENT
from travel_agent.planning.automatic_models import AutomaticStart
from travel_agent.planning.suggestions import _worker_finished
from test_goal_agent import service  # noqa: F401


@pytest.mark.parametrize("reason", ["WORKER_EXITED", "WORKER_MONITOR_FAILED"])
def test_dead_worker_is_terminal_without_replaying_or_resetting_usage(service, reason):
    s = service
    v = s.start(AutomaticStart(request="合成青谷七天", consent=CONSENT), str(uuid4()))
    task = v["automatic_task"]
    tid = task["task_id"]
    gid = s.db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()[0]
    s.db.connection.execute("UPDATE planning_tasks SET status='RUNNING',stage='DECIDING' WHERE task_id=?", (tid,))
    before = [tuple(r) for r in s.db.connection.execute("SELECT * FROM continuation_operations")]
    state = s.db.connection.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)).fetchone()[0]
    with Database(s.db.path) as monitor:
        _worker_finished(monitor, tid, automatic=True, reason=reason, exit_code=1)
        # A late receipt is idempotent and cannot replace the original terminal cause.
        _worker_finished(monitor, tid, automatic=True, reason="WORKER_EXITED", exit_code=0)
    row = s.db.connection.execute("SELECT * FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
    assert row["status"] == "INTERRUPTED" and row["stage"] == "DECIDING"
    summary = json.loads(row["summary_json"])
    assert summary["reason"] == reason and summary["failure"]["category"] == "PROCESS"
    assert s.db.connection.execute("SELECT finished_at FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone()[0]
    assert [tuple(r) for r in s.db.connection.execute("SELECT * FROM continuation_operations")] == before
    assert s.db.connection.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)).fetchone()[0] == state


def test_monitor_detects_process_exit_during_worker_write(service, monkeypatch):
    from travel_agent.planning import suggestions

    s = service
    v = s.start(AutomaticStart(request="合成青谷七天", consent=CONSENT), str(uuid4()))
    tid = v["automatic_task"]["task_id"]
    s.db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (tid,))
    writer = s.db.transaction()
    writer.__enter__()

    class Process:
        returncode = 7
        ticks = 0

        def poll(self):
            self.ticks += 1
            if self.ticks == 1:
                return None
            writer.__exit__(None, None, None)
            return self.returncode

    class Thread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    process = Process()
    monkeypatch.setattr(suggestions.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(suggestions.threading, "Thread", Thread)
    monkeypatch.setattr(suggestions, "sleep", lambda *_: None)
    suggestions.launch(s.db.path, tid, automatic=True)
    row = s.db.connection.execute("SELECT status,summary_json FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
    assert row["status"] == "INTERRUPTED"
    assert json.loads(row["summary_json"])["failure"]["exit_code"] == 7


def test_child_entry_failure_is_reported_without_model_execution(service, monkeypatch):
    from travel_agent.planning.agent import run
    from travel_agent.planning import agent

    v = service.start(AutomaticStart(request="合成青谷七天", consent=CONSENT), str(uuid4()))

    class Process:
        returncode = 1

        def poll(self):
            return 1

    def failed(command, **_):
        jid = command[command.index("--job") + 1]
        audit = service.db.path.parent / "operation-audit"
        audit.mkdir(exist_ok=True)
        (audit / f"exit-{jid}.json").write_text(json.dumps(dict(
            reason="WORKER_ENTRY_FAILED", phase="WORKER_ENTRY", exception_type="OperationalError",
            exit_code=1, model_executed=False,
        )))
        return Process()

    monkeypatch.setattr(agent.subprocess, "Popen", failed)
    run(service.db.path, v["automatic_task"]["task_id"])
    after = service.plans.get(v["session_id"])["automatic_task"]
    assert after["status"] == "BLOCKED" and after["reason"] == "WORKER_ENTRY_FAILED"
    assert after["understanding"]["model_executed"] is False
    assert after["understanding"]["failure"]["phase"] == "WORKER_ENTRY"
    assert service.db.connection.execute("SELECT status FROM preview_jobs").fetchone()[0] == "FAILED"
