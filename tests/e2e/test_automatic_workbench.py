"""Run normal-page single-click workflow in a deny-network child process."""

from pathlib import Path
import subprocess
import sys


def test_automatic_single_click_browser(tmp_path):
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(root / "tests/helpers/automatic_ui.py"),
            str(tmp_path / "automatic-ui"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"external_calls": 0' in result.stdout
