"""Run the offline sidecar; never launches a browser or accesses Xiaohongshu."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations/xhs-sidecar"))

from xhs_sidecar.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
