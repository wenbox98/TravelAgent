"""Explicit job worker, reusing ResearchService and the existing model supervisor."""

import json
from dataclasses import asdict
import os
from pathlib import Path
import subprocess
import sys
import threading
import re
import traceback
from time import monotonic, sleep
from typing import Any

from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget, has_capacity
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


def failure_diagnostic(exc: Exception, phase: str) -> dict[str, Any]:
    """Code locations only; never exception text, locals, paths or upstream payloads."""
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__):
        path = Path(frame.filename)
        if path.is_relative_to(PROJECT_ROOT / "apps") or path.is_relative_to(
            PROJECT_ROOT / "integrations"
        ):
            frames.append(dict(file=path.name, function=frame.name, line=frame.lineno))
    reason = "JOB_STOPPED_BEFORE_COMPLETION"
    if phase == "SOURCE_STARTUP" and type(exc).__name__ == "ProfileError":
        reason = "XHS_PROFILE_UNAVAILABLE"
    elif isinstance(exc, ValueError) and re.fullmatch(
        r"(?:CONFIGURED_|BOUNDED_|GATE_|ROUTE_CHOICES_|CACHE_BODY_)[A-Z0-9_]+", str(exc)
    ):
        reason = str(exc)
    result: dict[str, Any] = dict(reason=reason, phase=phase, exception_type=type(exc).__name__, frames=frames[-5:])
    import sqlite3
    if isinstance(exc, sqlite3.Error):
        result["sqlite_errorcode"] = getattr(exc, "sqlite_errorcode", None)
        name = getattr(exc, "sqlite_errorname", "")
        result["sqlite_errorname"] = name if re.fullmatch(r"SQLITE_[A-Z_]+", name) else None
    return result


def configured_provider() -> OpenAICompatibleProvider:
    provider = OpenAICompatibleProvider.from_env()
    if provider is None or provider.timeout != 120:
        raise ValueError("CONFIGURED_120_SECOND_PROVIDER_REQUIRED")
    return provider


def model_command(
    database: Path, kind: str, identifier: str, *, product: bool = False,
    research_gaps: tuple[str, ...] | None = None,
) -> list[str]:
    extra = []
    if research_gaps is not None:
        if kind != "extract-worker":
            raise ValueError("WORKER_GAP_CONTEXT_DENIED")
        extra = ["--research-gaps", *extraction_gap_ids(research_gaps)]
    if product:
        return [
            sys.executable,
            str(PROJECT_ROOT / "scripts/product_preview.py"),
            kind,
            "--job",
            identifier,
            "--workspace",
            str(database.resolve().parent),
        ] + extra
    return [
        sys.executable,
        str(PROJECT_ROOT / "scripts/live_workbench.py"),
        kind,
        "--database",
        str(database.resolve()),
        "--identifier",
        identifier,
    ] + extra


