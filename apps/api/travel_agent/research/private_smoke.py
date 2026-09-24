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
from .models import ResearchBudget, ResearchRequest, ResearchStopped
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
        if result.mode != "LLM":
            # Business code still supports safe fallback; the live gate must not
            # consume further site reads after model/schema failure.
            raise ResearchStopped("ERROR", "LIVE_LLM_EXTRACTION_FAILED")
        return result


class LimitedSelector(CandidateSelector):
    def select(self, *args: Any, **kwargs: Any) -> Any:
        return super().select(*args, **kwargs)[:3]


def run_live(project: Path, *, login_prompt: Any = None) -> dict[str, Any]:
    # Imports are below explicit opt-in; cache probe never imports these modules.
    from xhs_sidecar.live_smoke import AuditCounter
    from xhs_sidecar.resource_policy import ResourcePolicy
    from .live import LiveResearchReader

    folder = project / ".local/t06.1-private"
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
        "budget": {"search": 1, "detail": 3}, "operations": {"search": 0, "detail": 0},
        "network_policy": "OBSERVE_ONLY", "closed": False,
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
        reader = LiveResearchReader(project, resource_policy=ResourcePolicy.OBSERVE_ONLY,
                                    login_prompt=login_prompt)
        audit = AuditCounter()
        reader.login.audit.logger.handlers = [audit]
        reader.login.audit.logger.propagate = False
        reader.login.audit.logger.setLevel(logging.INFO)
        with Database(folder / "research.sqlite3") as db:
            store = EvidenceStore(db)
            policy = private_policy(SCOPE)
            extractor = ObservedExtractor(provider)
            service = ResearchService(store, reader, extractor, policy, selector=LimitedSelector(),
                                      checkpoint=checkpoint)
            request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
            report = service.run(request, research_id=RESEARCH_ID, revision=0,
                                 account_scope=SCOPE, budget=ResearchBudget(1, 3))
            result["first"] = report.safe_summary()
            result["operations"] = report.operations
            result["queries"] = sorted(store.queries(RESEARCH_ID))
            result["selection"] = [{"source": f"S{i}", "reason": choice.reason,
                                    "metadata_used": list(choice.metadata_used)}
                                   for i, choice in enumerate(report.selection, 1)]
            result["extractions"] = extractor.results
            contents = {b["source_id"]: store.contents.load(b["source_id"], SCOPE) for b in report.evidence}
            result["source_contents"] = [
                {"source": f"S{i}", "snapshots": len(contents[b["source_id"]]),
                 "blocks": sum(len(c["body_blocks"]) for c in contents[b["source_id"]]),
                 "normalized_chars": [len(c["normalized_text"]) for c in contents[b["source_id"]]],
                 "completeness": b["completeness"],
                 **audit_grounding(b, contents[b["source_id"]])}
                for i, b in enumerate(report.evidence, 1)
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
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"status": "NOT_RUN", "live_operations": 0}))
        return 0
    def prompt() -> None:
        print("现在请在打开的小红书官方页面完成正常登录。完成后按回车；不要提供 Cookie 或 token。", flush=True)
        input()
    try:
        result = run_live(PROJECT_ROOT, login_prompt=prompt)
    except Exception:
        result = {"status": "LIVE_TEST_BLOCKED", "error": "LOCAL_SETUP_ERROR"}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result["status"] == "FIRST_ROUND_RECORDED" else 2
