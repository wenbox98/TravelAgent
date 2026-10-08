"""Unified private planning entry; bounded grants, same workspace, reversible static build."""

import argparse
import os
from pathlib import Path
import secrets
import sys
import threading
from _bootstrap import enter


def reopen(workspace: Path, port: int) -> None:
    """Renew with local-owner proof; never start workers or touch trip data."""
    import http.client
    import json
    import webbrowser
    from urllib.parse import urlsplit
    from travel_agent.preview.local_entry import entry_proof

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        key = (workspace / "preview-auth.key").read_bytes()
        connection.request("POST", "/local-entry", headers={"X-Local-Entry-Proof": entry_proof(key)})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("LOCAL_ENTRY_UNAVAILABLE")
        url = json.loads(response.read(2048))["entry_url"]
        target = urlsplit(url)
        if target.scheme != "http" or target.netloc != f"127.0.0.1:{port}" or target.path != "/bootstrap":
            raise ValueError("LOCAL_ENTRY_UNAVAILABLE")
        (workspace / "entry.url").write_text(url, encoding="utf8")
        webbrowser.open(url)
        print("已重新打开本机旅行工作台；原服务、草稿和任务保留。")
    except (OSError, ValueError, KeyError):
        raise SystemExit("无法重新打开本机入口：请确认该工作区服务已启动且版本已更新。原数据未改变。") from None
    finally:
        connection.close()


def prepare_runtime(workspace: Path, *, initialize_empty: bool = False) -> Path:
    """Explicit empty install; never recover a missing configured database as empty."""
    import sqlite3
    from travel_agent.persistence.database import Database

    database = workspace / "preview.sqlite3"
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as con:
            if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("WORKSPACE_DATABASE_DAMAGED")
            if not con.execute("SELECT 1 FROM schema_version").fetchone():
                raise ValueError("WORKSPACE_DATABASE_UNKNOWN")
    elif (not initialize_empty and workspace.exists()) or (
        workspace.exists() and any(workspace.iterdir())
    ):
        raise ValueError("WORKSPACE_DATABASE_MISSING")
    with Database(database):
        pass
    return database


