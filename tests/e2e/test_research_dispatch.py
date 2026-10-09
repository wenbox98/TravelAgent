"""Normal built UI and actual production subprocess dispatch; authored I/O only."""
from pathlib import Path
import subprocess
import sys


def test_startup_failure_conditions_and_new_intent_subprocess_chain(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-X", "utf8", str(root / "tests/helpers/research_dispatch_ui.py"), str(tmp_path)], cwd=root, capture_output=True, text=True, encoding="utf8", timeout=150)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"external_calls": 0' in result.stdout
    assert '"production_subprocess_chain": true' in result.stdout
