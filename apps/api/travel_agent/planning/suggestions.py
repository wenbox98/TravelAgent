"""Bounded planning task on preview_jobs + continuation_operations; no research."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
from time import monotonic, sleep
from typing import Any
from uuid import uuid4

from travel_agent.persistence.database import Database
from travel_agent.preview.projection import fingerprint, safe_text
from travel_agent.preview.worker import configured_provider
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.retry import _config
from travel_agent.research.store import EvidenceStore
from travel_agent.settings import PROJECT_ROOT
from .flow_models import PlanDraft, PlanningResponse

IDENTIFIER = "p04-planning-synthetic-two"
_launch_lock = threading.Lock()
_workers: dict[tuple[str, str], subprocess.Popen[Any] | None] = {}
_closing: set[str] = set()


def grant(db: Database, scope: str, provider: OpenAICompatibleProvider) -> None:
    """Explicit CLI authorization only. Boot/read/restart cannot create a grant."""
    config = _config(provider, 180)
    if config["host"] != "api.deepseek.com" or provider.timeout != 120:
        raise ValueError("PLANNING_PROVIDER_DENIED")
    config["workspace"] = sha256(str(db.path.resolve()).encode()).hexdigest()
    with db.transaction() as con:
        previous = con.execute(
            "SELECT config_json FROM research_continuations WHERE account_scope=? AND limits_json IS NULL ORDER BY created_at DESC LIMIT 1",
            (scope,),
        ).fetchone()
        if previous is None or json.loads(previous[0]) != _config(provider, 180):
            raise ValueError("PLANNING_ORIGINAL_PROVIDER_REQUIRED")
        old = con.execute(
            "SELECT account_scope,config_json FROM research_continuations WHERE continuation_id=?",
            (IDENTIFIER,),
        ).fetchone()
        if old:
            if old[0] != scope or json.loads(old[1]) != config:
                raise ValueError("BOUNDED_GRANT_IMMUTABLE")
            return
        con.execute(
            "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
            (
                IDENTIFIER,
                scope,
                "P04_EXPLICIT_SYNTHETIC_AUTHORIZATION",
                json.dumps(config, sort_keys=True),
                db.stamp(),
                db.stamp(),
                json.dumps({"MODEL": 2}),
                '{"status":"SYNTHETIC_ONLY"}',
            ),
        )


def model_used(db: Database) -> int:
    return int(
        db.connection.execute(
            "SELECT count(*) FROM continuation_operations WHERE continuation_id=? AND kind='MODEL'",
            (IDENTIFIER,),
        ).fetchone()[0]
    )


def payload_for(p: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted synthetic data only. Never serialize UI request/private endpoints."""
    from .flow import demo_activities

    if p["demo"] not in {"CITY", "REGIONAL"}:
        raise ValueError("PLANNING_SYNTHETIC_ONLY")
    draft = PlanDraft.model_validate(p["draft"])
    catalog = {a.activity_id: a for a in demo_activities(p["demo"])}
    if not draft.activities or any(
        a.activity_id not in catalog
        or (a.name, a.region, a.provenance, a.evidence_ids)
        != (catalog[a.activity_id].name, catalog[a.activity_id].region, "SYNTHETIC_TEST", [])
        for a in draft.activities
    ):
        raise ValueError("PLANNING_SYNTHETIC_ONLY")
    return {
        "purpose": "SYNTHETIC_PLANNING_TEST",
        "travel_kind": p["demo"],
        "destination": "虚构城市甲" if p["demo"] == "CITY" else "虚构山岭乙",
        "scope": draft.inputs.planning_scope,
        "days": draft.days,
        "transport": draft.transport,
        "driving": draft.driving,
        "charter": draft.inputs.charter,
        "first_start": draft.inputs.activity_start,
        "first_day": draft.first_day,
        "first_period": draft.first_period,
        "return_deadline": draft.return_deadline,
        "activities": [
            {
                "activity_id": a.activity_id,
                "name": catalog[a.activity_id].name,
                "region": catalog[a.activity_id].region,
                "day": a.day,
                "locked_start": a.locked_start,
                "stay_min": a.stay_min,
                "stay_max": a.stay_max,
            }
            for a in draft.activities
        ],
        "allowed_citation_ids": [],
        "known_map_values": [],
        "instructions": "提供两种可修改安排，锁定预约不移动；未知交通保留。所有活动地点均虚构。",
    }


def model_available(db: Database, scope: str, p: dict[str, Any]) -> bool:
    try:
        payload_for(p)
        budget = BoundedBudget(EvidenceStore(db), IDENTIFIER)
        s = budget.state()
        if s["account_scope"] != scope or s["finished_at"] or model_used(db) >= 2:
            return False
        if db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE continuation_id=? AND json_extract(request_json,'$.slot')=?",
            (IDENTIFIER, p["demo"]),
        ).fetchone():
            return False
        budget.check_provider(configured_provider())
        return True
    except ValueError, RuntimeError:
        return False


