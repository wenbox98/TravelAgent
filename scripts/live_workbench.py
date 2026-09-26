"""Local workbench and operator-only budget/review controls. No actions on ordinary boot."""

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
from _bootstrap import enter


def main() -> None:
    enter()
    from travel_agent.persistence.database import Database
    from travel_agent.preview.worker import (
        configured_provider,
        run_job,
        extract_worker,
        supervised_review,
    )
    from travel_agent.research.bounded import BoundedBudget
    from travel_agent.research.context_review import run_review
    from travel_agent.research.store import EvidenceStore

    parser = argparse.ArgumentParser(description="本机有限研究工作台；serve/status 不访问外部服务")
    parser.add_argument(
        "action",
        choices=[
            "serve",
            "status",
            "grant",
            "evaluate",
            "gate-pass",
            "gate-partial",
            "close-grant",
            "job-worker",
            "extract-worker",
            "review-worker",
        ],
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--source-database", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--account-scope", default="")
    parser.add_argument("--continuation", default="")
    parser.add_argument("--predecessor", default="")
    parser.add_argument("--evaluation-attempt", action="append", default=[])
    parser.add_argument("--identifier", default="")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    os.environ["LLM_TIMEOUT_SECONDS"] = "120"
    if args.action == "serve":
        from cached_preview import prepare_workspace

        if (
            args.workspace is None
            or args.source_database is None
            or not args.account_scope
            or not args.continuation
        ):
            parser.error("serve 需要工作目录、原缓存、scope 和已登记的有界许可")
        args.database = prepare_workspace(args.source_database, args.workspace)
        from travel_agent.main import create_app
        from travel_agent.preview.api import PreviewConfig
        from travel_agent.preview.jobs import JobService
        from travel_agent.settings import Settings
        import uvicorn

        keyfile = args.database.parent / "preview-auth.key"
        if not keyfile.exists():
            with keyfile.open("xb") as file:
                file.write(secrets.token_bytes(32))
        key = keyfile.read_bytes()
        if len(key) != 32:
            raise ValueError("INVALID_LOCAL_KEY")
        ready = False
        with Database(args.database) as db:
            JobService(
                db, args.account_scope, "CACHED_PRIVATE_PREVIEW", args.continuation
            ).reconcile_restart()
            try:
                BoundedBudget(EvidenceStore(db), args.continuation).check_provider(
                    configured_provider()
                )
                ready = True
            except ValueError:
                pass
        config = PreviewConfig(
            args.database,
            args.account_scope,
            "CACHED_PRIVATE_PREVIEW",
            key,
            continuation=args.continuation,
            live_ready=ready,
        )
        url = f"http://127.0.0.1:{args.port}/bootstrap?ticket={config.ticket}"
        print("缓存可用。只有页面主动操作且门槛/额度许可时才派发研究。", flush=True)
        print("本机五分钟一次性入口，请勿分享：" + url, flush=True)
        if args.open:
            import threading
            import webbrowser

            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        uvicorn.run(
            create_app(Settings.load(preferred_port=args.port), preview=config),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
        return
    if args.database is None or not args.database.is_file():
        parser.error("需要已有工作数据库")
    if args.action == "job-worker":
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/xhs-sidecar"))
        run_job(args.database, args.identifier)
        return
    with Database(args.database) as db:
        store = EvidenceStore(db)
        budget = BoundedBudget(store, args.continuation)
        if args.action == "extract-worker":
            extract_worker(store, configured_provider(), args.identifier)
            return
        if args.action == "review-worker":
            run_review(store, configured_provider(), args.identifier)
            return
        if args.action == "grant":
            budget.grant(
                args.account_scope, args.predecessor, configured_provider(), args.evaluation_attempt
            )
        elif args.action == "evaluate":
            from travel_agent.preview.service import PreviewService

            current = PreviewService(db, args.account_scope, "CACHED_PRIVATE_PREVIEW").latest()
            result = supervised_review(
                store,
                configured_provider(),
                budget,
                args.identifier,
                args.account_scope,
                current["preferences"] if current else {},
                evaluation=True,
            )
            print(json.dumps(result, ensure_ascii=True))
            return
        elif args.action.startswith("gate-"):
            budget.conclude_evaluation(args.action == "gate-pass")
        elif args.action == "close-grant":
            db.connection.execute(
                "UPDATE research_continuations SET finished_at=coalesce(finished_at,?) WHERE continuation_id=?",
                (db.stamp(), args.continuation),
            )
        print(json.dumps(budget.summary(), ensure_ascii=True))


if __name__ == "__main__":
    main()
