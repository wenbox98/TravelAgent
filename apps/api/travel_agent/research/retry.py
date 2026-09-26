"""Explicit model-only retry of one durable attempt. This module never imports XHS."""

import json
from hashlib import sha256
import os
from pathlib import Path
import re
import subprocess
import sys
from time import monotonic
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from travel_agent.domain.models import SourcePolicy, validator
from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.providers.diagnostics import Diagnostic, safe_model
from travel_agent.settings import PROJECT_ROOT
from .extractor import EvidenceExtractor
from .models import ResearchReport, ResearchRequest
from .planning import SufficiencyEvaluator
from .recovery import EXTRACTION_VERSION, ExtractionRecovery
from .store import EvidenceStore

EXTRA_AUTHORIZATION = "t064-response-timeout-once"


def _config(provider: OpenAICompatibleProvider, deadline: float) -> dict[str, Any]:
    if not 0 < deadline <= 180 or safe_model(provider.model) != provider.model:
        raise ValueError("INVALID_EXTRA_CONFIG")
    config = {"host": urlsplit(provider.base_url).hostname,
            "endpoint_hash": sha256(provider.base_url.encode()).hexdigest(),
            "model": provider.model, "response_format": provider.response_format,
            "timeout_seconds": provider.timeout, "total_deadline_seconds": deadline,
            "max_http_attempts": 1, "purpose": "PRIVATE_TRAVEL_RESEARCH"}
    validator("ExtractionAuthorizationConfig").validate(config)
    return config


def authorize_extra(store: EvidenceStore, *, base_attempt_id: str, fix_commit: str,
                    provider: OpenAICompatibleProvider, deadline: float) -> dict[str, Any]:
    """Explicit offline grant for T06.4 only, never automatically called by a live retry."""
    if not re.fullmatch(r"[a-f0-9]{40}", fix_commit):
        raise ValueError("EXTRA_REQUIRES_FIX_COMMIT")
    config = _config(provider, deadline)
    with store.db.transaction() as con:
        base = con.execute("SELECT a.*,b.account_scope,c.source_id,s.source_type FROM extraction_attempts a "
            "JOIN extraction_batches b USING(batch_id) JOIN source_contents c USING(content_id) "
            "JOIN sources s ON s.source_id=c.source_id WHERE attempt_id=?", (base_attempt_id,)).fetchone()
        if (base is None or base["attempt_number"] != 2 or base["status"] != "FAILED"
            or json.loads(base["diagnostic_json"])["category"] != "TIMEOUT"):
            raise ValueError("EXTRA_REQUIRES_EXHAUSTED_TIMEOUT")
        if config["host"] != "api.deepseek.com" and not (
            base["source_type"] == "SYNTHETIC" and config["host"] == "127.0.0.1"):
            raise ValueError("EXTRA_TARGET_DENIED")
        contents = store.contents.load(base["source_id"], base["account_scope"])
        if not any(c["content_id"] == base["content_id"] and c["content_hash"] == base["content_hash"]
                   and c["normalization_version"] == base["normalization_version"] for c in contents):
            raise ValueError("EXTRA_SNAPSHOT_OR_POLICY_DENIED")
        values = (EXTRA_AUTHORIZATION, base_attempt_id, base["batch_id"], base["source_id"],
                  base["content_id"], base["content_hash"], base["account_scope"], base["normalization_version"],
                  fix_commit, json.dumps(config, sort_keys=True))
        prior = con.execute("SELECT * FROM extraction_authorizations WHERE authorization_id=?", (EXTRA_AUTHORIZATION,)).fetchone()
        if prior is not None:
            if tuple(prior)[:10] != values:
                raise ValueError("EXTRA_AUTHORIZATION_IMMUTABLE")
        else:
            con.execute("INSERT INTO extraction_authorizations VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)", (*values, store.db.stamp()))
        return {"authorization_id": EXTRA_AUTHORIZATION, "status": "CONSUMED" if prior is not None and prior["consumed_at"] else "GRANTED",
                "config": config, "http_attempts": 0}


