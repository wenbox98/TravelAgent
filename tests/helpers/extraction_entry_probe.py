"""Exercise the actual entry parser with a synthetic database and no provider I/O."""
import json
from pathlib import Path
import runpy
import socket
import sys


def denied(*args, **kwargs):
    raise AssertionError("External I/O forbidden in child entry probe")


socket.socket.connect = denied
socket.create_connection = denied
socket.getaddrinfo = denied
root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "apps/api"))
sys.path.insert(0, str(root / "scripts"))
from travel_agent.preview import worker  # noqa: E402


def capture(store, provider, attempt, *, research_gaps=()):
    print(json.dumps(dict(attempt=attempt, research_gaps=list(research_gaps))))


worker.configured_provider = lambda: object()
worker.extract_worker = capture
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
