"""Explicit T06.1 live entry; profile and private research SQLite remain separate."""

from pathlib import Path
import sys

from _bootstrap import enter

enter()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/xhs-sidecar"))

from travel_agent.research.private_smoke import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
