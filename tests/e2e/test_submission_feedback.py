"""Visible feedback on the built normal page; synthetic loopback server only."""

from pathlib import Path
import subprocess
import sys


def test_submission_feedback_duplicate_ime_and_unknown_recovery(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(root / "tests/helpers/submission_ui.py"), str(tmp_path)],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"external_calls": 0' in result.stdout
