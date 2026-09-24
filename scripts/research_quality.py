"""T06 local-only benchmark/cache controls. This entry point never performs live reads."""

import argparse
import json
from pathlib import Path

from _bootstrap import enter

enter()

from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.research.benchmark import QualityBenchmark, live_preflight  # noqa: E402
from travel_agent.research.store import EvidenceStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="T06 离线合成研究质量验收；不会访问真实小红书")
    commands = parser.add_subparsers(dest="command", required=True)
    benchmark = commands.add_parser("benchmark", help="执行合成场景并输出指标与可读示例")
    benchmark.add_argument("--metrics", type=Path, default=ROOT / ".local/t06-benchmark/metrics.json")
    benchmark.add_argument("--report", type=Path, default=ROOT / "reports/T06-synthetic-research-example.md")
    clear = commands.add_parser("clear-cache", help="仅清理指定 SQLite 与账号范围的研究缓存")
    clear.add_argument("--database", type=Path, required=True)
    clear.add_argument("--account-scope", required=True)
    commands.add_parser("live-preflight", help="仅检查模型配置，不发模型请求、不登录或访问站点")
    args = parser.parse_args()
    if args.command == "live-preflight":
        result = live_preflight()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "PRIVATE_LOCAL_CONFIG_READY" else 2
    if args.command == "clear-cache":
        # Refuse an absent file rather than manufacturing an empty cache as success.
        if not args.database.is_file():
            print(json.dumps({"status": "CACHE_NOT_FOUND"}))
            return 2
        with Database(args.database) as db:
            deleted = EvidenceStore(db).clear_research_cache(args.account_scope)
        print(json.dumps({"status": "CLEARED", "deleted": deleted,
                          "login_profile_touched": False}, ensure_ascii=False))
        return 0
    suite = QualityBenchmark(ROOT)
    metrics = suite.run()
    metrics["live_preflight"] = live_preflight()
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(suite.example_markdown(), encoding="utf-8")
    print(json.dumps({key: value for key, value in metrics.items() if key != "cases"}, ensure_ascii=False))
    return int(metrics["failed"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
