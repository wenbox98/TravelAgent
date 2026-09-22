from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def enter():
    python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        if not python.exists():
            raise SystemExit("请先运行 uv sync --locked 安装开发依赖")
        raise SystemExit(subprocess.call([str(python), *sys.argv], cwd=ROOT))
    sys.path.insert(0, str(ROOT / "apps/api"))
