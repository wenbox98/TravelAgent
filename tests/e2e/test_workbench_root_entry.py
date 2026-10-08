"""Real built Vue root path; synthetic data only, no stage URL parameters."""

import json
import subprocess
import sys
from pathlib import Path
from travel_agent.persistence.database import Database


def test_built_root_auth_intake_offline_keyboard_and_narrow(tmp_path):
    with Database(tmp_path / "synthetic.sqlite3"):
        pass
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "tests/helpers/entry_ui.py"), str(tmp_path)],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == "PASS"
