"""Child boundary for synthetic HTTP worker tests. Never used by production dispatch."""

import runpy
import sys
from pathlib import Path


def guard(event, args):
    if event in {"socket.connect", "socket.sendto"} and args[1][0] not in {"127.0.0.1", "::1"}:
        raise RuntimeError("TEST_EXTERNAL_DENIED")
    if event == "socket.getaddrinfo" and args[0] not in {"127.0.0.1", "::1", None}:
        raise RuntimeError("TEST_EXTERNAL_DNS_DENIED")


sys.addaudithook(guard)
sys.argv = sys.argv[1:]
sys.path.insert(0, str(Path(sys.argv[0]).parent))
runpy.run_path(sys.argv[0], run_name="__main__")
