import json
from pathlib import Path
import subprocess
import sys


def test_vue_explicit_job_real_workers_and_nonempty_restart(tmp_path):
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run(
        [
            sys.executable,
            str(root / "tests/helpers/workbench_ui.py"),
            "--output",
            str(tmp_path / "ui"),
        ],
        capture_output=True,
        text=True,
        cwd=root,
        timeout=90,
    )
    assert child.returncode == 0, child.stderr
    result = json.loads(child.stdout)
    assert result["status"] == "PASS" and result["real_loopback_model_requests"] == 2
    assert not result["external_requests"] and result["cross_process_recovery"]
