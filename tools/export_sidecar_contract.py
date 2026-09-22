"""Export/check the offline sidecar contract without starting ASGI or a browser."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "integrations/xhs-sidecar"))

from pydantic import SecretStr  # noqa: E402
from xhs_sidecar.app import SidecarConfig, create_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    # Synthetic construction-only value; never a deployed credential or part of the schema.
    app = create_app(SidecarConfig(secret=SecretStr("SYNTHETIC_CONTRACT_EXPORT_" * 2)))
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
    path = ROOT / "contracts/xhs-sidecar.openapi.json"
    if args.check:
        if not path.exists() or path.read_text("utf-8") != text:
            print("FAIL: sidecar contract snapshot differs")
            return 1
        print("PASS: offline sidecar contract snapshot matches")
    else:
        path.write_text(text, encoding="utf-8")
        print("Exported offline sidecar contract (no server/browser/network)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