def reserve_extra(store: EvidenceStore, *, base_attempt_id: str, fix_commit: str,
                  provider: OpenAICompatibleProvider, deadline: float) -> str:
    """BEGIN IMMEDIATE atomically consumes the grant and creates exactly one attempt."""
    with store.db.transaction() as con:
        auth = con.execute("SELECT * FROM extraction_authorizations WHERE authorization_id=?", (EXTRA_AUTHORIZATION,)).fetchone()
        if (auth is None or auth["consumed_at"] or auth["base_attempt_id"] != base_attempt_id
            or auth["fix_commit"] != fix_commit or json.loads(auth["config_json"]) != _config(provider, deadline)):
            raise ValueError("EXTRA_AUTHORIZATION_MISSING_CONSUMED_OR_MISMATCHED")
        old = con.execute("SELECT a.*,r.research_id,q.current_revision,q.request_json FROM extraction_attempts a "
            "JOIN research_runs r USING(run_id) JOIN research_questions q USING(research_id) WHERE attempt_id=?", (base_attempt_id,)).fetchone()
        if old["revision"] != old["current_revision"]:
            raise ValueError("EXTRA_STALE_REVISION")
        source = store.repository.get(auth["source_id"], auth["account_scope"])
        content = next((c for c in store.contents.load(auth["source_id"], auth["account_scope"])
                        if c["content_id"] == auth["content_id"]), None)
        if source is None or content is None or content["content_hash"] != auth["content_hash"]:
            raise ValueError("EXTRA_SNAPSHOT_OR_POLICY_DENIED")
        policy = store._latest_policy(content["policy_id"])
        run = store.begin(old["research_id"], old["revision"], json.loads(old["request_json"]), auth["account_scope"])
        store.register_policy(run, old["revision"], policy)
        attempt = "extract-" + uuid4().hex
        con.execute("INSERT INTO extraction_attempts VALUES(?,?,?,?,?,?,?,3,'PENDING',NULL,?,?,NULL,?,NULL,?)",
            (attempt, auth["batch_id"], run, old["revision"], auth["content_id"], auth["normalization_version"],
             EXTRACTION_VERSION, fix_commit, store.db.stamp(), auth["content_hash"], EXTRA_AUTHORIZATION))
        con.execute("INSERT INTO research_run_contents VALUES(?,?)", (run, auth["content_id"]))
        con.execute("UPDATE extraction_authorizations SET consumed_at=? WHERE authorization_id=?", (store.db.stamp(), EXTRA_AUTHORIZATION))
        return attempt


def run_extra_worker(store: EvidenceStore, provider: OpenAICompatibleProvider, attempt_id: str) -> None:
    auth = store.db.connection.execute("SELECT g.* FROM extraction_authorizations g JOIN extraction_attempts a "
                                      "USING(authorization_id) WHERE a.attempt_id=?", (attempt_id,)).fetchone()
    if auth is None or not auth["consumed_at"]:
        raise ValueError("UNRESERVED_EXTRA_WORKER")
    config = json.loads(auth["config_json"])
    if config != _config(provider, config["total_deadline_seconds"]):
        raise ValueError("EXTRA_WORKER_CONFIG_MISMATCH")
    ExtractionRecovery(store, EvidenceExtractor(provider)).run_reserved(attempt_id)


def supervise_extra(database: Path, *, base_attempt_id: str, fix_commit: str,
                    provider: OpenAICompatibleProvider, deadline: float = 180,
                    worker_command: list[str] | None = None) -> dict[str, Any]:
    """Own one network process. Kill and join before reconciling its actual durable state."""
    with Database(database) as db:
        attempt = reserve_extra(EvidenceStore(db), base_attempt_id=base_attempt_id,
                                fix_commit=fix_commit, provider=provider, deadline=deadline)
    command = worker_command or [sys.executable, str(PROJECT_ROOT / "scripts/retry_extraction.py"),
        "--live", "--database", str(database.resolve()), "--attempt-id", base_attempt_id,
        "--extra-worker", attempt]
    # Test workers use this environment only for their synthetic loopback invocation.
    env = dict(os.environ, TRAVEL_RESERVED_ATTEMPT=attempt, LLM_TIMEOUT_SECONDS=str(provider.timeout))
    started = monotonic()
    timed_out, process = False, None
    interrupted: BaseException | None = None
    try:
        process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        process.wait(timeout=max(0.001, deadline - (monotonic() - started)))
    except subprocess.TimeoutExpired:
        timed_out = True
    except BaseException as error:
        interrupted = error
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    elapsed = round(monotonic() - started, 4)
    with Database(database) as db:
        store = EvidenceStore(db)
        with db.transaction() as con:
            row = con.execute("SELECT * FROM extraction_attempts WHERE attempt_id=?", (attempt,)).fetchone()
            if row["status"] in {"PENDING", "RUNNING"}:
                safe = json.loads(row["diagnostic_json"]) if row["diagnostic_json"] else Diagnostic(timeout_seconds=provider.timeout).safe_dict()
                safe.update(stage="TRANSPORT" if timed_out else "INTERNAL",
                            category="TOTAL_DEADLINE" if timed_out else "UNEXPECTED_ERROR")
                con.execute("UPDATE extraction_attempts SET status=?,diagnostic_json=?,finished_at=? WHERE attempt_id=?",
                    ("INTERRUPTED" if timed_out or process is not None else "FAILED", json.dumps(safe), db.stamp(), attempt))
        result = report_saved_attempt(store, attempt)
    if interrupted is not None and not isinstance(interrupted, Exception):
        raise interrupted
    return result | {"total_deadline_seconds": deadline, "outer_elapsed_seconds": elapsed,
                     "deadline_reached": timed_out, "owned_worker_exited": process is None or process.poll() is not None,
                     "worker_exit_code": process.returncode if process is not None else None}


