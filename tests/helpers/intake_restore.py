"""Restore synthetic stopped intake in another process, with outbound I/O denied."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/api"))
attempts = []


def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen"}:
        attempts.append(event)
        raise AssertionError("RESTORE_EXTERNAL_DENIED")
    if event == "import" and (str(args[0]).startswith("xhs_sidecar")
                              or args[0] == "travel_agent.research.live"):
        raise AssertionError("RESTORE_LIVE_IMPORT_DENIED")


sys.addaudithook(audit)
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.planning.flow import PlanningService  # noqa: E402

with Database(Path(sys.argv[1])) as db:
    v = PlanningService(db, "owner").get(sys.argv[2])
    t = v["automatic_task"]
    print(json.dumps(dict(model_executed=t["understanding"]["model_executed"],
        failure=t["understanding"]["failure"], used_model=t["budget"]["used"]["model"],
        attempts=len(attempts))))
