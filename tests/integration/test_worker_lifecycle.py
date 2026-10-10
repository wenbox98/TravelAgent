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


def pending_review(service):
    from test_workbench_pipeline import add_source, Provider
    from travel_agent.research.store import EvidenceStore
    from travel_agent.research.bounded import BoundedBudget
    from travel_agent.research.context_review import reserve_review

    v = service.start(AutomaticStart(request="合成青谷七天", consent=CONSENT), str(uuid4()))
    tid = v["automatic_task"]["task_id"]
    db = service.db
    gid = db.connection.execute("SELECT grant_id FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()[0]
    db.connection.execute("UPDATE planning_tasks SET status='RUNNING',stage='RESEARCH' WHERE task_id=?", (tid,))
    store = EvidenceStore(db)
    aid = add_source(store, gid, Provider())
    rid = reserve_review(store, BoundedBudget(store, gid), aid, "owner", {})
    research = db.connection.execute("SELECT r.research_id FROM extraction_attempts a JOIN research_runs r USING(run_id) WHERE attempt_id=?", (aid,)).fetchone()[0]
    jid = "job-" + uuid4().hex
    db.connection.execute("INSERT INTO preview_jobs VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,NULL)",
                          (jid,gid,v["session_id"],"owner",v["revision"]-1,research,"{}",jid,jid,"RUNNING",'{"stage":"REVIEW"}',db.stamp()))
    db.connection.execute("UPDATE planning_tasks SET research_job_id=? WHERE task_id=?", (jid,tid))
    state = json.loads(db.connection.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)).fetchone()[0])
    state["planning"]["research_job_id"] = jid
    db.connection.execute("UPDATE preview_sessions SET state_json=? WHERE session_id=?", (json.dumps(state),v["session_id"]))
    db.connection.execute("UPDATE planning_tasks SET status='RUNNING',stage='RESEARCH' WHERE task_id=?", (tid,))
    db.connection.execute("UPDATE context_review_runs SET status='RUNNING',diagnostic_json=? WHERE review_id=?",
                          ('{"http_status":200,"transport_phase":"BODY_READ"}', rid))
    return v, tid, gid, aid, rid