def create_job(
    db: Database, scope: str, sid: str, revision: int, p: dict[str, Any], key: str
) -> str:
    if not model_available(db, scope, p):
        raise ValueError("PLANNING_UNAVAILABLE")
    payload = payload_for(p)
    budget = BoundedBudget(EvidenceStore(db), IDENTIFIER)
    budget.reserve_count("MODEL", p["demo"], {"MODEL": 2})
    jid = "planning-" + uuid4().hex
    data = {
        "task": "planning_suggestion",
        "slot": p["demo"],
        "payload": payload,
        "draft": p["draft"],
    }
    db.connection.execute(
        "INSERT INTO preview_jobs VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL,?,NULL)",
        (
            jid,
            IDENTIFIER,
            sid,
            scope,
            revision,
            jid,
            json.dumps(data, ensure_ascii=False),
            key,
            fingerprint(payload),
            "QUEUED",
            db.stamp(),
        ),
    )
    return jid


def job_view(db: Database, scope: str, jid: str) -> dict[str, Any]:
    row = db.connection.execute(
        "SELECT * FROM preview_jobs WHERE job_id=? AND account_scope=? AND continuation_id=?",
        (jid, scope, IDENTIFIER),
    ).fetchone()
    if row is None:
        raise ValueError("JOB_UNAVAILABLE")
    summary = json.loads(row["summary_json"] or "{}")
    return {
        "job_id": jid,
        "status": row["status"],
        "request_revision": row["request_revision"],
        "proposals": summary.get("proposals", []),
        "reason": summary.get("reason"),
        "provenance": "AI_PROPOSED",
        "diagnostic": summary.get("diagnostic", {}),
    }


