"""Operator-driven live read smoke. No browser starts on import or without opt-in."""

from pathlib import Path
import sys

from _bootstrap import enter

enter()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/xhs-sidecar"))

from xhs_sidecar.live_smoke import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(ROOT))
