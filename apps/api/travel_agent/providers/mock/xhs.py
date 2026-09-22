from datetime import datetime, timezone
import json
from travel_agent.domain.models import FetchResult
from travel_agent.settings import PROJECT_ROOT


def metrics(**values):
    return {"search_ops": 0, "detail_ops": 0, "auth_probes": 0, "page_navigations": None, "site_http_requests": None, "network_measurement": "UNAVAILABLE", "image_fetches": 0, "model_calls": 0, "unique_notes_read": 0, "duplicate_fetches_avoided": 0, "cache_hits": 0, "cache_misses": 0, "candidate_count": 0, "selected_candidate_count": 0, "evidence_count": 0} | values


class MockXhsReadonlyAdapter:
    """Fixed synthetic corpus; no transport, credentials or real-site fallback."""
    SCENARIOS = {"OK", "PARTIAL", "SUMMARY_ONLY", "EMPTY", "NEED_LOGIN", "VERIFICATION_REQUIRED", "RATE_LIMITED", "NETWORK_ERROR", "CONTENT_UNAVAILABLE", "PARSE_ERROR", "CONTRACT_ERROR", "CANCELED", "ACCESS_POLICY_BLOCKED", "UNSUPPORTED"}

    def __init__(self, *, clock=None, scenario="OK"):
        if scenario not in self.SCENARIOS:
            raise ValueError("未知合成场景")
        self.clock = clock or (lambda: datetime(2026, 9, 22, tzinfo=timezone.utc))
        self.scenario = scenario
        self.pool = json.loads((PROJECT_ROOT / "fixtures/research-pool.json").read_text(encoding="utf-8"))
        if self.pool["is_synthetic"] is not True or any(n["candidate"]["is_synthetic"] is not True for n in self.pool["notes"]):
            raise ValueError("mock 只允许合成资料")

    def result(self, status, *, candidates=None, evidence=None, **counts):
        return FetchResult({"status": status, "candidates": candidates or [], "evidence": evidence or [], "metrics": metrics(**counts), "message": "合成演示：未访问真实小红书"})

    def search(self, query):
        if not isinstance(query, str) or not query.strip():
            return self.result("CONTRACT_ERROR")
        if self.scenario not in {"OK", "PARTIAL", "SUMMARY_ONLY"}:
            return self.result(self.scenario, search_ops=1)
        candidates = [note["candidate"] for note in self.pool["notes"]]
        return self.result("OK" if self.scenario == "OK" else "PARTIAL", candidates=candidates, search_ops=1, candidate_count=len(candidates))

    def detail(self, note_handle):
        note = next((n for n in self.pool["notes"] if n["candidate"]["note_handle"] == note_handle), None)
        if note is None:
            return self.result("CONTRACT_ERROR")
        if self.scenario not in {"OK", "PARTIAL", "SUMMARY_ONLY"}:
            return self.result(self.scenario, detail_ops=1)
        if note["labels"]["unavailable"]:
            return self.result("CONTENT_UNAVAILABLE", detail_ops=1)
        completeness = {"OK": "FULL_TEXT", "PARTIAL": "PARTIAL_TEXT", "SUMMARY_ONLY": "SUMMARY_ONLY"}[self.scenario]
        if note["labels"]["metadata_only"]:
            completeness = "METADATA_ONLY"
        candidate = note["candidate"]
        claims = [] if completeness == "METADATA_ONLY" else [{"claim_id": "claim-" + candidate["source_id"], "source_id": candidate["source_id"], "topic": note["labels"]["topic"], "text": note["fixture_detail"] if completeness == "FULL_TEXT" else "合成资料片段，仅用于完整度边界测试。", "kind": "AUTHOR_OPINION", "locator": "summary:1" if completeness == "SUMMARY_ONLY" else "text:paragraph-1", "support": "SUPPORTED" if completeness == "FULL_TEXT" else "PARTIAL", "confidence": None, "valid_from": None, "valid_until": None}]
        evidence = {"source_id": candidate["source_id"], "source_type": "SYNTHETIC", "source_title": candidate["title"], "destination": "合成甲区域", "applicable_conditions": [], "completeness": completeness, "fetched_at": self.clock().isoformat(), "source_published_at": candidate["published_at"], "travel_occurred_at": None, "policy_id": "synthetic-all", "claims": claims, "missing_fields": ["真实旅行日期"], "is_synthetic": True}
        return self.result("OK" if completeness == "FULL_TEXT" else "PARTIAL", evidence=[evidence], detail_ops=1, evidence_count=1, unique_notes_read=int(completeness in {"FULL_TEXT", "PARTIAL_TEXT"}))
