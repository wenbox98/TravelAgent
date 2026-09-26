"""Run the built UI on authored, explicitly synthetic cached sources."""
import json
from pathlib import Path
import subprocess
import sys

from travel_agent.persistence.database import Database

ROOT = Path(__file__).resolve().parents[2]


def test_built_vue_choice_cancel_restart_local_only(tmp_path, clock):
    sys.path.insert(0, str(ROOT / "tests/integration"))
    from test_cached_overview import seed
    path = tmp_path / "synthetic.sqlite3"
    with Database(path, clock=clock) as db:
        seed(db, clock)
        db.connection.execute("UPDATE sources SET is_synthetic=1,source_type='SYNTHETIC'")
        db.connection.execute("UPDATE sources SET title='<b id=source-injected>合成标题</b>'")
        row = db.connection.execute("SELECT policy_json FROM source_policies").fetchone()
        policy = json.loads(row[0])
        policy["basis"] = "SYNTHETIC"
        db.connection.execute("UPDATE source_policies SET policy_json=?", (json.dumps(policy),))
    child = subprocess.run([sys.executable, str(ROOT / "tests/helpers/preview_ui.py"),
        "--database", str(path), "--scope", "owner", "--mode", "SYNTHETIC_DEMO",
        "--research", "partial", "--output", str(tmp_path / "ui"), "--count", "2"],
        cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert child.returncode == 0, child.stderr
    result = json.loads(child.stdout)
    assert result["status"] == "PASS" and result["external_page_requests"] == []
