import argparse
import subprocess
import sys
from _bootstrap import ROOT, enter


def main():
    enter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["unit", "contract", "integration", "security", "e2e"], required=True)
    args = parser.parse_args()
    path = ROOT / "tests" / args.suite
    if not path.exists() or not list(path.glob("test_*.py")):
        print(f"SKIPPED: {args.suite} 尚无已实现测试")
        return 5
    return subprocess.call([sys.executable, "-m", "pytest", str(path), "-q"], cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
