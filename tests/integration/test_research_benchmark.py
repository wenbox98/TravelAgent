"""Fixture-declared quality expectations and local-only CLI contract."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.research.benchmark import QualityBenchmark, live_preflight

ROOT = Path(__file__).resolve().parents[2]
SPEC = json.loads((ROOT / "fixtures/research-quality-benchmark.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", SPEC["cases"], ids=lambda case: case["id"] + "-" + case["scenario"])
def test_declared_quality_scenario(case):
    observed = QualityBenchmark(ROOT).evaluate(case["scenario"])
    for key, expected in case["expect"].items():
        assert observed[key] == expected, (case["id"], key, observed[key])
    assert observed["unsupported_claims"] == 0
    if observed["evaluated_claim_instances"]:
        assert observed["locator_coverage"] == 1


def test_benchmark_summary_and_example_are_synthetic_and_grounded():
    benchmark = QualityBenchmark(ROOT)
    metrics = benchmark.run()
    assert metrics["scenario_count"] >= 20 and metrics["failed"] == 0
    assert metrics["passed"] == len(SPEC["cases"])
    assert metrics["unsupported_claims"] == 0 and metrics["locator_coverage"] == 1
    assert metrics["live_operations"] == 0 and metrics["real_model_verified"] is False
    rendered = benchmark.example_markdown()
    assert "非真实攻略" in rendered and "Mock" in rendered
    assert "青岚环线" in rendered and "苍原区域" in rendered
    assert "note-body:v2:STATE:" in rendered and "5 天" in rendered and "不自驾" in rendered
    assert "G1 真实质量通过" in rendered


@pytest.mark.parametrize("environment,status", [
    ({}, "G1_LIVE_LLM_BLOCKED"),
    ({"LLM_MODEL": "synthetic-model"}, "G1_LIVE_LLM_BLOCKED"),
    ({"LLM_MODEL": "synthetic-model", "LLM_API_KEY": "SYNTHETIC_KEY",
      "LLM_BASE_URL": "https://example.invalid/v1"}, "G1_LIVE_SOURCE_POLICY_BLOCKED"),
])
def test_live_preflight_is_read_only_and_does_not_claim_model_validation(environment, status):
    result = live_preflight(environment)
    assert result["status"] == status and result["live_operations"] == 0
    assert "SYNTHETIC_KEY" not in json.dumps(result)


def test_cli_refuses_nonexistent_cache_without_creating_database(tmp_path):
    database = tmp_path / "absent.sqlite3"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/research_quality.py"), "clear-cache",
                             "--database", str(database), "--account-scope", "synthetic"],
                            cwd=ROOT, capture_output=True, text=True, timeout=20, check=False)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "CACHE_NOT_FOUND"
    assert not database.exists()
