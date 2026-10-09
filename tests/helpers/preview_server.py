"""Loopback-only acceptance server. Deny outbound connections and live imports."""
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--database", type=Path, required=True)
    p.add_argument("--scope", required=True)
    p.add_argument("--mode", required=True)
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--product", action="store_true")
    p.add_argument("--automatic-synthetic", action="store_true")
    p.add_argument("--automatic-subprocess", action="store_true")
    args = p.parse_args()
    attempts = []
    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("PREVIEW_OUTBOUND_DENIED")
        if event == "import" and (str(values[0]).startswith("xhs_sidecar") or values[0] == "travel_agent.research.live" or (not args.product and values[0] == "travel_agent.research.service")):
            raise RuntimeError("PREVIEW_LIVE_IMPORT_DENIED")
    # Allocate only asyncio's Windows wakeup pair before the outbound guard.
    import asyncio
    loop = asyncio.new_event_loop()
    sys.addaudithook(audit)
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.settings import Settings
    import uvicorn
    if args.product and not (args.automatic_synthetic or args.automatic_subprocess):
        import travel_agent.preview.worker as worker
        def missing_configuration():
            raise ValueError("CONFIGURED_120_SECOND_PROVIDER_REQUIRED")
        worker.configured_provider = missing_configuration
    if args.automatic_synthetic:
        # This switch exists ONLY in the deny-network test server, never product CLI.
        from automatic_fakes import config, Model, GoalModel, Reader, research, planning
        import travel_agent.preview.worker as worker
        import travel_agent.planning.suggestions as suggestions
        from travel_agent.planning.automatic import run_task
        worker.configured_provider = config
        suggestions.configured_provider = config
        from test_critical_map import MapTransport
        from travel_agent.providers.amap import AmapAdapter
        AmapAdapter.from_env = staticmethod(MapTransport)
        def launch(database, jid, **options):
            if options.get("question"):
                from travel_agent.planning.questions import run as answer
                threading.Thread(target=lambda:answer(database,jid,Model()),daemon=True).start()
                return
            if not options.get("automatic"):
                raise AssertionError("UNEXPECTED_TEST_DISPATCH")
            def run():
                from travel_agent.persistence.database import Database
                with Database(database) as db:
                    request=db.connection.execute("SELECT request_json FROM planning_tasks WHERE task_id=?",(jid,)).fetchone()
                if json.loads(request[0])["consent"] in {"PRIVATE_GOAL_AGENT_V3", "PRIVATE_GOAL_AGENT_V4"}:
                    from travel_agent.planning.agent import run as goal_run
                    from test_workbench_pipeline import dispatches
                    model=GoalModel()
                    extract,review=dispatches(model)
                    goal_run(database,jid,provider=model,reader=Reader(),extract_dispatch=extract,review_dispatch=review)
                    return
                model, reader = Model(), Reader()
                run_task(database, jid, research_runner=research(model, reader), planning_runner=planning(model))
            threading.Thread(target=run,daemon=True).start()
        suggestions.launch = launch
    if args.automatic_subprocess:
        from dispatch_worker import install
        install(args.database)
    key_file = args.control.with_suffix(".key")
    if not key_file.exists():
        key_file.write_bytes(secrets.token_bytes(32))
    config = PreviewConfig(args.database, args.scope, args.mode, key_file.read_bytes(), product_flow=args.product, daily_workbench=args.product)
    server = uvicorn.Server(uvicorn.Config(create_app(Settings.load(preferred_port=args.port), preview=config),
        host="127.0.0.1", port=args.port, access_log=False, log_level="error", loop="asyncio"))
    args.control.write_text(json.dumps({"ticket": config.ticket}), encoding="utf-8")
    def stop():
        sys.stdin.readline()
        server.should_exit = True
    threading.Thread(target=stop, daemon=True).start()
    try:
        loop.run_until_complete(server.serve())
    finally:
        loop.close()
        args.control.with_suffix(".metrics.json").write_text(json.dumps({"outbound_attempts": attempts,
            "live_imports": [name for name in sys.modules if name.startswith("xhs_sidecar") or name == "travel_agent.research.live"]}), encoding="utf-8")


if __name__ == "__main__":
    main()