def validate_response(raw: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    response = PlanningResponse.model_validate(raw).model_dump()
    allowed = {a["activity_id"]: a for a in payload["activities"]}
    for proposal in response["proposals"]:
        ids = [a["activity_id"] for a in proposal["activities"]]
        if (
            len(set(ids)) != len(ids)
            or not set(ids) <= allowed.keys()
            or not set(proposal["citation_ids"]) <= set(payload["allowed_citation_ids"])
        ):
            raise ValueError("PLANNING_UNKNOWN_REFERENCE")
        for activity in proposal["activities"]:
            if activity["stay_max"] < activity["stay_min"] or (
                payload["days"] and activity["day"] > payload["days"]
            ):
                raise ValueError("PLANNING_INVALID_TIME")
        for identifier, activity in allowed.items():
            if activity["locked_start"] and (
                identifier not in ids
                or next(a for a in proposal["activities"] if a["activity_id"] == identifier)["day"]
                != activity["day"]
            ):
                raise ValueError("PLANNING_LOCKED_CONSTRAINT")
        if payload["first_start"] and proposal["first_start"] != payload["first_start"]:
            raise ValueError("PLANNING_LOCKED_ANCHOR")
        if payload["transport"] != "UNKNOWN" and proposal["transport"] != payload["transport"]:
            raise ValueError("PLANNING_LOCKED_TRANSPORT")
        if payload["driving"] == "NO" and proposal["transport"] == "SELF_DRIVE":
            raise ValueError("PLANNING_LOCKED_TRANSPORT")
        for value in [
            proposal["title"],
            proposal["reason"],
            *proposal["assumptions"],
            *proposal["unknowns"],
            *proposal["impacts"],
        ]:
            safe_text(value, 500)
            if re.search(
                r"https?://|保证|已预订|已核实|\d+\s*(?:元|公里|km)|(?:车程|公交|驾车|接驳).{0,8}\d+\s*分钟",
                value,
                re.I,
            ):
                raise ValueError("PLANNING_UNSUPPORTED_FACT")
    return response


def apply_proposal(
    db: Database, scope: str, p: dict[str, Any], revision: int, index: int
) -> dict[str, Any]:
    job = job_view(db, scope, p["job_id"])
    if (
        job["status"] != "COMPLETED"
        or job["request_revision"] != revision
        or index >= len(job["proposals"])
    ):
        raise ValueError("STALE_PROPOSAL")
    draft = PlanDraft.model_validate(p["draft"])
    proposal = job["proposals"][index]
    old = {a.activity_id: a for a in draft.activities}
    arranged = []
    for item in proposal["activities"]:
        a = deepcopy(old[item["activity_id"]])
        a.day, a.stay_min, a.stay_max, a.rest_minutes = (
            item["day"],
            item["stay_min"],
            item["stay_max"],
            item["rest_minutes"],
        )
        a.timing_origin = "AI_PROPOSED"
        arranged.append(a)
    draft.activities = arranged
    if not draft.inputs.activity_start:
        draft.inputs.activity_start = proposal["first_start"]
        draft.anchor_origin = "AI_PROPOSED"
    # A transport suggestion remains in the proposal, never silently a preference.
    return draft.model_dump()


def run_worker(database: Path, jid: str, provider: Any = None) -> None:
    with Database(database) as db:
        with db.transaction() as con:
            row = con.execute(
                "SELECT * FROM preview_jobs WHERE job_id=? AND continuation_id=?", (jid, IDENTIFIER)
            ).fetchone()
            if (
                row is None
                or con.execute(
                    "UPDATE preview_jobs SET status='RUNNING' WHERE job_id=? AND status='QUEUED' AND cancel_requested=0",
                    (jid,),
                ).rowcount
                != 1
            ):
                return
        summary: dict[str, Any] = {}
        status = "FAILED"
        try:
            provider = provider or configured_provider()
            budget = BoundedBudget(EvidenceStore(db), IDENTIFIER)
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            data = json.loads(row["request_json"])
            budget.check_permit("MODEL", data["slot"])
            budget.check_job_active(jid)
            from .flow import PlanningService

            live, state = PlanningService(db, row["account_scope"]).load(row["session_id"])
            if (
                live["revision"] != row["request_revision"]
                or payload_for(state["planning"]) != data["payload"]
            ):
                raise ValueError("STALE_PROPOSAL")
            raw = provider.structured(
                "planning_suggestion", data["payload"], PlanningResponse.model_json_schema()
            )
            summary = validate_response(raw, data["payload"])
            status = "COMPLETED"
        except Exception as exc:
            summary = {
                "reason": str(exc)
                if str(exc)
                in {
                    "STALE_PROPOSAL",
                    "PLANNING_UNKNOWN_REFERENCE",
                    "PLANNING_LOCKED_CONSTRAINT",
                    "PLANNING_LOCKED_ANCHOR",
                    "PLANNING_LOCKED_TRANSPORT",
                    "PLANNING_UNSUPPORTED_FACT",
                    "PLANNING_INVALID_TIME",
                }
                else "PLANNING_NOT_GENERATED"
            }
        if isinstance(provider, OpenAICompatibleProvider) and provider.last_diagnostic:
            summary["diagnostic"] = provider.last_diagnostic.safe_dict()
        with db.transaction() as con:
            # Never writes a trip draft or adopted plan. Cancellation/deadline wins.
            con.execute(
                "UPDATE preview_jobs SET status=?,summary_json=?,finished_at=? WHERE job_id=? AND status='RUNNING' AND cancel_requested=0",
                (status, json.dumps(summary, ensure_ascii=False), db.stamp(), jid),
            )


def launch(database: Path, jid: str) -> None:
    owner = str(database.resolve())
    identity = (owner, jid)
    with _launch_lock:
        if identity in _workers or owner in _closing:
            return
        # Keep the receipt after completion: replay cannot start a second supervisor.
        _workers[identity] = None

    def supervise() -> None:
        command = [
            sys.executable,
            str(PROJECT_ROOT / "scripts/product_preview.py"),
            "worker",
            "--job",
            jid,
        ]
        try:
            with _launch_lock:
                if owner in _closing:
                    return
                process = subprocess.Popen(
                    command, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                _workers[identity] = process
        except OSError:
            with Database(database) as db:
                db.connection.execute(
                    "UPDATE preview_jobs SET status='FAILED',summary_json=? WHERE job_id=? AND status='QUEUED'",
                    ('{"reason":"WORKER_NOT_STARTED"}', jid),
                )
            return
        end = monotonic() + 180
        while process.poll() is None:
            with Database(database) as db:
                row = db.connection.execute(
                    "SELECT cancel_requested,status FROM preview_jobs WHERE job_id=?", (jid,)
                ).fetchone()
                stop = (
                    row is None
                    or row[0]
                    or row[1] in {"INTERRUPTED", "CANCELED"}
                    or monotonic() >= end
                )
                if stop:
                    db.connection.execute(
                        "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,summary_json=? WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                        ('{"reason":"CANCELED_OR_TOTAL_DEADLINE"}', jid),
                    )
                    _stop_process(process)
                    return
            sleep(0.25)
        with Database(database) as db:
            db.connection.execute(
                "UPDATE preview_jobs SET status='FAILED',summary_json=? WHERE job_id=? AND status IN ('QUEUED','RUNNING')",
                ('{"reason":"WORKER_EXITED"}', jid),
            )

    threading.Thread(target=supervise, daemon=True).start()


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def shutdown_workers(database: Path) -> None:
    """Normal server shutdown invalidates jobs before stopping its own children."""
    owner = str(database.resolve())
    with _launch_lock:
        _closing.add(owner)
        processes = [p for (path, _), p in _workers.items() if path == owner and p is not None]
    with Database(database) as db:
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,summary_json=? WHERE continuation_id=? AND status IN ('QUEUED','RUNNING')",
            ('{"reason":"SERVER_STOPPED"}', IDENTIFIER),
        )
    for process in processes:
        _stop_process(process)