def retry_saved(store: EvidenceStore, extractor: EvidenceExtractor, *, attempt_id: str,
                fix_commit: str) -> dict[str, Any]:
    con = store.db.connection
    row = con.execute("SELECT a.*,b.account_scope,b.max_attempts,r.research_id,q.current_revision,q.request_json "
                      "FROM extraction_attempts a JOIN extraction_batches b USING(batch_id) "
                      "JOIN research_runs r USING(run_id) JOIN research_questions q USING(research_id) "
                      "WHERE attempt_id=?", (attempt_id,)).fetchone()
    if row is None or row["revision"] != row["current_revision"]:
        raise ValueError("RECOVERY_ATTEMPT_MISSING_OR_OBSOLETE")
    source = con.execute("SELECT policy_id FROM source_contents WHERE content_id=?",
                         (row["content_id"],)).fetchone()
    if source is None:
        raise ValueError("SOURCE_NOT_RESTORED")
    policy = store._latest_policy(source[0])
    if not isinstance(policy, SourcePolicy):
        raise PermissionError("SOURCE_POLICY_MISSING")
    request = ResearchRequest(**json.loads(row["request_json"]))
    run = store.begin(row["research_id"], row["revision"], request.to_dict(), row["account_scope"])
    store.register_policy(run, row["revision"], policy)
    outcome = ExtractionRecovery(store, extractor).execute(
        run_id=run, revision=row["revision"], content_id=row["content_id"],
        account_scope=row["account_scope"], policy=policy, batch_id=row["batch_id"],
        max_attempts=row["max_attempts"], retry_fix_commit=fix_commit)
    return report_saved_attempt(store, outcome["attempt_id"]) | {"cache_hit": outcome["cache_hit"]}


def report_saved_attempt(store: EvidenceStore, attempt_id: str) -> dict[str, Any]:
    row = store.db.connection.execute("SELECT a.*,r.research_id,q.request_json,q.account_scope FROM extraction_attempts a "
        "JOIN research_runs r USING(run_id) JOIN research_questions q USING(research_id) WHERE attempt_id=?", (attempt_id,)).fetchone()
    request = ResearchRequest(**json.loads(row["request_json"]))
    run = row["run_id"]
    outcome = ExtractionRecovery(store, EvidenceExtractor()).outcome(attempt_id)
    evidence = store.lookup(row["research_id"], request.destination, row["account_scope"])
    gaps = SufficiencyEvaluator(clock=store.db.clock).gaps(request, evidence)
    report = ResearchReport(row["research_id"], row["revision"], run, request, evidence, gaps,
        "SOURCE_UNAVAILABLE" if outcome["status"] in {"PENDING_REVIEW", "NO_ACCEPTED_EVIDENCE"} else
        "ERROR" if outcome["status"] not in {"SUCCEEDED", "PARTIAL_SUCCESS"} else "BUDGET_EXHAUSTED" if gaps else "EVIDENCE_SUFFICIENT",
        {"search": 0, "detail": 0}, len(evidence), assessed_at=store.db.stamp(),
        extraction_diagnostics=(outcome["diagnostic"],) if outcome.get("diagnostic") else (),
        extraction_results=({"status": outcome["status"], **outcome["counts"]},))
    store.finish(run, row["revision"], [g.to_dict() for g in gaps], report.safe_summary())
    return {k: v for k, v in outcome.items() if k != "result"} | {
        "summary": report.safe_summary(), "xhs_calls": {"connect": 0, "search": 0, "detail": 0},
        "browser_sessions": 0}
