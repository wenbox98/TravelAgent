"""Developer launcher; no worker or sidecar is started in T00/T01."""
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    return subprocess.call([sys.executable, str(root / "scripts/dev.py"), "--mode", "mock"], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
