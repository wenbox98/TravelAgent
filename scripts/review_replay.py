"""P02.1 isolated local replay/preview. Never enable the P02 worker or grants."""

import argparse
import json
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import webbrowser
from _bootstrap import enter


def main() -> None:
    enter()
    from cached_preview import prepare_workspace
    from travel_agent.persistence.database import Database
    from travel_agent.research.store import EvidenceStore
    from travel_agent.research.review_replay import replay
    from travel_agent.settings import PROJECT_ROOT, Settings
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    import uvicorn

    parser = argparse.ArgumentParser(description="只读本地提议回放；不调用小红书或模型")
    parser.add_argument("command", choices=["dry-run", "replay", "serve"])
    parser.add_argument("--source-database", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--account-scope", required=True)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--static-dir", type=Path, default=PROJECT_ROOT / ".local/p021-web")
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    database = prepare_workspace(args.source_database, args.workspace)
    metrics = dict(
        project_model=0,
        xhs_connect=0,
        xhs_search=0,
        xhs_detail=0,
        xhs_browser=0,
        external_socket_attempts=0,
        loopback_connections=0,
        loopback_http_requests=0,
    )
    metrics_file = database.parent / (args.command + "-metrics.json")

    def save_metrics() -> None:
        metrics_file.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    def guard(event: str, values: tuple) -> None:
        if event in {"socket.connect", "socket.getaddrinfo"}:
            address = values[1] if event == "socket.connect" else values[0]
            host = address[0] if isinstance(address, tuple) else address
            if host not in {"127.0.0.1", "::1", "localhost"}:
                metrics["external_socket_attempts"] += 1
                save_metrics()
                raise PermissionError("P021_EXTERNAL_NETWORK_DISABLED")
            if event == "socket.connect":
                metrics["loopback_connections"] += 1

    sys.addaudithook(guard)
    save_metrics()
    if args.command != "serve":
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        results = []
        with Database(database) as db:
            reviews = db.connection.execute(
                "SELECT review_id FROM context_review_runs WHERE account_scope=? AND status='COMPLETED' ORDER BY CASE mode WHEN 'EVALUATION' THEN 0 ELSE 1 END,rowid",
                (args.account_scope,),
            ).fetchall()
            for r in reviews:
                try:
                    results.append(
                        replay(
                            EvidenceStore(db),
                            r[0],
                            args.account_scope,
                            sha,
                            dry_run=args.command == "dry-run",
                        )
                    )
                except ValueError, PermissionError:
                    results.append({"status": "REPLAY_UNAVAILABLE"})
        (database.parent / (args.command + "-private.json")).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                [
                    {k: v for k, v in r.items() if k not in {"results", "revalidation_id"}}
                    for r in results
                ]
            )
        )
        save_metrics()
        return
    key_file = database.parent / "p021-auth.key"
    if not key_file.exists():
        with key_file.open("xb") as stream:
            stream.write(secrets.token_bytes(32))
    config = PreviewConfig(
        database,
        args.account_scope,
        "CACHED_PRIVATE_PREVIEW",
        key_file.read_bytes(),
        local_replay=True,
        static_dir=args.static_dir.resolve(),
    )
    app = create_app(Settings.load(preferred_port=args.port), preview=config)

    @app.middleware("http")
    async def count_requests(request, call_next):
        metrics["loopback_http_requests"] += 1
        save_metrics()
        return await call_next(request)

    url = f"http://127.0.0.1:{args.port}/bootstrap?ticket={config.ticket}"
    (database.parent / "entry.url").write_text(url, encoding="utf-8")
    print(f"P02.1 本机地址：http://127.0.0.1:{args.port}/；外部调用已关闭。", flush=True)
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
