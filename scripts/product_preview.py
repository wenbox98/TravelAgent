"""Unified private planning entry; bounded grants, same workspace, reversible static build."""

import argparse
import os
import secrets
import sys
import threading
from _bootstrap import enter


def main() -> None:
    enter()
    from cached_preview import prepare_workspace
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
            "authorize-synthetic",
            "authorize-private",
            "worker",
            "job-worker",
            "extract-worker",
            "review-worker",
        ],
    )
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--job", default="")
    parser.add_argument("--destination", default="")
    args = parser.parse_args()
    workspace = PROJECT_ROOT / ".local/p04-preview"
    database = workspace / "preview.sqlite3"
    scope = "current-private-profile"
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
    if not args.action.endswith("worker"):
        prepare_workspace(PROJECT_ROOT / ".local/p03-preview/preview.sqlite3", workspace)
    if args.action == "authorize-synthetic":
        with Database(database) as db:
            grant(db, scope, configured_provider())
        print("已登记原服务的两次合成验收许可；旧额度与失败记录不变。")
        return

    from travel_agent.planning.private_budget import PrivatePlanningBudget, IDENTIFIER as PRIVATE_ID

    if args.action == "authorize-private":
        with Database(database) as db:
            PrivatePlanningBudget(db).initialize(scope, args.destination, configured_provider())
        print("本批私人规划许可已登记，旧批次和失败记录保留。")
        return
    from travel_agent.planning.network import install

    audit = PROJECT_ROOT / ".local/p05-audit"
    audit.mkdir(exist_ok=True)
    install(args.action, audit / f"metrics-{os.getpid()}.json")
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
        raise SystemExit("P04_ALREADY_RUNNING") from None
    with Database(database) as db:
        db.connection.execute(
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1 WHERE continuation_id IN (?,?) AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (IDENTIFIER, PRIVATE_ID),
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
        static_dir=PROJECT_ROOT / ".local/p05-web",
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