def main() -> None:
    enter()
    from travel_agent.persistence.database import Database
    from travel_agent.planning.suggestions import IDENTIFIER, grant, run_worker, shutdown_workers
    from travel_agent.preview.worker import configured_provider
    from travel_agent.settings import PROJECT_ROOT, Settings
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    import uvicorn

    parser = argparse.ArgumentParser(description="本机私人旅行规划；仅显式操作使用已登记额度")
    parser.add_argument(
        "action",
        nargs="?",
        default="serve",
        choices=[
            "serve",
            "open",
            "authorize-synthetic",
            "authorize-private",
            "worker",
            "job-worker",
            "extract-worker",
            "review-worker",
            "diagnostic-replay",
            "diagnostic-clean",
        ],
    )
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--job", default="")
    parser.add_argument("--destination", default="")
    parser.add_argument("--batch", choices=["p05", "p051", "p052", "p06"], default="p06")
    parser.add_argument("--code-sha", default="")
    parser.add_argument("--all-records", action="store_true")
    parser.add_argument("--workspace", type=Path, default=PROJECT_ROOT / ".local/p04-preview")
    parser.add_argument(
        "--account-scope", default=os.environ.get("TRAVEL_ACCOUNT_SCOPE", "current-private-profile")
    )
    parser.add_argument("--initialize-empty", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    database = workspace / "preview.sqlite3"
    scope = args.account_scope.strip()
    if not scope or len(scope) > 80:
        raise ValueError("ACCOUNT_SCOPE_REQUIRED")
    if args.action == "open":
        reopen(workspace, args.port)
        return
    os.environ["LLM_TIMEOUT_SECONDS"] = "120"
    # Only configured model variables are inherited. No secret is logged or exposed.
    if os.name == "nt":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as envkey:
            for name in (
                "AMAP_WEB_SERVICE_KEY",
                "LLM_API_KEY",
                "LLM_MODEL",
                "LLM_BASE_URL",
                "LLM_RESPONSE_FORMAT",
                "TRAVEL_LLM_API_KEY",
                "TRAVEL_LLM_MODEL",
                "TRAVEL_LLM_BASE_URL",
            ):
                if not os.environ.get(name):
                    try:
                        value, _ = winreg.QueryValueEx(envkey, name)
                        os.environ[name] = value
                    except FileNotFoundError:
                        pass
    prepare_runtime(workspace, initialize_empty=args.initialize_empty)
    if args.action == "authorize-synthetic":
        with Database(database) as db:
            grant(db, scope, configured_provider())
        print("已登记原服务的两次合成验收许可；旧额度与失败记录不变。")
        return

    from travel_agent.planning.private_budget import (
        PrivatePlanningBudget,
        IDENTIFIER as PRIVATE_ID,
        CURRENT_IDENTIFIER,
        DISCOVERY_IDENTIFIER,
        REVISION_IDENTIFIER,
    )

    if args.action == "authorize-private":
        with Database(database) as db:
            PrivatePlanningBudget(
                db,
                {
                    "p05": PRIVATE_ID,
                    "p051": CURRENT_IDENTIFIER,
                    "p052": DISCOVERY_IDENTIFIER,
                    "p06": REVISION_IDENTIFIER,
                }[args.batch],
            ).initialize(scope, args.destination, configured_provider())
        print("本批私人规划许可已登记，旧批次和失败记录保留。")
        return
    from travel_agent.planning.network import install

    audit = workspace / "operation-audit"
    audit.mkdir(exist_ok=True)
    install(args.action, audit / f"metrics-{os.getpid()}.json")
    if args.action in {"diagnostic-replay", "diagnostic-clean"}:
        import json
        from travel_agent.planning.revision_diagnostics import cleanup, replay

        with Database(database) as db:
            result = (
                replay(db, scope, args.job, args.code_sha)
                if args.action == "diagnostic-replay"
                else {"removed": cleanup(db, all_records=args.all_records)}
            )
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.action == "worker":
        run_worker(database, args.job)
        return
    if args.action == "job-worker":
        from travel_agent.preview.worker import run_job

        sys.path.insert(0, str(PROJECT_ROOT / "integrations/xhs-sidecar"))
        run_job(database, args.job, product=True)
        return
    if args.action in {"extract-worker", "review-worker"}:
        from travel_agent.preview.worker import extract_worker
        from travel_agent.research.context_review import run_review
        from travel_agent.research.store import EvidenceStore

        with Database(database) as db:
            (extract_worker if args.action == "extract-worker" else run_review)(
                EvidenceStore(db), configured_provider(), args.job
            )
        return
    # Exactly one owner of the independent working copy. Never stop other apps.
    lock = (workspace / "serve.lock").open("a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if args.open:
            reopen(workspace, args.port)
            return
        raise SystemExit("WORKBENCH_ALREADY_RUNNING") from None
    with Database(database) as db:
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1 WHERE continuation_id IN (?,?,?,?,?) AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (IDENTIFIER, PRIVATE_ID, CURRENT_IDENTIFIER, DISCOVERY_IDENTIFIER, REVISION_IDENTIFIER),
        )
        from travel_agent.planning.revision_diagnostics import cleanup

        cleanup(db)
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1 WHERE continuation_id IN (SELECT continuation_id FROM research_continuations WHERE json_extract(gate_json,'$.purpose')='PRIVATE_OPERATION') AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')"
        )
    keyfile = workspace / "preview-auth.key"
    if not keyfile.exists():
        with keyfile.open("xb") as f:
            f.write(secrets.token_bytes(32))
    config = PreviewConfig(
        database,
        scope,
        "CACHED_PRIVATE_PREVIEW",
        keyfile.read_bytes(),
        product_flow=True,
        daily_workbench=True,
        local_metrics_path=audit / f"ui-requests-{os.getpid()}.json",
        static_dir=PROJECT_ROOT / ".local/workbench-web",
    )
    url = f"http://127.0.0.1:{args.port}/bootstrap?ticket={config.ticket}"
    (workspace / "entry.url").write_text(url, encoding="utf-8")
    print(
        f"TravelAgent：http://127.0.0.1:{args.port}/；旧测试独立保留，新旅行不继承测试偏好。",
        flush=True,
    )
    if args.open:
        import webbrowser

        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        uvicorn.run(
            create_app(Settings.load(preferred_port=args.port), preview=config),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
        )
    finally:
        shutdown_workers(database)
        lock.close()


if __name__ == "__main__":
    main()
