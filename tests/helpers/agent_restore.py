"""Read nonempty agent results in a separate process with all outbound calls denied."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/api"))
attempts = []


def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto", "subprocess.Popen"}:
        attempts.append(event)
        raise AssertionError("RESTORE_EXTERNAL_DENIED")
    if event == "import" and (
        str(args[0]).startswith("xhs_sidecar") or args[0] == "travel_agent.research.live"
    ):
        raise AssertionError("RESTORE_LIVE_IMPORT_DENIED")


sys.addaudithook(audit)
from travel_agent.persistence.database import Database  # noqa: E402
from travel_agent.planning.flow import PlanningService  # noqa: E402
from travel_agent.planning.automatic import recover  # noqa: E402

with Database(Path(sys.argv[1])) as db:
    recover(db)
    v = PlanningService(db, "owner").get(sys.argv[2])
    print(
        json.dumps(
            dict(
                days=v["draft"]["days"],
                transport=v["draft"]["transport"],
                proposals=len(v["job"]["proposals"]),
                external_attempts=len(attempts),
            )
        )
    )
