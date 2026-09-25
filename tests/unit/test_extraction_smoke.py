"""Same synthetic business entry, offline provider, durable budget protection."""

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from travel_agent.providers.diagnostics import Diagnostic
from travel_agent.providers.llm import LLMError


def test_synthetic_entry_valid_policy_body_and_cannot_repeat(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("extraction_smoke", root / "scripts/extraction_smoke.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures/t062-synthetic-travel.txt").write_bytes((root / "fixtures/t062-synthetic-travel.txt").read_bytes())
    calls = []
    class Provider:
        base_url = "https://api.deepseek.com"
        is_external = True
        is_mock = False
        def structured(self, task, payload, schema):
            assert payload["is_synthetic"] and task == "extract_evidence"
            # One block mentions contact information and is conservatively omitted.
            assert len(payload["blocks"]) == 15
            calls.append(True)
            raise LLMError(diagnostic=Diagnostic(stage="TRANSPORT", category="TIMEOUT", http_attempts=1))
    monkeypatch.setattr(module.OpenAICompatibleProvider, "from_env", lambda: Provider())
    result = module.run()
    assert result["status"] == "FAILED" and result["source_saved"]
    assert result["normalized_chars"] == 1379 and result["body_blocks"] == 16
    with pytest.raises(FileExistsError):
        module.run()
    with pytest.raises(AssertionError):
        module.run(resume_before_dispatch=True)
    retried = module.run("a" * 40)
    assert retried["status"] == "FAILED" and retried["diagnostic"]["retry_count"] == 1
    with pytest.raises(ValueError, match="BUDGET_OR_RETRY_DENIED"):
        module.run("b" * 40)
    assert len(calls) == 2
    ledger = json.loads((tmp_path / ".local/t06.2-synthetic/attempt.json").read_text(encoding="utf-8"))
    assert ledger["attempt_id"] == result["attempt_id"]