def extraction_gap_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    """Only bounded program gap identifiers cross the child-process boundary."""
    if len(values) > 32 or any(
        not isinstance(v, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", v)
        for v in values
    ):
        raise ValueError("WORKER_GAP_CONTEXT_DENIED")
    return values


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
        from travel_agent.research.material_eligibility import play_focused

        terms = [
            request.departure,
            request.destination,
            request.time_hint,
            self.focus,
            f"{request.days}天" if request.days else None,
            "玩法 体验 看点 取舍" if play_focused(request) else "路线 行程 交通",
            "不自驾 交通接驳" if request.no_self_drive else None,
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
    reader_holder: dict[str, Any] | None = None,
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
        ordinary = budget.state()["gate"].get("purpose") == "PRIVATE_OPERATION"
        automatic = bool(budget.state()["gate"].get("automatic_task_id"))
        summary: dict[str, Any] = {}
        state = "FAILED"
        if reader_holder is not None:
            reader = reader_holder.get("reader")
        owned = reader is None and reader_holder is None
        already_connected = bool(reader_holder and reader_holder.get("connected"))
        phase = "PROVIDER_CONFIG"

        def progress(stage: str) -> None:
            con.execute(
                "UPDATE preview_jobs SET summary_json=json_set(coalesce(summary_json,'{}'),'$.stage',?) WHERE job_id=? AND status IN ('RUNNING','WAITING_LOGIN')",
                (stage, job_id),
            )
            if stage in {"LOGIN_CHECK", "LOGIN_REQUIRED", "LOGIN_AUTHENTICATED"}:
                con.execute(
                    "UPDATE preview_jobs SET summary_json=json_set(coalesce(summary_json,'{}'),'$.login_state',?) WHERE job_id=?",
                    (stage, job_id),
                )

        def active() -> None:
            if ordinary:
                from travel_agent.planning.workbench import check_active

                check_active(db, budget.state())
            if "route_choices" in data:
                from travel_agent.planning.flow import PlanningService
                from travel_agent.planning.reference_overview import choices, references

                _, latest = PlanningService(db, j["account_scope"]).load(j["session_id"])
                p = latest["planning"]
                if (
                    choices(references(db, j["account_scope"], j["session_id"], p), p)
                    != data["route_choices"]
                ):
                    raise ResearchStopped("ERROR", "ROUTE_CHOICES_CHANGED")
            r = con.execute(
                "SELECT status,cancel_requested FROM preview_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if r[1] or r[0] not in {"RUNNING", "WAITING_LOGIN"}:
                raise ResearchStopped("ERROR", "CANCELED")

        class Permits:
            def before_detail(self) -> None:
                active()
                from travel_agent.planning.agent_contract import COMPLETION_RESERVE

                reserve = COMPLETION_RESERVE if data.get("agent_step") else 1
                if (data.get("planning_protocol") == 2
                    and not has_capacity(budget.summary()["remaining"]["model"], 2 + reserve)):
                    raise ResearchStopped("BUDGET_EXHAUSTED", "PLANNING_MODEL_RESERVED")

            def reserve(self, kind: str, fingerprint: str) -> None:
                active()
                if kind == "DETAIL":
                    self.before_detail()
                budget.reserve(kind, fingerprint)
                progress(
                    {"CONNECT": "LOGIN_CHECK", "SEARCH": "SEARCH", "DETAIL": "READING"}.get(
                        kind, "RESEARCH"
                    )
                )

        try:
            provider = provider or configured_provider()
            if isinstance(provider, OpenAICompatibleProvider):
                budget.check_provider(provider)
            if budget.state()["gate"]["status"] != "PASS":
                raise ValueError("GATE_NOT_PASS")

            def login_prompt() -> None:
                progress("LOGIN_REQUIRED")
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

            if reader is None and not data.get("cached_body_step"):
                from travel_agent.research.live import LiveResearchReader

                phase = "SOURCE_STARTUP"
                progress(phase)
                reader = LiveResearchReader(PROJECT_ROOT, login_prompt=login_prompt,
                    max_search_operations=budget.state()["limits"]["SEARCH"],
                    max_feed_details=budget.state()["limits"]["DETAIL"])
                if reader_holder is not None:
                    reader_holder["reader"] = reader
            phase = "COVERAGE_SETUP"
            before = {r[0] for r in con.execute("SELECT claim_id FROM claims")}

            def dispatch(attempt: str, gaps: tuple[str, ...]) -> dict[str, Any]:
                active()
                source = con.execute(
                    "SELECT c.source_id FROM extraction_attempts a JOIN source_contents c USING(content_id) WHERE attempt_id=?",
                    (attempt,),
                ).fetchone()[0]
                budget.reserve("MODEL", "extract:" + source)
                progress("EXTRACT")
                if extract_dispatch:
                    return dict(extract_dispatch(store, attempt, gaps))
                return supervise_reserved(
                    database,
                    attempt,
                    provider=provider,
                    deadline=180,
                    finish_report=False,
                    command=model_command(
                        database, "extract-worker", attempt, product=product, research_gaps=gaps
                    ),
                )

            def after(out: dict[str, Any]) -> None:
                active()
                if data.get("cached_body_step"):
                    from travel_agent.research.cached_reprocess import validate

                    validate(store, j, data["cached_body_step"])
                progress("REVIEW")
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
                # A completed review with no accepted activity is not a transport error.
                # Continue to the next distinct source within this grant, never re-review it.
                out["continue_after_pending_review"] = data.get("planning_protocol") == 2 and (
                    ordinary or j["continuation_id"] == "p051-scope-locked-planning"
                )

            if data.get("cached_body_step"):
                from travel_agent.research.cached_reprocess import analyze

                phase = "CACHE_BODY_ANALYSIS"
                progress(phase)
                state, summary = analyze(store, j, data,
                    ExtractionRecovery(store, EvidenceExtractor(provider, protocol_version=3)),
                    budget, dispatch, after, active)
                return

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
                model_max_attempts=budget.state()["limits"]["DETAIL"]
                if ordinary
                else 2
                if data.get("planning_protocol") == 2
                and j["continuation_id"] == "p051-scope-locked-planning"
                else 1,
                continuation=Permits(),
                extraction_dispatch=dispatch,
                after_extraction=after,
                activity_target=activity_target if product and not automatic else None,
                adaptive_queries=automatic,
                deadline_seconds=2700 if automatic else None,
                on_connected=lambda: progress("LOGIN_AUTHENTICATED"),
                already_connected=already_connected,
                detail_number_offset=budget.summary()["used"]["detail"] if data.get("agent_step") else 0,
                adaptive_candidate_selection=bool(data.get("agent_step", {}).get("multi_body")),
                before_detail=Permits().before_detail,
                attempted_detail_hashes={r[0] for r in con.execute(
                    "SELECT fingerprint FROM continuation_operations WHERE continuation_id=? AND kind='DETAIL'",
                    (j["continuation_id"],),
                )} if data.get("agent_step") else None,
            )
            service.planner = FocusedPlanner(data["focus"])
            coverage_evaluator = None
            if automatic:
                from travel_agent.planning.flow import PlanningService
                from travel_agent.research.advisory_coverage import (
                    CoverageEvaluator,
                    CoveragePlanner,
                    REVIEWED,
                )
                from travel_agent.domain.models import EvidenceBundle

                _, current_state = PlanningService(db, j["account_scope"]).load(j["session_id"])
                from travel_agent.planning.reference_overview import (
                    focused,
                    choices,
                    references as route_references,
                )

                route_rows = route_references(
                    db, j["account_scope"], j["session_id"], current_state["planning"]
                )
                if "route_choices" in data and data["route_choices"] != choices(
                    route_rows, current_state["planning"]
                ):
                    raise ResearchStopped("ERROR", "ROUTE_CHOICES_CHANGED")
                base_refs = focused(route_rows, current_state["planning"])

                def filtered(evidence: Any) -> Any:
                    # Only this task's newly read bodies enter extraction coverage.
                    # Historical cards are separately revalidated above; no global raw fallback.
                    allowed = {
                        r[0]
                        for r in con.execute(
                            "SELECT DISTINCT c.source_id FROM research_runs r JOIN research_run_contents rc USING(run_id) JOIN source_contents c USING(content_id) WHERE r.research_id=? AND c.account_scope=?",
                            (j["research_id"], j["account_scope"]),
                        )
                    }
                    result = []
                    for b in evidence:
                        if b["source_id"] not in allowed:
                            continue
                        claims = [
                            c
                            for c in b["claims"]
                            if b["claim_metadata"]
                            .get(c["claim_id"], {})
                            .get("context_review_status")
                            in REVIEWED
                        ]
                        if claims:
                            result.append(
                                EvidenceBundle(
                                    b.to_dict()
                                    | {
                                        "claims": claims,
                                        "claim_metadata": {
                                            c["claim_id"]: b["claim_metadata"][c["claim_id"]]
                                            for c in claims
                                        },
                                    }
                                )
                            )
                    return tuple(result)

                service.evidence_filter = filtered
                coverage_evaluator = CoverageEvaluator(
                    base_refs,
                    j["account_scope"],
                    j["research_id"],
                    data.get("spatial_intent", "UNDECIDED"),
                    db.clock,
                    require_activity_content=budget.state()["gate"].get("consent") == "PRIVATE_GOAL_AGENT_V5",
                    perspective_gap=data.get("agent_step", {}).get("gap_key"),
                )
                service.evaluator = coverage_evaluator
                service.planner = CoveragePlanner(data["focus"], has_cache=bool(base_refs))
            if data.get("agent_step"):
                step = data["agent_step"]
                class AgentQuery(QueryPlanner):
                    def plan(self, request: Any, evidence: Any, gaps: Any, previous: Any) -> Any:
                        if previous:
                            return ()
                        return (SearchQuery(step["query"], (step["gap_key"],), "模型按当前缺口选择的一次业务查询"),)
                service.planner = AgentQuery()
            if product and data.get("planning_protocol") == 2:
                from travel_agent.planning.spatial import ScopedSelector

                service.selector = ScopedSelector(data.get("spatial_intent", "UNDECIDED"))
            phase = "RESEARCH"
            report = service.run(
                ResearchRequest(**data["request"]),
                research_id=j["research_id"],
                revision=0,
                account_scope=j["account_scope"],
                budget=ResearchBudget(
                    1 if data.get("agent_step") else budget.state()["limits"]["SEARCH"],
                    data["agent_step"].get("max_body", 1) if data.get("agent_step") else budget.state()["limits"]["DETAIL"],
                ),
            )
            if reader_holder is not None and budget.summary()["used"]["connect"]:
                reader_holder["connected"] = True
            accepted = {c["claim_id"] for b in report.evidence for c in b["claims"]} - before
            counts = [o.get("counts", {}) for o in service.extraction_attempts]
            summary = {
                **json.loads(
                    con.execute(
                        "SELECT summary_json FROM preview_jobs WHERE job_id=?", (job_id,)
                    ).fetchone()[0]
                    or "{}"
                ),
                "new_evidence_count": len(accepted),
                "reviewed": len(accepted),
                "pending": sum(c.get("context_review_pending", 0) for c in counts),
                "rejected": sum(c.get("rejected_candidates", 0) for c in counts),
                "reason": report.diagnostic,
                "report": report.safe_summary(),
                "budget": budget.summary(),
                "unique_candidate_count": len(service.unique_candidates),
                "candidate_source_ids": sorted(service.unique_candidates) if data.get("agent_step") else [],
                "duplicate_body_count": service.duplicate_bodies,
                "source_skips": service.source_skips,
                "query_progress": [
                    {k: v for k, v in q.items() if not k.startswith("_") and k != "detail_before"}
                    for q in service.query_progress
                ],
            }
            if coverage_evaluator:
                summary["advisory_coverage"] = coverage_evaluator.last
                summary["research_stop"] = report.stop_reason
            if report.stop_reason == "NEED_LOGIN":
                summary["login_state"] = "EXPIRED_OR_REQUIRED"
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
        except Exception as exc:
            summary.update(
                json.loads(
                    con.execute(
                        "SELECT summary_json FROM preview_jobs WHERE job_id=?", (job_id,)
                    ).fetchone()[0]
                    or "{}"
                )
            )
            summary["failure"] = failure_diagnostic(exc, phase)
            summary["reason"] = summary["failure"]["reason"]
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
                            "SEARCH_2",
                            "SEARCH_3",
                            "DETAIL_1",
                            "DETAIL_2",
                            "DETAIL_3",
                            "DETAIL_4",
                            "DETAIL_5",
                            "DETAIL_6",
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
            if state in {"COMPLETED", "PARTIAL"} and summary.get("new_evidence_count"):
                try:
                    from travel_agent.knowledge.organize import after_research

                    summary["knowledge_organized"] = after_research(
                        db, j["account_scope"], j["session_id"], j["research_id"]
                    )
                except ValueError:
                    summary["knowledge_status"] = "NEEDS_ORGANIZE"
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


def extract_worker(
    store: EvidenceStore, provider: OpenAICompatibleProvider, attempt: str, *,
    research_gaps: tuple[str, ...] = (),
) -> None:
    research_gaps = extraction_gap_ids(research_gaps)
    a = store.db.connection.execute(
        "SELECT a.*,c.source_id FROM extraction_attempts a JOIN source_contents c USING(content_id) WHERE attempt_id=?",
        (attempt,),
    ).fetchone()
    if not a or a["extraction_version"] != 3 or a["attempt_number"] != 1:
        raise ValueError("WORKER_PROTOCOL_DENIED")
    budget = BoundedBudget(store, a["batch_id"])
    budget.check_provider(provider)
    budget.check_permit("MODEL", "extract:" + a["source_id"])
    cached = store.db.connection.execute(
        "SELECT j.* FROM preview_jobs j JOIN research_runs r USING(research_id) WHERE r.run_id=? AND j.continuation_id=?",
        (a["run_id"], a["batch_id"]),
    ).fetchone()
    if cached and (step := json.loads(cached["request_json"]).get("cached_body_step")):
        from travel_agent.research.cached_reprocess import validate

        validate(store, cached, step)
        if research_gaps != tuple(step["gaps"]):
            raise ValueError("CACHE_BODY_TASK_BINDING_DENIED")
    research = store.db.connection.execute(
        "SELECT research_id FROM research_runs WHERE run_id=?", (a["run_id"],)
    ).fetchone()[0]
    def guard() -> None:
        budget.check_job_active(research)
        from travel_agent.research.cached_reprocess import validate_attempt

        validate_attempt(store, attempt)

    ExtractionRecovery(store, EvidenceExtractor(provider, protocol_version=3)).run_reserved(
        attempt,
        research_gaps=research_gaps,
        dispatch_guard=guard,
    )
