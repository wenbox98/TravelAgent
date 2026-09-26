"""One durable 1-search/3-detail experiment; summary logs never contain source bodies."""

import argparse
from dataclasses import asdict
import json
import logging
import os
from pathlib import Path
import re
from typing import Any

from travel_agent.domain.source_policy import private_policy
from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.settings import PROJECT_ROOT

from .content_store import audit_grounding
from .extractor import EvidenceExtractor, ExtractionResult
from .models import ResearchBudget, ResearchRequest
from .planning import CandidateSelector
from .reporting import render_private_report
from .service import ResearchService
from .store import EvidenceStore

SCOPE = "current-private-profile"
RESEARCH_ID = "t061-private-live"


class ObservedExtractor(EvidenceExtractor):
    def __init__(self, provider: OpenAICompatibleProvider) -> None:
        super().__init__(provider)
        self.results: list[dict[str, object]] = []

    def extract(self, **kwargs: Any) -> ExtractionResult:
        result = super().extract(**kwargs)
        self.results.append(result.safe_summary())
        print(json.dumps({"stage": "EXTRACTION", "detail": len(self.results),
                          **result.safe_summary()}, ensure_ascii=True), flush=True)
        return result


class LimitedSelector(CandidateSelector):
    def select(self, *args: Any, **kwargs: Any) -> Any:
        return super().select(*args, **kwargs)[:3]


