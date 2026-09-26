import json
from pathlib import Path
import sys

from travel_agent.domain.models import validator
from travel_agent.preview.models import PreviewMutation

ROOT = Path(__file__).resolve().parents[2]


def test_preview_models_match_checked_in_contract():
    sys.path.insert(0, str(ROOT / "tools"))
    from export_preview_contract import definitions
    domain = json.loads((ROOT / "contracts/domain.schema.json").read_text(encoding="utf-8"))
    assert all(domain["$defs"][k] == v for k, v in definitions().items())
    payload = {"action": "preferences", "expected_revision": 3, "preferences": {"days": 5, "driving": "NO"}}
    validator("PreviewMutation").validate(payload)
    assert PreviewMutation.model_validate(payload).expected_revision == 3
