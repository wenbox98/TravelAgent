"""Operator-approved model-only retry; reads existing local snapshot, never a browser."""

import argparse
import json
from pathlib import Path
import socket
import sys
from urllib.parse import urlsplit
from _bootstrap import enter

enter()
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.providers.llm import OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.retry import authorize_extra, retry_saved, run_extra_worker, supervise_extra  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402
from travel_agent.research.candidate_review import review_candidates  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--fix-commit")
    parser.add_argument("--review-stdin", action="store_true")
    parser.add_argument("--account-scope")
    parser.add_argument("--grant-extra", action="store_true", help="Record this task's one additional authorization without network")
    parser.add_argument("--extra-authorization", action="store_true", help="Consume T06.4 authorization under a 180-second deadline")
    parser.add_argument("--extra-worker", help=argparse.SUPPRESS)
    parser.add_argument("--continuation-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--research-gaps", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.live and not args.review_stdin and not args.grant_extra:
        print(json.dumps({"status": "NOT_RUN", "http_attempts": 0}))
        return 0
    try:
        if (args.live and (args.review_stdin or args.grant_extra)
            or args.review_stdin and args.grant_extra):
            raise ValueError("REVIEW_CANNOT_DISPATCH_MODEL")
        allowed_addresses = set()
        resolve = socket.getaddrinfo
        def model_dns(host, port, *pos, **kw):
            if not args.live or host != "api.deepseek.com" or port != 443:
                raise PermissionError("RECOVERY_NETWORK_DENIED")
            result = resolve(host, port, *pos, **kw)
            allowed_addresses.update(row[4][0] for row in result)
            return result
        socket.getaddrinfo = model_dns
        def network_guard(event, values):
            if event == "import" and (values[0].startswith("xhs_sidecar") or values[0].startswith("playwright")):
                raise PermissionError("RECOVERY_BROWSER_DENIED")
            if event == "socket.connect" and (not args.live or values[1][0] not in allowed_addresses or values[1][1] != 443):
                raise PermissionError("RECOVERY_NETWORK_DENIED")
            if event in {"socket.bind", "socket.sendto"}:
                raise PermissionError("RECOVERY_NETWORK_DENIED")
        sys.addaudithook(network_guard)
        if not args.database.is_file():
            raise ValueError("MISSING_DATABASE")
        with Database(args.database) as db:
            if args.review_stdin:
                decisions = json.loads(sys.stdin.read(32768))
                result = review_candidates(EvidenceStore(db), attempt_id=args.attempt_id,
                    account_scope=args.account_scope, decisions={int(k): v for k, v in decisions.items()})
            else:
                provider = OpenAICompatibleProvider.from_env()
                if provider is None or urlsplit(provider.base_url).hostname != "api.deepseek.com":
                    raise ValueError("EXPECTED_CONFIGURED_PROVIDER_AND_FIX")
                if args.extra_worker:
                    run_extra_worker(EvidenceStore(db), provider, args.extra_worker)
                    return 0
                if args.continuation_worker:
                    from travel_agent.research.continuation import ContinuationBudget
                    from travel_agent.research.recovery import ExtractionRecovery
                    store = EvidenceStore(db)
                    ContinuationBudget(store).check_worker(args.attempt_id, provider)
                    ExtractionRecovery(store, EvidenceExtractor(provider)).run_reserved(args.attempt_id,
                        research_gaps=tuple(filter(None, args.research_gaps.split(","))))
                    return 0
                if not args.fix_commit:
                    raise ValueError("EXPECTED_FIX_COMMIT")
                if args.grant_extra or args.extra_authorization:
                    if provider.timeout != 120:
                        raise ValueError("EXTRA_REQUIRES_120_SECOND_TIMEOUT")
                    if args.grant_extra:
                        result = authorize_extra(EvidenceStore(db), base_attempt_id=args.attempt_id,
                            fix_commit=args.fix_commit, provider=provider, deadline=180)
                    else:
                        result = supervise_extra(args.database, base_attempt_id=args.attempt_id,
                            fix_commit=args.fix_commit, provider=provider, deadline=180)
                else:
                    result = retry_saved(EvidenceStore(db), EvidenceExtractor(provider),
                                         attempt_id=args.attempt_id, fix_commit=args.fix_commit)
            result.update(browser_modules_absent=not any(m.startswith(("xhs_sidecar", "playwright")) for m in sys.modules),
                          network_guard="DEEPSEEK_ONLY" if args.live else "DENY_ALL")
    except Exception:
        result = {"status": "BLOCKED", "reason": "LOCAL_RECOVERY_PRECONDITION_FAILED"}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] in {"SUCCEEDED", "PARTIAL_SUCCESS", "PENDING_REVIEW", "GRANTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
