"""One explicitly opted-in T05 experiment with a durable, non-resettable local ledger."""

import argparse
from dataclasses import asdict, replace
from importlib.metadata import version
import json
import logging
from pathlib import Path
import platform
from typing import Any

from xhs_sidecar.live_smoke import AuditCounter
from xhs_sidecar.resource_policy import ResourcePolicy

from travel_agent.domain.models import SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider

from .extractor import EvidenceExtractor
from .live import LiveResearchReader
from .models import ResearchBudget, ResearchRequest
from .service import ResearchService
from .store import EvidenceStore

QUERY = "成都 川西 国庆 攻略"


def temporary_policy() -> SourcePolicy:
    return SourcePolicy({
        "policy_id": "xhs-current-experiment-only", "version": 1, "basis": "UNKNOWN",
        "basis_note": "用户明确授权当前只读实验；第三方内容长期用途尚未核实",
        "allow_read": True, "allow_inference": True,
        "allow_external_model": False, "allow_persist_metadata": False,
        "allow_persist_raw": False, "allow_persist_derived": False,
        "allow_embed": False, "allow_export": False, "reviewed_at": None, "expires_at": None,
    })


def run_smoke(project: Path) -> dict[str, Any]:
    output = project / ".local/t05-smoke/summary.json"
    if output.exists():
        # Fail closed even for interrupted/login-blocked experiments. No automatic rerun.
        raise RuntimeError("已有 T05 实站实验记录，不得重启重置额度")
    result: dict[str, Any] = {
        "experiment": "T04.2_T05", "attempted": True, "query": QUERY,
        "budget": {"max_search_operations": 1, "max_feed_details": 2},
        "business_operations": {"search": 0, "detail": 0},
        "status": "STARTING", "closed": False,
        "environment": {"os": platform.platform(), "python": platform.python_version(),
                        "playwright": version("playwright"), "browser_type": "chromium",
                        "channel": None, "headless": False, "args": [], "no_viewport": True,
                        "persistent_context": True},
        "storage": "EPHEMERAL_MEMORY_ONLY_SOURCE_POLICY_UNKNOWN",
        "model": "NOT_CONFIGURED", "full_body_persisted": False,
    }

    def save() -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        pending = output.with_suffix(".tmp")
        pending.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        pending.replace(output)

    def checkpoint(operations: dict[str, int]) -> None:
        result["business_operations"] = dict(operations)
        save()  # Failure here prevents dispatch.
        print(json.dumps({"stage": "BUDGET_RESERVED", "operations": operations}), flush=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    reader: LiveResearchReader | None = None
    db: Database | None = None
    try:
        provider = OpenAICompatibleProvider.from_env()
        result["model"] = "CONFIGURED_BUT_POLICY_BLOCKED" if provider else "NOT_CONFIGURED"
        reader = LiveResearchReader(project, resource_policy=ResourcePolicy.TEXT_FIRST)
        audit = AuditCounter()
        reader.login.audit.logger.handlers = [audit]
        reader.login.audit.logger.propagate = False
        reader.login.audit.logger.setLevel(logging.INFO)
        db = Database(Path(":memory:"))
        store = EvidenceStore(db, temporary=True)
        service = ResearchService(store, reader, EvidenceExtractor(provider), temporary_policy(),
                                  checkpoint=checkpoint, temporary_read_allowed=True)
        request = ResearchRequest(departure="成都", destination="川西", time_hint="国庆")
        first = service.run(request, research_id="t05-live", revision=0,
                            account_scope="current-private-profile", budget=ResearchBudget(1, 2))
        # Keep the actual material view in memory only; never export real source excerpts.
        material_view = first.material_view()
        result["material_sections"] = {key: len(value)
                                       for key, value in material_view["materials"].items()}
        result["first"] = first.safe_summary()
        result["business_operations"] = first.operations
        result["login"] = {
            "profile_present_at_start": reader.profile_present_at_start,
            "status": reader.login_state, "connect_calls": reader.connect_calls,
            "browser_sessions": reader.browser.sessions_created,
            "account_identity": reader.login.status().account_identity,
        }
        result["environment"].update(reader.browser_info)
        result["details"] = reader.detail_summaries
        result["detail_diagnostic"] = reader.backend.detail_diagnostic
        result["read_diagnostic"] = reader.backend.last_read_diagnostic
        result["policy"] = reader.backend.resource_policy.snapshot()
        # Close before cache runs so background page traffic cannot masquerade as zero.
        reader.close()
        before = reader.observer.snapshot().total_requests
        connect_before = reader.connect_calls
        cached = service.run(request, research_id="t05-live", revision=0,
                             account_scope="current-private-profile", budget=ResearchBudget(0, 0))
        incremental = service.run(replace(request, days=5, no_self_drive=True),
                                  research_id="t05-live", revision=1,
                                  account_scope="current-private-profile", budget=ResearchBudget(0, 0))
        result["cache"] = cached.safe_summary()
        result["incremental"] = incremental.safe_summary()
        after = reader.observer.snapshot().total_requests
        result["cache_validation"] = {
            "browser_closed_before_calls": True,
            "connect_delta": reader.connect_calls - connect_before,
            "context_request_event_delta": after - before
            if before is not None and after is not None else None,
            "evidence_reused": len(cached.evidence) == len(first.evidence) and bool(first.evidence),
            "incremental_evidence_reused": len(incremental.evidence) == len(first.evidence)
            and bool(first.evidence),
            "persistent_cross_process_cache": "NOT_TESTED_SOURCE_POLICY_BLOCKED",
        }
        result["audit"] = {"lines": audit.lines, "unrecognized": audit.unrecognized,
                           "sentinel_matches": audit.sentinel_matches}
        result["status"] = "LIVE_TEST_BLOCKED" if first.stop_reason in {
            "NEED_LOGIN", "VERIFICATION_REQUIRED", "SOURCE_UNAVAILABLE", "ERROR",
        } else "COMPLETED_WITH_GAPS" if first.gaps else "COMPLETED"
    except Exception:
        result["status"] = "LIVE_TEST_BLOCKED"
        result["error"] = "LOCAL_EXPERIMENT_ERROR"
    finally:
        if reader is not None:
            try:
                reader.close()
            except Exception:
                result["cleanup_error"] = "CLEANUP_FAILED"
            result["closed"] = reader.closed
            try:
                result["profile_preserved"] = reader.profile.exists()
                result["network"] = {
                    label: asdict(reader.observer.snapshot(None if label == "TOTAL" else label))
                    for label in ("TOTAL", "LOGIN", "SEARCH", "DETAIL_1", "DETAIL_2", "OUTSIDE_WINDOW")
                }
            except Exception:
                result["final_observation_error"] = "NOT_MEASURED"
        if db is not None:
            db.connection.close()
        result["safety"] = {"platform_content_writes": 0, "comment_expansions": 0,
                            "image_analysis": False, "raw_body_exported": False,
                            "automatic_login_retries": 0, "disconnect_called": False}
        save()
    return result


def main(project: Path) -> int:
    parser = argparse.ArgumentParser(description="T05 单轮 1 search / 2 detail 验证，结束保留 profile")
    parser.add_argument("--live", action="store_true", help="显式授权本轮真实普通浏览器读取")
    args = parser.parse_args()
    if not args.live:
        print("未启用真实访问；仅完成本地入口检查。")
        return 0
    try:
        result = run_smoke(project)
    except Exception:
        print(json.dumps({"status": "BLOCKED", "error": "EXISTING_RUN_OR_SETUP_ERROR"}), flush=True)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 2 if result["status"] == "LIVE_TEST_BLOCKED" or not result["closed"] else 0
