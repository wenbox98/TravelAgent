"""Local job state and explicit adoption. Reads never construct providers or browsers."""

import json
from typing import Any
from uuid import uuid4

from travel_agent.persistence.database import Database
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.models import ResearchRequest
from travel_agent.research.store import EvidenceStore
from .models import Mode
from .projection import fingerprint, safe_text
from .service import PreviewService

ACTIVE = {"QUEUED", "RUNNING", "WAITING_LOGIN"}


class JobService:
    def __init__(self, db: Database, scope: str, mode: Mode, continuation: str):
        self.db, self.scope, self.mode, self.continuation = db, scope, mode, continuation
        self.preview = PreviewService(db, scope, mode)
        self.budget = BoundedBudget(EvidenceStore(db), continuation)
        self.created = False

    def index(self, ready: bool) -> dict[str, Any]:
        try:
            state = self.budget.state()
            if state["account_scope"] != self.scope:
                raise ValueError("SCOPE_MISMATCH")
            budget = self.budget.summary()
        except ValueError:
            budget = {
                "used": dict(connect=0, search=0, detail=0, model=0),
                "remaining": dict(connect=0, search=0, detail=0, model=0),
                "gate": "NOT_CONFIGURED",
                "closed": True,
            }
        jobs = [
            self.get(r[0])
            for r in self.db.connection.execute(
                "SELECT job_id FROM preview_jobs WHERE account_scope=? "
                "AND continuation_id=? ORDER BY created_at DESC LIMIT 10",
                (self.scope, self.continuation),
            )
        ]
        return {
            "enabled": ready
            and self.mode == "CACHED_PRIVATE_PREVIEW"
            and budget["gate"] == "PASS"
            and not budget["closed"]
            and not jobs
            and budget["remaining"]["search"] > 0
            and budget["remaining"]["model"] >= 2,
            "configured": ready,
            "budget": budget,
            "jobs": jobs,
            "data_use": "仅主动研究会访问小红书；一篇必要正文过滤后最多6000字发往既定 DeepSeek，最多一次提取和一次审核。审核不代表当前事实已核实。",
        }

    def create(
        self, session: str, revision: int, destination: str | None, key: str, *, ready: bool
    ) -> dict[str, Any]:
        safe_text(key, 128)
        if not 8 <= len(key) <= 128:
            raise ValueError("INVALID_IDEMPOTENCY_KEY")
        payload = [session, revision, destination]
        with self.db.transaction() as con:
            old = con.execute(
                "SELECT job_id,request_hash FROM preview_jobs WHERE account_scope=? AND idempotency_key=?",
                (self.scope, key),
            ).fetchone()
            if old:
                if old[1] != fingerprint(payload):
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return self.get(old[0])
            if not self.index(ready)["enabled"]:
                raise ValueError("LIVE_RESEARCH_UNAVAILABLE")
            v = self.preview.get(session)
            if v["revision"] != revision:
                raise ValueError("STALE_REVISION")
            if v["stale"]:
                raise ValueError("RESEARCH_CHANGED")
            if v["research_id"]:
                q, _ = self.preview._cache(v["research_id"])
                req = json.loads(q["request_json"])
                if destination and destination != req.get("destination"):
                    raise ValueError("DESTINATION_CONFLICT")
            else:
                if not destination or not destination.strip():
                    raise ValueError("DESTINATION_REQUIRED")
                req = ResearchRequest(destination=safe_text(destination.strip(), 80)).to_dict()
            if not req.get("destination"):
                raise ValueError("DESTINATION_REQUIRED")
            prefs = v["preferences"]
            req.update(
                days=prefs["days"],
                no_self_drive=prefs["driving"] == "NO",
                budget_cny_fen=prefs["budget_cny_fen"],
                traveler_count=prefs["traveler_count"],
            )
            confirmed = next(
                (o for o in v["options"] if o["option_id"] == v["confirmed_option_id"]), None
            )
            data = {
                "request": req,
                "preferences": prefs,
                "focus": confirmed["label"] if confirmed else None,
                "original_interest": confirmed,
                "original_research_id": v["research_id"],
            }
            jid = "job-" + uuid4().hex
            research = "research-" + uuid4().hex
            con.execute(
                "INSERT INTO preview_jobs VALUES(?,?,?,?,?,?,?,?,?,?,0,NULL,?,NULL)",
                (
                    jid,
                    self.continuation,
                    session,
                    self.scope,
                    revision,
                    research,
                    json.dumps(data, ensure_ascii=False),
                    key,
                    fingerprint(payload),
                    "QUEUED",
                    self.db.stamp(),
                ),
            )
            self.created = True
            return self.get(jid)

    def get(self, job: str) -> dict[str, Any]:
        r = self.db.connection.execute(
            "SELECT * FROM preview_jobs WHERE job_id=? AND account_scope=? AND continuation_id=?",
            (job, self.scope, self.continuation),
        ).fetchone()
        if r is None:
            raise ValueError("JOB_UNAVAILABLE")
        summary = json.loads(r["summary_json"] or "{}")
        return {
            "job_id": job,
            "session_id": r["session_id"],
            "status": r["status"],
            "request_revision": r["request_revision"],
            "cancel_requested": bool(r["cancel_requested"]),
            "new_evidence_count": summary.get("new_evidence_count", 0),
            "reviewed": summary.get("reviewed", 0),
            "pending": summary.get("pending", 0),
            "rejected": summary.get("rejected", 0),
            "reason": summary.get("reason"),
            "can_adopt": r["status"] in {"COMPLETED", "PARTIAL"}
            and summary.get("new_evidence_count", 0) > 0,
        }

    def cancel(self, job: str) -> dict[str, Any]:
        with self.db.transaction():
            self.get(job)
            self.db.connection.execute(
                "UPDATE preview_jobs SET cancel_requested=1,status=CASE WHEN status='QUEUED' THEN 'CANCELED' ELSE status END "
                "WHERE job_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                (job,),
            )
            return self.get(job)

    def adopt(self, job: str, revision: int, key: str) -> dict[str, Any]:
        with self.db.transaction() as con:
            receipt = ["adopt", job, revision]
            previous = self.preview._receipt(key, receipt)
            if previous:
                return self.preview.get(previous)
            j = self.get(job)
            if not j["can_adopt"]:
                raise ValueError("NEW_MATERIAL_UNAVAILABLE")
            r = con.execute("SELECT * FROM preview_jobs WHERE job_id=?", (job,)).fetchone()
            self.preview.adopt_research(j["session_id"], r["research_id"], revision)
            self.preview._remember(key, receipt, j["session_id"])
            return self.preview.get(j["session_id"])

    def reconcile_restart(self) -> None:
        """Restart is local-only: unknown work is interrupted, never redispatched."""
        self.db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1,finished_at=? "
            "WHERE continuation_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (self.db.stamp(), self.continuation),
        )
