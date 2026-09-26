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
    args = p.parse_args()
    attempts = []
    def audit(event, values):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            attempts.append(event)
            raise RuntimeError("PREVIEW_OUTBOUND_DENIED")
        if event == "import" and (str(values[0]).startswith("xhs_sidecar") or values[0] in {"travel_agent.research.live", "travel_agent.research.service"}):
            raise RuntimeError("PREVIEW_LIVE_IMPORT_DENIED")
    # Allocate only asyncio's Windows wakeup pair before the outbound guard.
    import asyncio
    loop = asyncio.new_event_loop()
    sys.addaudithook(audit)
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.settings import Settings
    import uvicorn
    key_file = args.control.with_suffix(".key")
    if not key_file.exists():
        key_file.write_bytes(secrets.token_bytes(32))
    config = PreviewConfig(args.database, args.scope, args.mode, key_file.read_bytes())
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
