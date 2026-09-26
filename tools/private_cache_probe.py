"""Independent, network-denied process for private SourceContent/Evidence restoration."""

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))

from travel_agent.domain.models import SourcePolicy  # noqa: E402
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.research.content_store import audit_grounding  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.models import ResearchBudget, ResearchRequest  # noqa: E402
from travel_agent.research.service import ResearchService  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402


class NoAccessReader:
    text_first = False

    def __init__(self):
        self.calls = {"connect": 0, "search": 0, "detail": 0}

    def forbidden(self, kind):
        self.calls[kind] += 1
        raise AssertionError("CACHE_PROBE_FORBIDS_READER")

    def connect(self): self.forbidden("connect")
    def search(self, query): self.forbidden("search")
    def detail(self, candidate, number): self.forbidden("detail")
    def disable_text_first(self): raise AssertionError("CACHE_PROBE_FORBIDS_FALLBACK")


def evidence_digest(evidence):
    return sha256(json.dumps([b.to_dict() for b in evidence], sort_keys=True,
                             ensure_ascii=False).encode()).hexdigest()


def probe(database, account_scope, research_id):
    with Database(database) as db:
        store = EvidenceStore(db)
        previous = store.load_report(research_id, account_scope)
        if previous is None:
            return {"status": "FAIL", "reason": "REPORT_NOT_RESTORED"}
        request = ResearchRequest(**previous["request"])
        evidence = store.lookup(research_id, request.destination, account_scope)
        source_ids = {b["source_id"] for b in evidence} | {row[0] for row in db.connection.execute(
            "SELECT DISTINCT c.source_id FROM source_contents c JOIN research_run_contents r USING(content_id) "
            "WHERE r.run_id=? AND c.account_scope=?", (previous["run_id"], account_scope))}
        if not source_ids:
            return {"status": "FAIL", "reason": "EVIDENCE_NOT_RESTORED"}
        contents = {source: store.contents.load(source, account_scope) for source in sorted(source_ids)}
        content_digest = sha256(json.dumps(contents, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        keys = {source: [c["content_hash"] for c in rows] for source, rows in contents.items()}
        row = db.connection.execute("SELECT policy_json FROM source_policies WHERE policy_id=? "
                                     "ORDER BY version DESC LIMIT 1", (next(iter(contents.values()))[0]["policy_id"],)).fetchone()
        policy = SourcePolicy(json.loads(row[0]))
        reader = NoAccessReader()
        service = ResearchService(store, reader, EvidenceExtractor(), policy)
        # A separate question avoids rewriting the original question's revision/history.
        last = db.connection.execute("SELECT current_revision FROM research_questions WHERE research_id=?", (research_id + "-cache",)).fetchone()
        revision = last[0] + 1 if last is not None else 0
        cached = service.run(request, research_id=research_id + "-cache", revision=revision,
                             account_scope=account_scope, budget=ResearchBudget(0, 0))
        cached_summary = cached.safe_summary()
        restored = store.load_report(research_id + "-cache", account_scope)
        incremental = service.run(replace(request, days=5, no_self_drive=True),
                                  research_id=research_id + "-cache", revision=revision + 1,
                                  account_scope=account_scope, budget=ResearchBudget(0, 0))
        after_contents = {source: store.contents.load(source, account_scope) for source in sorted(source_ids)}
        after = {source: [c["content_hash"] for c in rows] for source, rows in after_contents.items()}
        audits = [audit_grounding(b, contents[b["source_id"]]) for b in evidence]
        checks = {
            "source_content_restored": bool(contents) and all(contents.values()),
            "evidence_restored": bool(evidence) and evidence_digest(cached.evidence) == evidence_digest(evidence),
            "coverage_restored": cached_summary["coverage"] == previous["summary"].get("coverage"),
            "report_restored": restored is not None and restored["summary"]["coverage"] == cached_summary["coverage"],
            "original_report_preserved": store.load_report(research_id, account_scope) == previous,
            "no_reader_calls": all(value == 0 for value in reader.calls.values()),
            "zero_operations": cached.operations == incremental.operations == {"search": 0, "detail": 0},
            "incremental_evidence_preserved": bool(evidence) and evidence_digest(incremental.evidence) == evidence_digest(evidence),
            "incremental_content_preserved": keys == after,
            "body_blocks_and_metadata_unchanged": contents == after_contents,
            "incremental_gaps": {"DAYS_FIT", "NON_SELF_DRIVE"} <= {g.gap_id for g in incremental.gaps},
            "grounding_restored": bool(audits) and all(a["unsupported"] == 0 and a["checked"] > 0 for a in audits),
            "browser_modules_absent": not any(m.startswith("xhs_sidecar") for m in sys.modules),
        }
        return {"status": "PASS" if all(checks.values()) else "FAIL", "pid": os.getpid(),
                "checks": checks, "calls": reader.calls, "browser_sessions": 0,
                "model_calls": 0, "source_content_digest": content_digest,
                "source_content_count": sum(map(len, contents.values())),
                "body_blocks": sum(len(c["body_blocks"]) for rows in contents.values() for c in rows),
                "normalized_chars": [len(c["normalized_text"]) for rows in contents.values() for c in rows],
                "evidence_digest": evidence_digest(evidence), "summary": cached_summary,
                "incremental": incremental.safe_summary(), "grounding": audits}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--account-scope", required=True)
    parser.add_argument("--research-id", required=True)
    args = parser.parse_args()
    if not args.database.is_file():
        print(json.dumps({"status": "FAIL", "reason": "CACHE_NOT_FOUND"}))
        return 2
    def deny(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendto"}:
            raise PermissionError("CACHE_PROBE_FORBIDS_NETWORK")
    sys.addaudithook(deny)
    try:
        result = probe(args.database, args.account_scope, args.research_id)
    except Exception:
        result = {"status": "FAIL", "reason": "CACHE_RESTORE_ERROR"}
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
