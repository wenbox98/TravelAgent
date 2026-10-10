"""Synthetic research across the real supervised extraction boundary; no network."""
# ruff: noqa: F811 -- shared pytest fixture.

from uuid import uuid4
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_goal_agent import Wire, choose, intake, service  # noqa: F401
from test_goal_research_budget import MultiModel, MultiReader
from test_workbench_pipeline import dispatches
from automatic_fakes import config
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CONSENT
from travel_agent.planning.automatic_models import AutomaticStart
from travel_agent.preview import worker


@pytest.mark.parametrize("product", [False, True])
@pytest.mark.parametrize("gaps", [("LODGING",), ("PLAY",), ("ROUTES", "DURATION"), ()])
def test_extraction_command_retains_exact_gap_context(tmp_path, product, gaps):
    command = worker.model_command(
        tmp_path / "synthetic.sqlite3", "extract-worker", "synthetic-attempt",
        product=product, research_gaps=gaps,
    )
    assert command[command.index("--research-gaps") + 1:] == list(gaps)


def test_normal_lodging_research_reaches_extraction_wire_through_child_command(service, monkeypatch):
    oracle = MultiModel()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [
                ("destination", "合成青谷", "合成青谷"), ("days", 3, "三天"),
            ])
        if task == "travel_supervisor_v1":
            if data["previous_results"]:
                return choose("FINISH", stop="PARTIAL")
            return choose("RESEARCH_GAP", query="合成青谷住宿片区", gap_key="LODGING")
        return oracle.structured(task, data, {})

    wire = Wire(monkeypatch, respond)
    child_commands = []

    def supervised(database, attempt, *, command, **kwargs):
        child_commands.append(command)
        # Only the OS boundary is substituted; the ordinary worker and exact
        # serialized model request still execute under the original live grant.
        gaps = tuple(command[command.index("--research-gaps") + 1:])
        with worker.Database(database) as db:
            store = worker.EvidenceStore(db)
            worker.extract_worker(store, config(), attempt, research_gaps=gaps)
            return worker.ExtractionRecovery(store, worker.EvidenceExtractor(config())).outcome(attempt)

    monkeypatch.setattr(worker, "supervise_reserved", supervised)
    view = service.start(AutomaticStart(request="合成青谷三天住宿片区", consent=CONSENT), str(uuid4()))
    _, review = dispatches(config())
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(),
        reader=MultiReader(), review_dispatch=review)
    extracted = [v for v in wire.sent if v["task"] == "select_evidence_references_v1"]
    task = service.plans.get(view["session_id"])["automatic_task"]
    assert child_commands and extracted, (wire.errors, task.get("reason"), task.get("rounds"))
    assert all(v["input"]["research_gaps"] == ["LODGING"] for v in extracted)
    assert any(v["task"] == "review_evidence_context_v2" for v in wire.sent)
    assert not wire.errors


@pytest.mark.parametrize("product", [False, True])
@pytest.mark.parametrize("gaps", [("LODGING",), ()])
def test_actual_child_entry_parser_forwards_gaps_without_external_calls(tmp_path, product, gaps):
    database = tmp_path / "preview.sqlite3"
    with worker.Database(database):
        pass
    command = worker.model_command(
        database, "extract-worker", "synthetic-attempt", product=product, research_gaps=gaps,
    )
    helper = Path(__file__).parents[1] / "helpers/extraction_entry_probe.py"
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(helper), *command[1:]],
        capture_output=True, text=True, encoding="utf8", timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == dict(attempt="synthetic-attempt", research_gaps=list(gaps))


@pytest.mark.parametrize("gaps", [("not a gap",), ("--workspace",), ("A" * 65,), ("LODGING",) * 33])
def test_child_context_cannot_carry_arbitrary_text_or_options(tmp_path, gaps):
    with pytest.raises(ValueError, match="WORKER_GAP_CONTEXT_DENIED"):
        worker.model_command(tmp_path / "synthetic.sqlite3", "extract-worker", "test", research_gaps=gaps)
