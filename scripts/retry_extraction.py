"""Operator-approved model-only retry; reads existing local snapshot, never a browser."""

import argparse
import json
from pathlib import Path
from _bootstrap import enter

enter()
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.providers.llm import OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.retry import retry_saved  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--fix-commit", required=True)
    args = parser.parse_args()
    if not args.live:
        print(json.dumps({"status": "NOT_RUN", "http_attempts": 0}))
        return 0
    try:
        if not args.database.is_file():
            raise ValueError("MISSING_DATABASE")
        provider = OpenAICompatibleProvider.from_env()
        if provider is None:
            raise ValueError("NOT_CONFIGURED")
        with Database(args.database) as db:
            result = retry_saved(EvidenceStore(db), EvidenceExtractor(provider),
                                 attempt_id=args.attempt_id, fix_commit=args.fix_commit)
    except Exception:
        result = {"status": "BLOCKED", "reason": "LOCAL_RECOVERY_PRECONDITION_FAILED"}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
