"""One opt-in real-model call with synthetic content only; never imports XHS/browser."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import monotonic
from typing import Any
from unittest.mock import patch
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from travel_agent.domain.models import SourcePolicy  # noqa: E402
from travel_agent.providers import llm  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402

BODY = ("合成青岚环线连接虚构雾谷和镜湖。\n"
        "合成青岚环线的体验是湖畔步行。\n"
        "合成青岚环线：作者本次自驾安排五天。\n"
        "合成青岚环线：作者没有提供公共交通、票价和具体旅行日期。")


class ObservedProvider:
    is_external = True
    is_mock = False

    def __init__(self, provider: llm.OpenAICompatibleProvider):
        self.provider = provider
        self.calls = 0
        self.error: str | None = None
        self.schema_validated = False

    def structured(self, task, payload, schema):
        self.calls += 1
        if self.calls > 1:
            raise llm.LLMError("LLM_POLICY_BLOCKED")
        try:
            result = self.provider.structured(task, payload, schema)
            self.schema_validated = True
            return result
        except llm.LLMError as error:
            self.error = error.code
            raise


def safe_model_name(provider: llm.OpenAICompatibleProvider) -> str:
    name = provider.model
    return name if (re.fullmatch(r"[A-Za-z0-9._:/-]{1,160}", name)
                    and provider.api_key.get_secret_value() not in name) else "REDACTED"


def run_check(provider: llm.OpenAICompatibleProvider) -> dict[str, Any]:
    """A successful local fallback never counts as a successful real-model smoke."""
    observed = ObservedProvider(provider)
    now = datetime.now(timezone.utc).isoformat()
    policy = SourcePolicy({
        "policy_id": "t061-synthetic-model-check", "version": 1, "basis": "SYNTHETIC",
        "basis_note": "本测试自行编写的虚构正文，仅用于真实模型连通性验证",
        "allow_read": True, "allow_inference": True, "allow_external_model": True,
        "allow_persist_metadata": True, "allow_persist_derived": True, "allow_export": True,
        "allow_persist_raw": False, "allow_embed": False, "reviewed_at": now, "expires_at": None,
    })
    transport: dict[str, Any] = {"http_attempts": 0, "http_status": None,
                               "transport_error": None}
    original_builder = llm.build_opener

    def audited_builder(*handlers):
        opener = original_builder(*handlers)

        class AuditedOpener:
            def open(self, request, timeout):
                transport["http_attempts"] += 1
                try:
                    response = opener.open(request, timeout=timeout)
                    status = getattr(response, "status", None)
                    transport["http_status"] = status if type(status) is int else None
                    return response
                except HTTPError as error:
                    transport.update(http_status=error.code, transport_error="HTTP_ERROR")
                    raise
                except (TimeoutError, URLError) as error:
                    timeout_error = isinstance(error, TimeoutError) or isinstance(
                        getattr(error, "reason", None), TimeoutError)
                    transport["transport_error"] = "TIMEOUT" if timeout_error else "CONNECTION_ERROR"
                    raise
        return AuditedOpener()

    started = monotonic()
    with patch.object(llm, "build_opener", audited_builder):
        result = EvidenceExtractor(observed).extract(
            source_id="synthetic:t061-connectivity", source_title="完全合成的模型测试",
            body=BODY, completeness="PARTIAL_TEXT", fetched_at=now,
            source_published_at=now, policy=policy, source_type="SYNTHETIC",
            research_gaps=("ROUTES", "EXPERIENCES", "DURATION", "TRANSPORT"),
        )
    claims = result.bundle["claims"]
    located = 0
    for claim in claims:
        match = re.search(r":chars:(\d+)-(\d+)$", claim["locator"] or "")
        located += int(bool(match and result.canonical and
                            result.canonical.text[int(match[1]):int(match[2])] == claim["text"]))
    checks = {
        "exactly_one_provider_call": observed.calls == 1,
        "schema_validated_without_extra_fields": observed.schema_validated,
        "real_llm_mode": result.mode == "LLM",
        "nonempty_evidence": bool(claims),
        "all_retained_claims_located": bool(claims) and located == len(claims),
        "no_ungrounded_model_claims": result.rejected_claims == 0,
        "author_opinion_preserved": all(c["kind"] == "AUTHOR_OPINION" for c in claims),
        "unknown_travel_date_preserved": result.bundle["travel_occurred_at"] is None,
        "partial_completeness_preserved": result.bundle["completeness"] == "PARTIAL_TEXT",
    }
    passed = all(checks.values())
    # Output only accepted synthetic excerpts and bounded diagnostics. No raw response,
    # URL, headers, credentials or exception text is exposed or stored.
    return {"status": "PASS" if passed else "FAIL", "scope": "SYNTHETIC_BODY_REAL_LLM_ONLY",
            "provider_type": "OpenAICompatibleProvider", "model": safe_model_name(provider),
            "response_format": provider.response_format,
            "elapsed_seconds": round(monotonic() - started, 3), "timeout_seconds": provider.timeout,
            "provider_calls": observed.calls, "provider_error": observed.error,
            **transport, "extraction_mode": result.mode, "checks": checks,
            "evidence_count": len(claims), "rejected_model_claims": result.rejected_claims,
            "locator_coverage": located / len(claims) if claims else None,
            "accepted_synthetic_claims": [{"text": c["text"], "topic": c["topic"],
                                          "kind": c["kind"], "locator": c["locator"]} for c in claims]
            if result.mode == "LLM" else [],
            "xhs_connect": 0, "search": 0, "detail": 0, "browser_sessions": 0,
            "g1_pass": False}


def attempt_id(value: str) -> str:
    if re.fullmatch(r"[a-z][a-z0-9-]{0,47}", value) is None:
        # Never echo invalid input, which may accidentally contain a secret or URL.
        raise argparse.ArgumentTypeError("attempt 必须是 1–48 位小写字母、数字或连字符")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="一次合成正文的真实 LLM 检查；不连接小红书")
    parser.add_argument("--live-llm", action="store_true", help="允许一次已配置模型调用")
    parser.add_argument("--attempt", type=attempt_id,
                        help="人工修正配置后显式命名新尝试；保留旧账本，不自动重试")
    args = parser.parse_args()
    if not args.live_llm:
        print(json.dumps({"status": "NOT_RUN", "provider_calls": 0}))
        return 0
    name = f"connectivity-{args.attempt}.json" if args.attempt else "connectivity.json"
    path = ROOT / ".local/t06.1-llm" / name
    if path.exists():
        print(json.dumps({"status": "BLOCKED", "reason": "EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY"}))
        return 2
    try:
        provider = llm.OpenAICompatibleProvider.from_env()
    except llm.LLMError:
        provider = None
    if provider is None:
        print(json.dumps({"status": "G1_LIVE_LLM_BLOCKED", "provider_calls": 0}))
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump({"status": "STARTED", "automatic_retry_allowed": False}, handle)
    except FileExistsError:
        print(json.dumps({"status": "BLOCKED", "reason": "EXISTING_ATTEMPT_NO_AUTOMATIC_RETRY"}))
        return 2
    try:
        result = run_check(provider)
    except Exception:
        result = {"status": "FAIL", "reason": "LOCAL_CHECK_ERROR", "g1_pass": False}
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
