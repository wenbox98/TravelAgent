"""Normal workbench API with an explicitly synthetic reader, real supervised loopback LLM."""

import argparse
import asyncio
import json
import secrets
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "tests/integration")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--port", type=int, required=True)
    args = p.parse_args()
    loop = asyncio.new_event_loop()
    attempts = []

    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("SERVER_OUTBOUND_DENIED")
        if event == "import" and str(values[0]).startswith(
            ("xhs_sidecar", "travel_agent.research.live")
        ):
            raise RuntimeError("REAL_READER_DENIED")

    sys.addaudithook(audit)
    import uvicorn
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.preview import worker
    from travel_agent.preview.jobs import JobService
    from travel_agent.persistence.database import Database
    from travel_agent.settings import Settings
    from test_workbench_pipeline import Reader, GRANT

    original = worker.model_command
    worker.model_command = lambda db, kind, identifier: [
        sys.executable,
        str(ROOT / "tests/helpers/loopback_entry.py"),
        *original(db, kind, identifier)[1:],
    ]
    threads = []

    def launch(db, job):
        t = threading.Thread(
            target=worker.run_job,
            args=(db, job),
            kwargs={"reader": Reader(), "provider": worker.configured_provider()},
        )
        threads.append(t)
        t.start()

    worker.launch_job = launch
    keyfile = args.control.with_suffix(".key")
    if not keyfile.exists():
        keyfile.write_bytes(secrets.token_bytes(32))
    with Database(args.database) as db:
        JobService(db, "owner", "CACHED_PRIVATE_PREVIEW", GRANT).reconcile_restart()
    config = PreviewConfig(
        args.database,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        keyfile.read_bytes(),
        continuation=GRANT,
        live_ready=True,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(Settings.load(preferred_port=args.port), preview=config),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_level="error",
        )
    )
    args.control.write_text(json.dumps({"ticket": config.ticket}), encoding="utf-8")

    def stop():
        sys.stdin.readline()
        server.should_exit = True

    threading.Thread(target=stop, daemon=True).start()
    try:
        loop.run_until_complete(server.serve())
    finally:
        for t in threads:
            t.join(10)
        loop.close()
        args.control.with_suffix(".metrics.json").write_text(
            json.dumps({"outbound": attempts, "workers_alive": sum(t.is_alive() for t in threads)}),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
