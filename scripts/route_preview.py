"""P03 isolated route preview. Reuses preview boot/backup, no research worker."""

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import webbrowser
from _bootstrap import enter


def main() -> None:
    enter()
    from cached_preview import prepare_workspace
    from travel_agent.persistence.database import Database
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.preview.service import PreviewService
    from travel_agent.planning.budget import MapBudget
    from travel_agent.research.store import EvidenceStore
    from travel_agent.providers.network_fence import in_amap_transport
    from travel_agent.settings import PROJECT_ROOT, Settings
    from travel_agent.main import create_app
    import uvicorn

    parser = argparse.ArgumentParser(description="P03 本机路程核实；小红书/模型关闭")
    parser.add_argument(
        "--source-database", type=Path, default=PROJECT_ROOT / ".local/p021-preview/preview.sqlite3"
    )
    parser.add_argument("--workspace", type=Path, default=PROJECT_ROOT / ".local/p03-preview")
    parser.add_argument("--static-dir", type=Path, default=PROJECT_ROOT / ".local/p03-web")
    parser.add_argument("--account-scope", default="current-private-profile")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    # This batch is tied to exactly one authorized private workspace. No new run-ID grants.
    if args.workspace.resolve() != (PROJECT_ROOT / ".local/p03-preview").resolve():
        raise SystemExit("P03_WORKSPACE_FIXED; 不通过新目录恢复本轮额度")
    if (
        args.source_database.resolve()
        != (PROJECT_ROOT / ".local/p021-preview/preview.sqlite3").resolve()
    ):
        raise SystemExit("P03_SOURCE_MUST_BE_CURRENT_P021")
    if args.static_dir.resolve() != (PROJECT_ROOT / ".local/p03-web").resolve():
        raise SystemExit("P03_STATIC_DIRECTORY_FIXED")
    args.workspace.mkdir(parents=True, exist_ok=True)
    # One owning process per workspace; map values remain process-local.
    lock_file = (args.workspace / "serve.lock").open("a+b")
    lock_file.seek(0)
    lock_file.write(b"0")
    lock_file.flush()
    lock_file.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("P03_ALREADY_RUNNING; 请使用当前页面") from None
    database = prepare_workspace(args.source_database, args.workspace)
    with Database(database) as db:
        service = PreviewService(db, args.account_scope, "CACHED_PRIVATE_PREVIEW")
        grant = db.connection.execute(
            "SELECT config_json FROM research_continuations WHERE continuation_id='p03-amap-route-check'"
        ).fetchone()
        if grant:
            view = service.get(json.loads(grant[0])["session_id"])
        else:
            view = next(
                (
                    v
                    for r in db.connection.execute(
                        "SELECT session_id FROM preview_sessions WHERE account_scope=? ORDER BY updated_at DESC,rowid DESC",
                        (args.account_scope,),
                    )
                    if (v := service.get(r[0]))["confirmed_option_id"]
                    and not v["interest_needs_confirmation"]
                    and not v["stale"]
                ),
                None,
            )
        if not view or not view["confirmed_option_id"]:
            raise SystemExit("P03_REQUIRES_CURRENT_CONFIRMED_INTEREST")
        MapBudget(EvidenceStore(db)).initialize(
            args.account_scope, view["session_id"], view["confirmed_option_id"]
        )
    key_file = database.parent / "p03-auth.key"
    if not key_file.exists():
        with key_file.open("xb") as stream:
            stream.write(secrets.token_bytes(32))
    config = PreviewConfig(
        database,
        args.account_scope,
        "CACHED_PRIVATE_PREVIEW",
        key_file.read_bytes(),
        route_check=True,
        static_dir=args.static_dir.resolve(),
    )
    metrics = {
        "xhs_connect": 0,
        "xhs_search": 0,
        "xhs_detail": 0,
        "xhs_browser": 0,
        "project_model": 0,
        "amap_http_attempts": 0,
        "amap_dns_attempts": 0,
        "amap_socket_attempts": 0,
        "blocked_external_attempts": 0,
        "loopback_connections": 0,
        "loopback_http_requests": 0,
    }
    metrics_file = database.parent / f"metrics-{os.getpid()}.json"
    metrics_lock = threading.RLock()

    def count(name: str) -> None:
        with metrics_lock:
            metrics[name] += 1
            metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

    def guard(event: str, values: tuple) -> None:
        if event == "import" and (
            str(values[0]).startswith("xhs_sidecar")
            or values[0] in {"travel_agent.research.live", "travel_agent.research.service"}
        ):
            raise PermissionError("P03_RESEARCH_DISABLED")
        if event == "urllib.Request":
            from urllib.parse import urlsplit
            from travel_agent.providers.amap import PATHS

            url = urlsplit(values[0])
            if (
                in_amap_transport()
                and url.scheme == "https"
                and url.netloc == "restapi.amap.com"
                and url.path in PATHS.values()
            ):
                count("amap_http_attempts")
            else:
                count("blocked_external_attempts")
                raise PermissionError("P03_HTTP_DENIED")
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            address = (
                values[1]
                if event == "socket.connect"
                else values[0]
                if event == "socket.getaddrinfo"
                else values[-1]
            )
            host = address[0] if isinstance(address, tuple) else address
            if host in {"127.0.0.1", "::1", "localhost"}:
                if event == "socket.connect":
                    count("loopback_connections")
                return
            allowed = in_amap_transport() and (
                event == "socket.getaddrinfo"
                and host == "restapi.amap.com"
                or event == "socket.connect"
                and isinstance(address, tuple)
                and address[1] == 443
            )
            if not allowed:
                count("blocked_external_attempts")
                raise PermissionError("P03_EXTERNAL_NETWORK_DENIED")
            count("amap_dns_attempts" if event == "socket.getaddrinfo" else "amap_socket_attempts")

    metrics_file.write_text(json.dumps(metrics), encoding="utf-8")
    sys.addaudithook(guard)
    app = create_app(Settings.load(preferred_port=args.port), preview=config)

    @app.middleware("http")
    async def requests(request, call_next):
        count("loopback_http_requests")
        return await call_next(request)

    url = f"http://127.0.0.1:{args.port}/bootstrap?ticket={config.ticket}"
    (database.parent / "entry.url").write_text(url, encoding="utf-8")
    print(
        f"P03：http://127.0.0.1:{args.port}/；仅主动地图操作可出网；无 Key 时仅本地预览。",
        flush=True,
    )
    if args.open:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    lock_file.close()


if __name__ == "__main__":
    main()
