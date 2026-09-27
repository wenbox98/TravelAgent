"""Explicit job worker, reusing ResearchService and the existing model supervisor."""

import json
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import sys
import threading
from time import monotonic, sleep
from typing import Any

from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.context_review import reserve_review
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import (
    ResearchBudget,
    ResearchRequest,
    ResearchStopped,
    SearchQuery,
)
from travel_agent.research.planning import QueryPlanner
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.retry import supervise_reserved
from travel_agent.research.service import ResearchService
from travel_agent.research.store import EvidenceStore
from travel_agent.settings import PROJECT_ROOT


def configured_provider() -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider.from_env()
    if provider is None or provider.timeout != 120:
        raise ValueError("CONFIGURED_120_SECOND_PROVIDER_REQUIRED")
    return provider


def model_command(
    database: Path, kind: str, identifier: str, *, product: bool = False
) -> list[str]:
    if product:
        return [
            sys.executable,
            str(PROJECT_ROOT / "scripts/product_preview.py"),
            kind,
            "--job",
            identifier,
        ]
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts/live_workbench.py"),
        kind,
        "--database",
        str(database.resolve()),
        "--identifier",
        identifier,
    ]


def supervised_review(
    store: EvidenceStore,
    provider: OpenAICompatibleProvider,
    budget: BoundedBudget,
    attempt: str,
    scope: str,
    target: dict[str, Any],
    *,
    evaluation: bool = False,
    product: bool = False,
) -> dict[str, Any]:
    budget.check_provider(provider)
    rid = reserve_review(store, budget, attempt, scope, target, evaluation=evaluation)
    return supervise_reserved(
        store.db.path,
        rid,
        provider=provider,
        deadline=180,
        context_review=True,
        command=model_command(store.db.path, "review-worker", rid, product=product),
    )


class FocusedPlanner(QueryPlanner):
    def __init__(self, focus: str | None):
        self.focus = focus

    def plan(
        self, request: ResearchRequest, evidence: Any, gaps: Any, previous: set[str]
    ) -> tuple[SearchQuery, ...]:
        # Current user constraints and selected source object only; no inferred transit preference.
        terms = [
            request.departure,
            request.destination,
            request.time_hint,
            self.focus,
            f"{request.days}天" if request.days else None,
            "不自驾 交通接驳" if request.no_self_drive else "路线 行程 交通",
        ]
        query = " ".join(str(t) for t in terms if t)
        if self.normalize(query) in {self.normalize(p) for p in previous}:
            return ()
        return (
            SearchQuery(query, tuple(g.gap_id for g in gaps), "补充当前兴趣方向和已明确条件的缺口"),
        )