@pytest.mark.parametrize("stop", ["restart", "legacy_restart", "worker_exit"])
def test_interruption_settles_pending_review_and_preserves_extraction(service, stop):
    from travel_agent.planning.automatic import recover
    v, tid, gid, aid, rid = pending_review(service)
    con = service.db.connection
    before = [tuple(r) for r in con.execute("SELECT * FROM continuation_operations")]
    material = con.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)).fetchone()[0]
    candidates = [tuple(r) for r in con.execute("SELECT * FROM extraction_candidates")]
    if stop in {"restart", "legacy_restart"}:
        if stop == "legacy_restart":
            con.execute("UPDATE planning_tasks SET status='INTERRUPTED',summary_json=? WHERE task_id=?", ('{"reason":"SERVER_STOPPED"}', tid))
            con.execute("UPDATE research_continuations SET finished_at=? WHERE continuation_id=?", (service.db.stamp(), gid))
            con.execute("UPDATE preview_jobs SET status='CANCELED',cancel_requested=1 WHERE continuation_id=?", (gid,))
        recover(service.db)
        recover(service.db)
    else:
        _worker_finished(service.db, tid, automatic=True, reason="WORKER_EXITED", exit_code=7)
    row = con.execute("SELECT * FROM context_review_runs WHERE review_id=?", (rid,)).fetchone()
    assert row["status"] == "INTERRUPTED" and row["finished_at"]
    assert json.loads(row["diagnostic_json"])["transport_phase"] == "BODY_READ"
    assert con.execute("SELECT status FROM extraction_attempts WHERE attempt_id=?", (aid,)).fetchone()[0] == "PENDING_REVIEW"
    assert [tuple(r) for r in con.execute("SELECT * FROM continuation_operations")] == before
    assert [tuple(r) for r in con.execute("SELECT * FROM extraction_candidates")] == candidates
    assert con.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)).fetchone()[0] == material
    assert con.execute("SELECT finished_at FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone()[0]
    assert con.execute("SELECT status FROM preview_jobs WHERE continuation_id=?", (gid,)).fetchone()[0] == "INTERRUPTED"


def test_late_review_result_cannot_replace_interruption_or_approve(service):
    from test_workbench_pipeline import Provider
    from travel_agent.research.store import EvidenceStore
    from travel_agent.research.context_review import run_review

    _, tid, _, _, rid = pending_review(service)
    con = service.db.connection
    con.execute("UPDATE context_review_runs SET status='PENDING' WHERE review_id=?", (rid,))
    before = [tuple(r) for r in con.execute("SELECT * FROM extraction_candidates")]

    class LateProvider(Provider):
        def structured(self, *args):
            result = super().structured(*args)
            _worker_finished(service.db, tid, automatic=True, reason="WORKER_EXITED", exit_code=7)
            return result

    provider = LateProvider()
    result = run_review(EvidenceStore(service.db), provider, rid)
    assert provider.calls == ["review_evidence_context_v2"]
    assert result["status"] == "INTERRUPTED"
    assert [tuple(r) for r in con.execute("SELECT * FROM extraction_candidates")] == before


@pytest.mark.parametrize("fault", ["nonzero", "kill", "deadline"])
def test_actual_subprocess_failure_is_terminal(service, monkeypatch, fault):
    """Real OS processes under the production supervisor; no external transports."""
    import subprocess
    import sys
    import time
    from travel_agent.planning import suggestions

    _, tid, gid, _, rid = pending_review(service)
    real_popen, real_monotonic = subprocess.Popen, suggestions.monotonic
    processes = []
    launched = time.monotonic()

    def spawn(*args, **kwargs):
        body = "import time; time.sleep(.4); raise SystemExit(7)" if fault == "nonzero" else "import time; time.sleep(60)"
        child = real_popen([sys.executable, "-c", body], **kwargs)
        processes.append(child)
        return child

    monkeypatch.setattr(suggestions.subprocess, "Popen", spawn)
    if fault == "deadline":
        monkeypatch.setattr(suggestions, "monotonic", lambda: real_monotonic() + (4000 if time.monotonic() - launched > .5 else 0))
    try:
        suggestions.launch(service.db.path, tid, automatic=True)
        end = time.monotonic() + 10
        while not processes and time.monotonic() < end:
            time.sleep(.05)
        assert processes
        if fault == "kill":
            processes[0].kill()
        row = None
        while time.monotonic() < end:
            row = service.db.connection.execute("SELECT status,summary_json FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
            if row[0] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(.05)
        assert row[0] == "INTERRUPTED", dict(row)
        reason = json.loads(row[1])["reason"]
        assert reason == ("TASK_DEADLINE" if fault == "deadline" else "WORKER_EXITED")
        assert service.db.connection.execute("SELECT status FROM context_review_runs WHERE review_id=?", (rid,)).fetchone()[0] == "INTERRUPTED"
        assert service.db.connection.execute("SELECT finished_at FROM research_continuations WHERE continuation_id=?", (gid,)).fetchone()[0]
    finally:
        for child in processes:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)


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


def test_transient_exclusive_writer_does_not_interrupt_healthy_worker(service, monkeypatch):
    import sqlite3
    import threading
    from time import sleep
    from travel_agent.planning import suggestions

    s = service
    v = s.start(AutomaticStart(request="合成青谷七天", consent=CONSENT), str(uuid4()))
    tid = v["automatic_task"]["task_id"]
    locked = threading.Event()

    class Process:
        returncode = None

        def __init__(self):
            self.thread = real_thread(target=self.work, daemon=True)
            self.started = False

        def work(self):
            con = sqlite3.connect(s.db.path, isolation_level=None)
            con.execute("BEGIN EXCLUSIVE")
            con.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?", (tid,))
            locked.set()
            sleep(6)  # Exceed SQLite's existing 5-second busy timeout.
            con.execute("COMMIT")
            sleep(2)  # A healthy worker remains active after the transient lock.
            con.execute("UPDATE planning_tasks SET status='COMPLETED' WHERE task_id=? AND status='RUNNING'", (tid,))
            con.close()
            self.returncode = 0

        def poll(self):
            if not self.started:
                self.started = True
                self.thread.start()
                assert locked.wait(2)
            return self.returncode

        def wait(self, timeout=None):
            self.thread.join(timeout)
            return self.returncode

    real_thread = threading.Thread

    class Monitor:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    # Leave the simulated worker on a real thread, execute the monitor synchronously.
    processes = []
    def start_process(*args, **kwargs):
        process = Process()
        processes.append(process)
        return process
    monkeypatch.setattr(suggestions.subprocess, "Popen", start_process)
    monkeypatch.setattr(suggestions.threading, "Thread", Monitor)
    suggestions.launch(s.db.path, tid, automatic=True)
    processes[0].thread.join(10)
    monkeypatch.setattr(suggestions.threading, "Thread", real_thread)
    row = s.db.connection.execute("SELECT status,summary_json FROM planning_tasks WHERE task_id=?", (tid,)).fetchone()
    assert row["status"] == "COMPLETED", json.loads(row["summary_json"])