def run_live(project: Path, *, login_prompt: Any = None, t062: bool = False,
             after_extraction: Any = None, t065: bool = False) -> dict[str, Any]:
    # Imports are below explicit opt-in; cache probe never imports these modules.
    from xhs_sidecar.live_smoke import AuditCounter
    from xhs_sidecar.resource_policy import ResourcePolicy
    from .live import LiveResearchReader

    folder = project / (".local/t06.5-live" if t065 else ".local/t06.2-live" if t062 else ".local/t06.1-private")
    database = project / ".local/t06.2-live/research.sqlite3" if t065 else folder / "research.sqlite3"
    research_id = "t065-coverage-first-plan" if t065 else "t062-private-live" if t062 else RESEARCH_ID
    if t065 and (not database.is_file() or after_extraction is None):
        return {"status": "BLOCKED", "reason": "CONTINUATION_REQUIRES_CACHE_AND_WORK_REVIEW"}
    detail_limit = 2 if t065 else 3
    if t062:
        synthetic = project / ".local/t06.2-synthetic"
        proof = synthetic / ("retry.json" if (synthetic / "retry.json").exists() else "attempt.json")
        if not proof.is_file() or json.loads(proof.read_text(encoding="utf-8")).get("status") != "SUCCEEDED":
            return {"status": "BLOCKED", "reason": "SYNTHETIC_EXTRACTION_NOT_PASSED"}
        if after_extraction is None:
            return {"status": "BLOCKED", "reason": "WORK_REVIEW_CHECKPOINT_REQUIRED"}
    ledger = folder / "attempt.json"
    if ledger.exists():
        return {"status": "BLOCKED", "reason": "EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY"}
    provider = OpenAICompatibleProvider.from_env()
    if provider is None:
        return {"status": "BLOCKED", "reason": "LLM_NOT_CONFIGURED"}
    # Configuration was already smoke-tested by the operator; no new connectivity call.
    folder.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "status": "STARTED", "pid": os.getpid(), "g1": "NOT_EVALUATED", "g0": "PASS_PREVIOUSLY",
        "mode": "PRIVATE_LOCAL_RESEARCH", "retention": "PERSISTENT",
        "provider": "OpenAICompatibleProvider", "response_format": provider.response_format,
        "model": provider.model if re.fullmatch(r"[A-Za-z0-9._:/-]{1,160}", provider.model)
        and provider.api_key.get_secret_value() not in provider.model else "REDACTED",
        "budget": {"search": 1, "detail": detail_limit}, "operations": {"search": 0, "detail": 0},
        "network_policy": "OBSERVE_ONLY", "closed": False,
        "research_id": research_id, "model_budget": 2 if t065 else 4,
        "historical_failed_run": "t062-private-live" if t065 else RESEARCH_ID if t062 else None,
    }
    try:
        with ledger.open("x", encoding="utf-8") as handle:
            json.dump(result, handle)
    except FileExistsError:
        return {"status": "BLOCKED", "reason": "EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY"}

    def save() -> None:
        pending = ledger.with_suffix(".tmp")
        pending.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        pending.replace(ledger)

    def checkpoint(operations: dict[str, int]) -> None:
        result["operations"] = dict(operations)
        save()  # A failed reservation checkpoint prevents dispatch.
        print(json.dumps({"stage": "BUDGET_RESERVED", "operations": operations}), flush=True)

    reader = None
    try:
        with Database(database) as db:
            store = EvidenceStore(db)
            continuation = None
            dispatch = None
            request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
            if t065:
                from .continuation import ContinuationBudget
                from .planning import QueryPlanner, SufficiencyEvaluator
                from .retry import supervise_continuation
                continuation = ContinuationBudget(store)
                continuation.grant(SCOPE, "t062-private-live", provider)
                continuation.start()
                cached = store.lookup("t062-private-live", request.destination, SCOPE)
                gaps = SufficiencyEvaluator(clock=db.clock).gaps(request, cached)
                planned = QueryPlanner().plan(request, cached, gaps, store.queries("t062-private-live"))
                plan = {"cache_before_connect": True, "cached_evidence": sum(len(b["claims"]) for b in cached),
                    "known": "已有带年份、自驾及未游览条件的局部体验，尚无已接纳的整趟路线和时长",
                    "gaps": [g.gap_id for g in gaps], "query": planned[0].text if planned else None,
                    "purpose": planned[0].purpose if planned else None,
                    "selection": "只依据标题、类型和详情可读性选择；行程/天数/交通为预期补缺信号，未读正文；兼顾标题多样性"}
                (folder / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
                result["plan"] = plan
                save()
                def dispatch(attempt: str, gaps: tuple[str, ...]) -> dict[str, Any]:
                    return supervise_continuation(store, attempt, gaps, provider)
            reader = LiveResearchReader(project, resource_policy=ResourcePolicy.OBSERVE_ONLY,
                                        login_prompt=login_prompt)
            audit = AuditCounter()
            reader.login.audit.logger.handlers = [audit]
            reader.login.audit.logger.propagate = False
            reader.login.audit.logger.setLevel(logging.INFO)
            policy = (store._latest_policy("private-local-research-" + SCOPE) if t065 else private_policy(SCOPE))
            if policy is None:
                raise ValueError("CONTINUATION_POLICY_MISSING")
            extractor = ObservedExtractor(provider)
            service = ResearchService(store, reader, extractor, policy, selector=LimitedSelector(),
                                      checkpoint=checkpoint, model_batch_id=research_id,
                                      model_max_attempts=2 if t065 else 4, after_extraction=after_extraction,
                                      continuation=continuation, extraction_dispatch=dispatch)
            report = service.run(request, research_id=research_id, revision=0,
                                 account_scope=SCOPE, budget=ResearchBudget(1, detail_limit))
            if continuation is not None:
                continuation.finish()
                result["continuation"] = continuation.summary()
            result["first"] = report.safe_summary()
            result["operations"] = report.operations
            result["queries"] = sorted(store.queries(research_id))
            result["selection"] = [{"source": f"S{i}", "reason": choice.reason,
                                    "metadata_used": list(choice.metadata_used)}
                                   for i, choice in enumerate(report.selection, 1)]
            result["extractions"] = extractor.results
            result["model_attempts"] = service.extraction_attempts
            saved = [store.repository.get(row[0], SCOPE) for row in db.connection.execute(
                "SELECT DISTINCT source_id FROM source_contents WHERE account_scope=?", (SCOPE,))]
            saved = [b for b in saved if b is not None]
            contents = {b["source_id"]: store.contents.load(b["source_id"], SCOPE) for b in saved}
            result["source_contents"] = [
                {"source": f"S{i}", "snapshots": len(contents[b["source_id"]]),
                 "blocks": sum(len(c["body_blocks"]) for c in contents[b["source_id"]]),
                 "normalized_chars": [len(c["normalized_text"]) for c in contents[b["source_id"]]],
                 "completeness": b["completeness"],
                 **audit_grounding(b, contents[b["source_id"]])}
                for i, b in enumerate(saved, 1)
            ]
            if report.evidence:
                # The local generated report contains only short accepted excerpts;
                # inspect before copying a reviewable report into tracked reports/.
                sources = [b.to_dict() for b in report.evidence]
                (folder / "travel-example.md").write_text(
                    render_private_report(report.material_view(), sources), encoding="utf-8")
            result["login"] = {"state": reader.login_state, "connect_calls": reader.connect_calls,
                               "browser_sessions": reader.browser.sessions_created,
                               "profile_present_at_start": reader.profile_present_at_start}
            result["details"] = reader.detail_summaries
            result["browser"] = reader.browser_info
            result["audit"] = {"lines": audit.lines, "unrecognized": audit.unrecognized,
                               "sentinel_matches": audit.sentinel_matches}
            result["status"] = "FIRST_ROUND_RECORDED" if report.evidence else "LIVE_TEST_BLOCKED"
            if report.diagnostic == "LIVE_LLM_EXTRACTION_FAILED":
                result["status"] = "FAIL"
    except Exception:
        result.update(status="LIVE_TEST_BLOCKED", error="LOCAL_EXPERIMENT_ERROR")
    finally:
        if reader is not None:
            try:
                reader.close()  # Retains profile; never disconnect.
                result["closed"] = reader.closed
                result["profile_preserved"] = reader.profile.exists()
                result["network"] = {
                    label: asdict(reader.observer.snapshot(None if label == "TOTAL" else label))
                    for label in ("TOTAL", "LOGIN", "SEARCH", "DETAIL_1", "DETAIL_2", "DETAIL_3", "OUTSIDE_WINDOW")
                }
            except Exception:
                result["cleanup_error"] = "CLEANUP_FAILED"
        save()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="T06.1 私人本机真实研究验收，固定最多 1 搜索 / 3 详情")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--t062", action="store_true")
    parser.add_argument("--t065", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"status": "NOT_RUN", "live_operations": 0}))
        return 0
    def prompt() -> None:
        print("现在请在打开的小红书官方页面完成正常登录。完成后按回车；不要提供 Cookie 或 token。", flush=True)
        input()
    def review(outcome: dict[str, Any]) -> None:
        print(json.dumps({"stage": "WORK_REVIEW_REQUIRED", "attempt_id": outcome["attempt_id"]}), flush=True)
        if input().strip() != "REVIEWED":
            raise ValueError("WORK_REVIEW_NOT_ACCEPTED")
    try:
        if args.t065:
            os.environ["LLM_TIMEOUT_SECONDS"] = "120"
        result = run_live(PROJECT_ROOT, login_prompt=prompt, t062=args.t062,
                          after_extraction=review if args.t062 or args.t065 else None, t065=args.t065)
    except Exception:
        result = {"status": "LIVE_TEST_BLOCKED", "error": "LOCAL_SETUP_ERROR"}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["status"] == "FIRST_ROUND_RECORDED" else 2