def run_job(
    database: Path,
    job_id: str,
    *,
    reader: Any = None,
    provider: Any = None,
    extract_dispatch: Any = None,
    review_dispatch: Any = None,
    product: bool = False,
) -> None:
    """Injection is for authored offline tests; production command accepts no provider/URL/path from UI."""
    with Database(database) as db:
        store = EvidenceStore(db)
        with db.transaction() as con:
            j = con.execute("SELECT * FROM preview_jobs WHERE job_id=?", (job_id,)).fetchone()
            if (
                j is None
                or con.execute(
                    "UPDATE preview_jobs SET status='RUNNING' WHERE job_id=? AND status='QUEUED' AND cancel_requested=0",
                    (job_id,),
                ).rowcount
                != 1
            ):
                return
        data = json.loads(j["request_json"])
        budget = BoundedBudget(store, j["continuation_id"])
        summary: dict[str, Any] = {}
        state = "FAILED"
        owned = reader is None

        def active() -> None:
            r = con.execute(
                "SELECT status,cancel_requested FROM preview_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if r[1] or r[0] not in {"RUNNING", "WAITING_LOGIN"}:
                raise ResearchStopped("ERROR", "CANCELED")

        class Permits:
            def reserve(self, kind: str, fingerprint: str) -> None:
                active()
                if (
                    kind == "DETAIL"
                    and data.get("planning_protocol") == 2
                    and budget.summary()["remaining"]["model"] < 3
                ):
                    raise ResearchStopped("BUDGET_EXHAUSTED", "PLANNING_MODEL_RESERVED")
                budget.reserve(kind, fingerprint)

        try:
            provider = provider or configured_provider()
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            if budget.state()["gate"]["status"] != "PASS":
                raise ValueError("GATE_NOT_PASS")

            def login_prompt() -> None:
                con.execute(
                    "UPDATE preview_jobs SET status='WAITING_LOGIN' WHERE job_id=?", (job_id,)
                )
                end = monotonic() + 300
                while monotonic() < end:
                    active()
                    login = reader.login.status().status
                    if login == "AUTHENTICATED":
                        con.execute(
                            "UPDATE preview_jobs SET status='RUNNING' WHERE job_id=?", (job_id,)
                        )
                        return
                    if login == "VERIFICATION_REQUIRED":
                        raise ResearchStopped("VERIFICATION_REQUIRED")
                    sleep(0.25)
                raise ResearchStopped("NEED_LOGIN")

            if reader is None:
                from travel_agent.research.live import LiveResearchReader

                reader = LiveResearchReader(PROJECT_ROOT, login_prompt=login_prompt)
            before = {r[0] for r in con.execute("SELECT claim_id FROM claims")}

            def dispatch(attempt: str, gaps: tuple[str, ...]) -> dict[str, Any]:
                active()
                source = con.execute(
                    "SELECT c.source_id FROM extraction_attempts a JOIN source_contents c USING(content_id) WHERE attempt_id=?",
                    (attempt,),
                ).fetchone()[0]
                budget.reserve("MODEL", "extract:" + source)
                if extract_dispatch:
                    return dict(extract_dispatch(store, attempt, gaps))
                return supervise_reserved(
                    database,
                    attempt,
                    provider=provider,
                    deadline=180,
                    finish_report=False,
                    command=model_command(database, "extract-worker", attempt, product=product),
                )

            def after(out: dict[str, Any]) -> None:
                active()
                if review_dispatch:
                    review_dispatch(
                        store, budget, out["attempt_id"], j["account_scope"], data["preferences"]
                    )
                else:
                    reviewed = supervised_review(
                        store,
                        provider,
                        budget,
                        out["attempt_id"],
                        j["account_scope"],
                        data["preferences"],
                        product=product,
                    )
                    if reviewed.get("status") not in {"COMPLETED"}:
                        raise ResearchStopped("ERROR", "CONTEXT_REVIEW_NOT_COMPLETED")

            from travel_agent.domain.source_policy import private_policy

            def activity_target(evidence: Any) -> bool:
                from travel_agent.preview.projection import project
                from travel_agent.planning.materials import activities, scope_gaps

                projected = project(
                    evidence, scope=j["account_scope"], research_id=j["research_id"], now=db.clock()
                )
                refs = list(
                    {
                        e["claim_id"]: e
                        for e in [e for o in projected["options"] for e in o["evidence"]]
                        + projected["other_clues"]
                    }.values()
                )
                if data.get("planning_protocol") == 2:
                    candidates = activities(
                        refs,
                        data["request"]["destination"],
                        data.get("spatial_intent", "UNDECIDED"),
                    )
                    return (
                        sum(a.spatial_status == "MATCH" for a in candidates) >= 2
                        if data.get("spatial_intent") == "CITY_CORE"
                        else len(candidates) >= 2
                    )
                return (
                    not scope_gaps(data.get("city_area_requested", False), refs)
                    and len(activities(refs, data["request"]["destination"])) >= 2
                )

            policy = store._latest_policy(
                "private-local-research-" + j["account_scope"]
            ) or private_policy(j["account_scope"], now=db.clock())
            service = ResearchService(
                store,
                reader,
                EvidenceExtractor(provider, protocol_version=3),
                policy,
                model_batch_id=j["continuation_id"],
                # This is a batch-wide extraction cap, not a per-source retry cap.
                # Only the new grant permits two distinct sources; old caps stay immutable.
                model_max_attempts=2
                if data.get("planning_protocol") == 2
                and j["continuation_id"] == "p051-scope-locked-planning"
                else 1,
                continuation=Permits(),
                extraction_dispatch=dispatch,
                after_extraction=after,
                activity_target=activity_target if product else None,
            )
            service.planner = FocusedPlanner(data["focus"])
            if product and data.get("planning_protocol") == 2:
                from travel_agent.planning.spatial import ScopedSelector

                service.selector = ScopedSelector(data.get("spatial_intent", "UNDECIDED"))
            report = service.run(
                ResearchRequest(**data["request"]),
                research_id=j["research_id"],
                revision=0,
                account_scope=j["account_scope"],
                budget=ResearchBudget(1, budget.state()["limits"]["DETAIL"]),
            )
            accepted = {c["claim_id"] for b in report.evidence for c in b["claims"]} - before
            counts = [o.get("counts", {}) for o in service.extraction_attempts]
            summary = {
                "new_evidence_count": len(accepted),
                "reviewed": len(accepted),
                "pending": sum(c.get("context_review_pending", 0) for c in counts),
                "rejected": sum(c.get("rejected_candidates", 0) for c in counts),
                "reason": report.diagnostic,
                "report": report.safe_summary(),
                "budget": budget.summary(),
            }
            state = (
                "VERIFICATION_REQUIRED"
                if report.stop_reason == "VERIFICATION_REQUIRED"
                else "FAILED"
                if report.stop_reason in {"ERROR", "NEED_LOGIN"} and not accepted
                else "PARTIAL"
                if accepted and report.gaps
                else "COMPLETED"
                if accepted
                else "NEEDS_REVIEW"
            )
        except Exception:
            summary["reason"] = "JOB_STOPPED_BEFORE_COMPLETION"
        finally:
            if reader is not None and owned:
                try:
                    reader.close()
                    summary["browser_sessions"] = reader.browser.sessions_created
                    summary["network"] = {
                        k: asdict(reader.observer.snapshot(None if k == "TOTAL" else k))
                        for k in (
                            "TOTAL",
                            "LOGIN",
                            "SEARCH",
                            "DETAIL_1",
                            "DETAIL_2",
                            "OUTSIDE_WINDOW",
                        )
                    }
                    summary["profile_preserved"] = reader.profile.exists()
                except Exception:
                    summary["cleanup_error"] = "BROWSER_CLOSE_FAILED"
            row = con.execute(
                "SELECT status,cancel_requested FROM preview_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row[1]:
                state = "CANCELED"
            with db.transaction():
                con.execute(
                    "UPDATE preview_jobs SET status=?,summary_json=?,finished_at=? WHERE job_id=?",
                    (state, json.dumps(summary, ensure_ascii=False), db.stamp(), job_id),
                )


def launch_job(database: Path, job_id: str) -> None:
    """Return immediately to HTTP. Owned worker runs independently; no restart dispatch."""
    command = model_command(database, "job-worker", job_id)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except OSError:
        with Database(database) as db:
            db.connection.execute(
                "UPDATE preview_jobs SET status='FAILED',finished_at=? WHERE job_id=?",
                (db.stamp(), job_id),
            )
        return

    def monitor() -> None:
        process.wait()
        with Database(database) as db:
            db.connection.execute(
                "UPDATE preview_jobs SET status='INTERRUPTED',finished_at=? WHERE job_id=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
                (db.stamp(), job_id),
            )

    threading.Thread(target=monitor, daemon=True).start()


def extract_worker(store: EvidenceStore, provider: OpenAICompatibleProvider, attempt: str) -> None:
    a = store.db.connection.execute(
        "SELECT a.*,c.source_id FROM extraction_attempts a JOIN source_contents c USING(content_id) WHERE attempt_id=?",
        (attempt,),
    ).fetchone()
    if not a or a["extraction_version"] != 3 or a["attempt_number"] != 1:
        raise ValueError("WORKER_PROTOCOL_DENIED")
    budget = BoundedBudget(store, a["batch_id"])
    budget.check_provider(provider)
    budget.check_permit("MODEL", "extract:" + a["source_id"])
    research = store.db.connection.execute(
        "SELECT research_id FROM research_runs WHERE run_id=?", (a["run_id"],)
    ).fetchone()[0]
    ExtractionRecovery(store, EvidenceExtractor(provider, protocol_version=3)).run_reserved(
        attempt,
        research_gaps=("ROUTES", "DURATION", "TRANSPORT"),
        dispatch_guard=lambda: budget.check_job_active(research),
    )
