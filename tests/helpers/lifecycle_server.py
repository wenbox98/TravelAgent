"""Isolated synthetic fault server/actor. Never imported by product entry points."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/api"), str(ROOT / "tests/integration"), str(ROOT / "tests/helpers")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "serve", "actor"])
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--static", type=Path, default=ROOT / ".local/interruption-ui-web")
    p.add_argument("--port", type=int, default=18778)
    p.add_argument("--recover", action="store_true")
    p.add_argument("--dispatch", choices=["hold", "nonzero", "deadline"])
    args = p.parse_args()
    ws = args.workspace.resolve()
    assert ws.is_relative_to(ROOT / ".local") and "lifecycle" in ws.name
    ws.mkdir(parents=True, exist_ok=True)
    # Windows asyncio needs its private wakeup pair before the outbound fence.
    loop = asyncio.new_event_loop() if args.action == "serve" else None
    metrics = ws / f"metrics-{os.getpid()}.json"
    blocked = []

    def flush():
        metrics.write_text(json.dumps({"external_attempts": blocked}), encoding="utf8")

    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            blocked.append(event)
            flush()
            raise RuntimeError("LIFECYCLE_EXTERNAL_DENIED")
        if event == "import" and str(values[0]).startswith("xhs_sidecar"):
            raise RuntimeError("LIFECYCLE_BROWSER_IMPORT_DENIED")

    flush()
    sys.addaudithook(audit)
    if args.action == "actor":
        if args.dispatch == "nonzero":
            until = time.monotonic() + 600
            while not (ws / "release-worker").exists() and time.monotonic() < until:
                time.sleep(.1)
            raise SystemExit(7)
        time.sleep(600)
        return

    from travel_agent.persistence.database import Database
    from travel_agent.planning.automatic import AutomaticService, recover
    from travel_agent.planning import suggestions
    import travel_agent.preview.worker as worker
    from automatic_fakes import config

    worker.configured_provider = suggestions.configured_provider = config
    database = ws / "preview.sqlite3"
    if args.action == "prepare":
        assert not database.exists(), "Do not overwrite an existing test workspace"
        from test_worker_lifecycle import pending_review
        with Database(database) as db:
            service = AutomaticService(db, "owner")
            view, tid, gid, aid, rid = pending_review(service)
            row = db.connection.execute("SELECT state_json FROM preview_sessions WHERE session_id=?", (view["session_id"],)).fetchone()
            state = json.loads(row[0])
            state["planning"]["agent_rounds"] = [dict(round=1, tool="RESEARCH_GAP", status="DISPATCHED", reason="合成故障测试，未访问任何网站。")]
            db.connection.execute("UPDATE preview_sessions SET state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), view["session_id"]))
            (ws / "fixture.json").write_text(json.dumps(dict(task=tid, grant=gid, attempt=aid, review=rid, session=view["session_id"])), encoding="utf8")
        print("SYNTHETIC_FIXTURE_READY")
        return

    if args.recover:
        with Database(database) as db, db.transaction():
            recover(db)
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.settings import Settings
    import uvicorn
    key = ws / "auth.key"
    if not key.exists():
        key.write_bytes(os.urandom(32))
    cfg = PreviewConfig(database, "owner", "CACHED_PRIVATE_PREVIEW", key.read_bytes(),
                        product_flow=True, daily_workbench=True, static_dir=args.static)
    control = dict(pid=os.getpid(), port=args.port, ticket=cfg.ticket)
    (ws / "control.json").write_text(json.dumps(control), encoding="utf8")
    if args.dispatch:
        original = subprocess.Popen

        def launch(command, **kwargs):
            proc = original([sys.executable, str(Path(__file__).resolve()), "actor", "--workspace", str(ws), "--dispatch", args.dispatch], **kwargs)
            (ws / "worker.json").write_text(json.dumps(dict(pid=proc.pid)), encoding="utf8")
            return proc

        suggestions.subprocess.Popen = launch
        if args.dispatch == "deadline":
            original_clock = suggestions.monotonic
            suggestions.monotonic = lambda: original_clock() + (4000 if (ws / "release-worker").exists() else 0)
        fixture = json.loads((ws / "fixture.json").read_text())
        suggestions.launch(database, fixture["task"], automatic=True)
    server = uvicorn.Server(uvicorn.Config(create_app(Settings.load(preferred_port=args.port), preview=cfg),
                            host="127.0.0.1", port=args.port, access_log=False, log_level="error", loop="asyncio"))
    try:
        loop.run_until_complete(server.serve())
    finally:
        flush()
        loop.close()


if __name__ == "__main__":
    main()
