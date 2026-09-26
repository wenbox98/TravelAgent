"""Real loopback bytes and owned child termination; never calls an external API."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.candidate_review import review_candidates
from travel_agent.research.store import EvidenceStore
from test_candidate_grounding import prepare, candidate, accept, BODY


@pytest.mark.parametrize("mode", ["delay_old", "delay_new", "stall", "opening", "keepalive", "after_commit", "concurrent", "abort"])
def test_scaled_deadline_and_single_extra_authorization(mode, tmp_path):
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, str(root / "tests/helpers/timeout_http_probe.py"), mode,
        str(tmp_path / "cache.sqlite3")], capture_output=True, text=True, cwd=root, timeout=25)
    assert child.returncode == 0, child.stdout + child.stderr
    row = json.loads(child.stdout)
    assert row["source_unchanged"] and row["old_rows_unchanged"] and row["old_max"] == 4
    assert row["grant_consumed"] and row["replay_blocked"] and row["old_budget_still_exhausted"]
    assert row["owned_worker_exited"] and row["no_late_overwrite"] and row["browser_absent"]
    assert not row["credential_in_database"] and "SECRET_T064_CREDENTIAL" not in child.stdout + child.stderr
    assert row["http_requests"] == (0 if mode in {"opening", "abort"} else 1)
    diag = row["diagnostic"]
    if mode in {"delay_new", "concurrent", "after_commit"}:
        assert row["status"] == "PENDING_REVIEW" and diag["finish_reason"] == "stop"
        assert diag["transport_phase"] == "COMPLETE" and diag["http_status"] == 200
        assert diag["body_complete_elapsed_seconds"] >= 0.35 and row["timeout_effective"] == 1
        assert row["counts"]["locator_passed_candidates"] == 2 and row["counts"]["rejected_candidates"] == 1
        if mode != "after_commit":
            assert row["reviewed_status"] == "PARTIAL_SUCCESS" and row["persisted_evidence"] == 2
        if mode == "concurrent":
            assert row["concurrent_blocked"] == 1
        if mode == "after_commit":
            assert row["deadline_reached"]  # Do not overwrite a committed result when killing the worker.
    elif mode in {"delay_old", "stall", "keepalive"}:
        assert diag["http_status"] == 200 and diag["transport_phase"] == "BODY_READ"
        assert diag["headers_elapsed_seconds"] is not None
        assert diag["body_complete_elapsed_seconds"] is diag["generated_claims"] is None
        assert row["counts"]["persisted_evidence"] == 0
        assert diag["category"] == ("TOTAL_DEADLINE" if mode == "keepalive" else "TIMEOUT")
        if mode == "keepalive":
            assert row["status"] == "INTERRUPTED" and row["deadline_reached"]
            assert row["outer_elapsed_seconds"] < 3
    elif mode == "opening":
        assert diag["category"] in {"TIMEOUT", "NETWORK_ERROR"} and diag["http_status"] is None
        assert diag["transport_phase"] == "OPENING" and diag["headers_elapsed_seconds"] is None
    else:
        assert row["status"] == "INTERRUPTED" and not row["dispatch_marked"]
        assert diag["http_attempts"] == 0 and diag["transport_phase"] == "NOT_STARTED"


def test_v7_candidate_and_accepted_evidence_survive_v8_migration(tmp_path, clock):
    path = tmp_path / "v7.sqlite3"
    row = candidate(BODY.splitlines()[0])
    with Database(path, clock=clock, target_version=7) as db:
        store, _, _, kwargs = prepare(db, clock, [row])
        content = store.contents.load("xhs:synthetic-t063", "owner")[0]
        db.connection.execute("INSERT INTO extraction_batches VALUES('fixed-t063','owner',2)")
        db.connection.execute("INSERT INTO extraction_attempts VALUES(?,?,?,?,?,1,2,1,'PENDING_REVIEW',NULL,NULL,?,NULL,?,'LLM')",
            ("v7-original", "fixed-t063", kwargs["run_id"], 0, content["content_id"], db.stamp(), content["content_hash"]))
        check = {"candidate_index":0,"passed":True,"reason_code":"LOCATOR_PASS","block_ids":[0],"rule_version":2}
        db.connection.execute("INSERT INTO extraction_candidates VALUES(?,0,?,?,'PENDING','CONTEXT_REVIEW_REQUIRED',NULL,NULL)",
                             ("v7-original", json.dumps(row), json.dumps(check)))
        review_candidates(store, attempt_id="v7-original", account_scope="owner", decisions={0: accept()})
        before_candidate = db.connection.execute("SELECT * FROM extraction_candidates").fetchone()[:]
        before_evidence = store.lookup("partial", "合成青谷", "owner")[0].to_dict()
    with Database(path, clock=clock) as db:
        assert db.version == 10 and not db.connection.execute("PRAGMA foreign_key_check").fetchall()
        assert db.connection.execute("SELECT * FROM extraction_candidates").fetchone()[:] == before_candidate
        assert EvidenceStore(db).lookup("partial", "合成青谷", "owner")[0].to_dict() == before_evidence
        assert db.connection.execute("SELECT status,authorization_id FROM extraction_attempts").fetchone()[:] == ("SUCCEEDED", None)
