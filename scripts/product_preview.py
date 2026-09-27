"""Unified P04 entry; protected copy of P03, fixed two-request synthetic grant."""

import argparse
import json
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

    parser = argparse.ArgumentParser(description="本机旅行草案；本批无小红书和高德请求")
    parser.add_argument(
        "action", nargs="?", default="serve", choices=["serve", "authorize-synthetic", "worker"]
    )
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--job", default="")
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
    if args.action != "worker":
        prepare_workspace(PROJECT_ROOT / ".local/p03-preview/preview.sqlite3", workspace)
    if args.action == "authorize-synthetic":
        with Database(database) as db:
            grant(db, scope, configured_provider())
        print("已登记原服务的两次合成验收许可；旧额度与失败记录不变。")
        return

    metrics = dict(
        model_http=0,
        model_dns=0,
        model_socket=0,
        blocked_external=0,
        xhs_connect=0,
        xhs_search=0,
        xhs_detail=0,
        xhs_browser=0,
        amap_http=0,
    )
    metrics_file = workspace / f"metrics-{os.getpid()}.json"
    allowed_transport = False
    resolved: set[str] = set()

    def guard(event: str, values: tuple) -> None:
        nonlocal allowed_transport
        if event == "import" and (
            str(values[0]).startswith("xhs_sidecar") or values[0] == "travel_agent.research.live"
        ):
            raise PermissionError("P04_XHS_DISABLED")
        if event == "urllib.Request":
            from urllib.parse import urlsplit

            url = urlsplit(values[0])
            allowed_transport = (
                args.action == "worker"
                and url.scheme == "https"
                and url.netloc == "api.deepseek.com"
                and url.path in {"/chat/completions", "/v1/chat/completions"}
                and metrics["model_http"] == 0
            )
            if allowed_transport:
                metrics["model_http"] += 1
            else:
                metrics["blocked_external"] += 1
                metrics_file.write_text(json.dumps(metrics), encoding="utf-8")
                raise PermissionError("P04_HTTP_DENIED")
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
                return
            if (
                not allowed_transport
                or (event == "socket.getaddrinfo" and host != "api.deepseek.com")
                or event == "socket.sendto"
            ):
                metrics["blocked_external"] += 1
                metrics_file.write_text(json.dumps(metrics), encoding="utf-8")
                raise PermissionError("P04_EXTERNAL_DENIED")
            if event == "socket.connect" and (
                not isinstance(address, tuple) or address[1] != 443 or host not in resolved
            ):
                raise PermissionError("P04_DESTINATION_DENIED")
            metrics["model_dns" if event == "socket.getaddrinfo" else "model_socket"] += 1
        if event in {"urllib.Request", "socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            metrics_file.write_text(json.dumps(metrics), encoding="utf-8")

    # Bind socket targets to actual provider DNS without an extra DNS/network probe.
    import socket

    original_getaddrinfo = socket.getaddrinfo

    def getaddrinfo(*a, **kw):
        result = original_getaddrinfo(*a, **kw)
        if a and a[0] == "api.deepseek.com":
            resolved.update(r[4][0] for r in result)
        return result

    socket.getaddrinfo = getaddrinfo
    metrics_file.write_text(json.dumps(metrics), encoding="utf-8")
    sys.addaudithook(guard)
    if args.action == "worker":
        run_worker(database, args.job)
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
            "UPDATE preview_jobs SET status='INTERRUPTED',cancel_requested=1 WHERE continuation_id=? AND status IN ('QUEUED','RUNNING')",
            (IDENTIFIER,),
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
        static_dir=PROJECT_ROOT / ".local/p04-web",
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
