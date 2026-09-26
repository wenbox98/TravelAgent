"""Fixed T06.2 synthetic business extraction, max two durable model attempts."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit
from _bootstrap import enter

enter()
from travel_agent.domain.source_policy import private_policy  # noqa: E402
from travel_agent.domain.models import SourcePolicy  # noqa: E402
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.providers.llm import OpenAICompatibleProvider  # noqa: E402
from travel_agent.research.extractor import EvidenceExtractor  # noqa: E402
from travel_agent.research.models import DetailMaterial, ResearchRequest  # noqa: E402
from travel_agent.research.recovery import ExtractionRecovery  # noqa: E402
from travel_agent.research.retry import retry_saved  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def run(fix_commit=None, resume_before_dispatch=False):
    provider = OpenAICompatibleProvider.from_env()
    if provider is None or urlsplit(provider.base_url).hostname != "api.deepseek.com":
        return {"status": "BLOCKED", "reason": "EXPECTED_CONFIGURED_PROVIDER"}
    folder = ROOT / ".local/t06.2-synthetic"
    folder.mkdir(parents=True, exist_ok=True)
    ledger = folder / "attempt.json"
    if fix_commit:
        prior = json.loads(ledger.read_text(encoding="utf-8"))
        with Database(folder / "research.sqlite3") as db:
            result = retry_saved(EvidenceStore(db), EvidenceExtractor(provider),
                                 attempt_id=prior["attempt_id"], fix_commit=fix_commit)
        target = folder / "retry.json"
    else:
        if resume_before_dispatch:
            assert json.loads(ledger.read_text(encoding="utf-8"))["status"] == "RESERVED"
            with Database(folder / "research.sqlite3") as db:
                assert db.connection.execute("SELECT count(*) FROM extraction_attempts").fetchone()[0] == 0
                assert db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0] == 0
        else:
            with ledger.open("x", encoding="utf-8") as handle:
                json.dump({"status": "RESERVED"}, handle)
        body = (ROOT / "fixtures/t062-synthetic-travel.txt").read_text(encoding="utf-8").strip()
        now = datetime.now(timezone.utc).isoformat()
        with Database(folder / "research.sqlite3") as db:
            store = EvidenceStore(db)
            policy = SourcePolicy(private_policy("synthetic-owner").to_dict() | {
                "version": 2, "basis": "SYNTHETIC", "basis_note": "本项目自编虚构测试正文"})
            request = ResearchRequest(destination="合成青岚谷")
            if resume_before_dispatch:
                policy = store._latest_policy(policy["policy_id"]) or policy
                if policy["basis"] != "SYNTHETIC":
                    policy = SourcePolicy(policy.to_dict() | {"version": policy["version"] + 1,
                        "basis": "SYNTHETIC", "basis_note": "本项目自编虚构测试正文"})
                run_id = db.connection.execute("SELECT run_id FROM research_ops WHERE kind='DETAIL' "
                                               "AND fingerprint='synthetic:t062'").fetchone()[0]
            else:
                run_id = store.begin("t062-synthetic", 0, request.to_dict(), "synthetic-owner")
            store.register_policy(run_id, 0, policy)
            if not resume_before_dispatch:
                assert store.reserve_operation(run_id, 0, "DETAIL", "synthetic:t062", 1)  # Fixture permit only.
            content_id = store.save_source(run_id, 0,
                DetailMaterial("synthetic:t062", "自行编写的虚构旅行记录", body, "PARTIAL_TEXT", now,
                               source_type="SYNTHETIC"), policy, request.destination)
            contents = store.contents.load("synthetic:t062", "synthetic-owner")
            assert 900 <= len(contents[0]["normalized_text"]) <= 1500
            assert 12 <= len(contents[0]["body_blocks"]) <= 20
            outcome = ExtractionRecovery(store, EvidenceExtractor(provider, protocol_version=2)).execute(
                run_id=run_id, revision=0, content_id=content_id, account_scope="synthetic-owner",
                policy=policy, batch_id="t062-synthetic", max_attempts=2)
            result = {k: v for k, v in outcome.items() if k != "result"} | {
                "normalized_chars": len(contents[0]["normalized_text"]),
                "body_blocks": len(contents[0]["body_blocks"]),
                "source_saved": True, "xhs_calls": 0,
                "pre_dispatch_repair": resume_before_dispatch,
                "extraction": outcome["result"].safe_summary() if outcome["result"] else None}
        target = ledger
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fix-commit")
    parser.add_argument("--resume-before-dispatch", action="store_true")
    args = parser.parse_args()
    try:
        result = run(args.fix_commit, args.resume_before_dispatch) if args.live else {"status": "NOT_RUN", "http_attempts": 0}
    except Exception:
        result = {"status": "BLOCKED", "reason": "LOCAL_SYNTHETIC_PRECONDITION_FAILED"}
    print(json.dumps(result, ensure_ascii=True), flush=True)
    raise SystemExit(0 if result["status"] in {"SUCCEEDED", "NOT_RUN"} else 2)
