"""Single explicit intent exercises real research, review, planning and durable counts."""

import sys
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from travel_agent.persistence.database import Database
from travel_agent.planning.automatic import AutomaticService, run_task, recover, revise
from travel_agent.planning.automatic_models import AutomaticStart, AutomaticAction, CONSENT
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.flow_models import PlanAction, PlanDraft
from travel_agent.preview.api import PreviewConfig
from travel_agent.main import create_app
from travel_agent.settings import Settings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
from automatic_fakes import config, Model, Reader, research, planning  # noqa: E402


@pytest.fixture
def automatic(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    with Database(tmp_path / "auto.sqlite3") as db:
        yield AutomaticService(db, "owner")


def start(s, text="我想去合成青谷玩7天", key=None):
    return s.start(AutomaticStart(request=text, consent=CONSENT), key or str(uuid4()))


def test_single_click_real_chain_counts_results_followup_and_recovery(automatic):
    s = automatic
    key = str(uuid4())
    v = start(s, key=key)
    assert v["automatic_task"]["status"] == "QUEUED"
    assert start(s, key=key)["session_id"] == v["session_id"]
    model, reader = Model(), Reader()
    tid = v["automatic_task"]["task_id"]
    run_task(
        s.db.path, tid, research_runner=research(model, reader), planning_runner=planning(model)
    )
    v = s.plans.get(v["session_id"])
    assert v["automatic_task"]["status"] == "COMPLETED", v["automatic_task"]
    assert v["job"]["proposals"] and v["job"]["can_preview"]
    assert v["adopted"] is None
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL"]
    assert len(model.calls) == 3
    assert v["automatic_task"]["new_body_count"] == 1
    assert v["automatic_task"]["budget"]["used"]["model"] == 3
    run_task(s.db.path, tid, research_runner=lambda *_: pytest.fail("replayed"))
    v = s.plans.mutate(
        v["session_id"],
        PlanAction(action="use_proposal", expected_revision=v["revision"]),
        str(uuid4()),
    )
    v = s.plans.mutate(
        v["session_id"], PlanAction(action="adopt", expected_revision=v["revision"]), str(uuid4())
    )
    adopted = v["adopted"]
    v = s.action(
        v["session_id"],
        AutomaticAction(
            action="revise",
            text="只有5天，不想自驾，想轻松一点",
            expected_revision=v["revision"],
            consent=CONSENT,
        ),
        str(uuid4()),
    )
    assert (
        v["draft"]["days"] == 5
        and v["draft"]["driving"] == "NO"
        and v["draft"]["pace"] == "RELAXED"
    )
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=lambda *_: pytest.fail("unnecessary research"),
        planning_runner=planning(model),
    )
    v = s.plans.get(v["session_id"])
    assert v["automatic_task"]["status"] == "COMPLETED", v["automatic_task"]
    assert len(model.calls) == 4 and v["adopted"] == adopted
    assert v["operation"]["cumulative_used"]["model"] == 4
    with Database(s.db.path) as db:
        recover(db)
        restored = PlanningService(db, "owner").get(v["session_id"])
        assert restored["job"]["proposals"] == v["job"]["proposals"]
        assert restored["adopted"] == adopted


def test_cancel_and_manual_change_invalidate_before_dispatch(automatic):
    s = automatic
    v = start(s)
    tid = v["automatic_task"]["task_id"]
    s.action(
        v["session_id"],
        AutomaticAction(action="cancel", expected_revision=v["revision"]),
        str(uuid4()),
    )
    run_task(s.db.path, tid, research_runner=lambda *_: pytest.fail("canceled dispatch"))
    assert not s.db.connection.execute("SELECT * FROM continuation_operations").fetchall()
    v = start(s)
    tid = v["automatic_task"]["task_id"]
    draft = PlanDraft.model_validate(v["draft"])
    draft.days = 5
    v = s.plans.mutate(
        v["session_id"],
        PlanAction(action="save", draft=draft, expected_revision=v["revision"]),
        str(uuid4()),
    )
    assert v["automatic_task"]["status"] == "CANCELED"
    run_task(s.db.path, tid, research_runner=lambda *_: pytest.fail("obsolete dispatch"))


def test_cancel_receipt_recovers_unknown_response_and_rejects_key_reuse(automatic):
    s = automatic
    v = start(s)
    key = str(uuid4())
    body = AutomaticAction(action="cancel", expected_revision=v["revision"])
    result = s.action(v["session_id"], body, key)
    assert result["automatic_task"]["intent_key"] == key
    replay = s.action(v["session_id"], body, key)
    assert replay["revision"] == result["revision"]
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        start(s, key=key)


def test_no_configuration_no_network_and_explicit_resume(automatic, monkeypatch):
    s = automatic

    def missing():
        raise ValueError("CONFIGURED_120_SECOND_PROVIDER_REQUIRED")

    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", missing)
    v = start(s)
    assert v["automatic_task"]["status"] == "WAITING_CONFIGURATION"
    assert not s.db.connection.execute("SELECT * FROM research_continuations").fetchall()
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    v = s.action(
        v["session_id"],
        AutomaticAction(action="continue", expected_revision=v["revision"], consent=CONSENT),
        str(uuid4()),
    )
    assert v["automatic_task"]["status"] == "QUEUED"


def test_zero_reads_csrf_and_versioned_explicit_intent(automatic, monkeypatch):
    s = automatic
    launches = []
    monkeypatch.setattr(
        "travel_agent.planning.suggestions.launch", lambda *a, **kw: launches.append((a, kw))
    )
    cfg = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"fixture",
        product_flow=True,
        daily_workbench=True,
    )
    with TestClient(
        create_app(Settings.load(preferred_port=18773), preview=cfg),
        base_url="http://127.0.0.1:18773",
    ) as client:
        body = dict(request="我想去合成青谷玩7天", consent=CONSENT)
        assert client.post("/api/v1/preview/automatic-planning", json=body).status_code == 401
        client.get("/bootstrap?ticket=" + cfg.ticket)
        csrf = client.get("/api/v1/preview").json()["csrf_token"]
        assert client.post("/api/v1/preview/automatic-planning", json=body).status_code == 403
        headers = {
            "origin": "http://127.0.0.1:18773",
            "x-csrf-token": csrf,
            "idempotency-key": str(uuid4()),
        }
        assert (
            client.post(
                "/api/v1/preview/automatic-planning",
                json={"request": body["request"]},
                headers=headers,
            ).status_code
            == 422
        )
        result = client.post("/api/v1/preview/automatic-planning", json=body, headers=headers)
        assert result.status_code == 200, result.text
        sid = result.json()["session_id"]
        for _ in range(3):
            client.get("/api/v1/preview/planning/" + sid)
        assert len(launches) == 1 and launches[0][1] == {"automatic": True}
        assert not s.db.connection.execute("SELECT * FROM continuation_operations").fetchall()


@pytest.mark.parametrize("days", [1, 3, 5, 9])
def test_generic_constraints_unknowns_and_locked_times(days):
    draft = PlanDraft(planning_mode="ADVISORY", days=12, walking_allowed=None)
    out = revise(draft, f"只有{days}天，不想自驾，想轻松一点")
    assert out.days == days and out.driving == "NO" and out.pace == "RELAXED"
    assert out.walking_allowed is None and out.inputs.activity_start is None
    with pytest.raises(ValueError, match="AUTOMATIC_CLARIFY_CHANGE"):
        revise(out, "不错")


def test_site_challenge_stops_without_model_or_retry(automatic):
    from travel_agent.research.models import ResearchStopped

    s = automatic
    v = start(s)
    model = Model()

    class Challenge(Reader):
        def connect(self):
            self.calls.append("CONNECT")
            raise ResearchStopped("VERIFICATION_REQUIRED", "VERIFICATION_REQUIRED")

    reader = Challenge()
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=lambda *_: pytest.fail("must stop"),
    )
    v = s.plans.get(v["session_id"])
    assert v["automatic_task"]["status"] == "BLOCKED"
    assert "VERIFICATION_REQUIRED" in v["automatic_task"]["reason"]
    assert reader.calls == ["CONNECT"] and model.calls == []
    assert (
        not v["automatic_task"]["research_attempted"] and not v["automatic_task"]["new_body_count"]
    )
    with pytest.raises(ValueError, match="AUTOMATIC_NO_RETRY"):
        s.action(
            v["session_id"],
            AutomaticAction(action="continue", expected_revision=v["revision"], consent=CONSENT),
            str(uuid4()),
        )


def test_late_research_cannot_commit_after_current_conditions_change(automatic):
    s = automatic
    v = start(s)
    model, reader = Model(), Reader()

    def late(path, jid):
        research(model, reader)(path, jid)
        latest = s.plans.get(v["session_id"])
        draft = PlanDraft.model_validate(latest["draft"])
        draft.days = 3
        s.plans.mutate(
            v["session_id"],
            PlanAction(action="save", expected_revision=latest["revision"], draft=draft),
            str(uuid4()),
        )

    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=late,
        planning_runner=lambda *_: pytest.fail("obsolete planning"),
    )
    latest = s.plans.get(v["session_id"])
    assert latest["automatic_task"]["status"] == "CANCELED"
    assert latest["draft"]["days"] == 3 and latest["job"] is None
    assert latest["draft"]["activities"] == []


def test_shorter_trip_recomputes_unlocked_days_but_never_moves_appointment():
    from travel_agent.planning.flow_models import Activity

    draft = PlanDraft(
        planning_mode="ADVISORY",
        days=7,
        activities=[
            Activity(activity_id="example", name="合成公园", provenance="SOURCE_REFERENCE", day=7)
        ],
    )
    out = revise(draft, "只有5天")
    assert out.days == 5 and draft.activities[0].day == 7
    draft.activities[0].locked_start = "10:00"
    with pytest.raises(ValueError, match="PLANNING_LOCKED_CONSTRAINT"):
        revise(draft, "只有5天")


def test_restart_marks_pending_interrupted_and_never_dispatches(automatic):
    s = automatic
    v = start(s)
    recover(s.db)
    restored = s.plans.get(v["session_id"])
    assert restored["automatic_task"]["status"] == "INTERRUPTED"
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=lambda *_: pytest.fail("restarted dispatch"),
    )
    assert not s.db.connection.execute("SELECT * FROM continuation_operations").fetchall()


def test_cached_reviewed_material_reuses_but_test_trip_is_not_default_fallback(
    automatic, monkeypatch
):
    from travel_agent.planning.automatic import save

    s = automatic
    original = start(s)
    run_task(
        s.db.path,
        original["automatic_task"]["task_id"],
        research_runner=research(Model(), Reader()),
        planning_runner=planning(Model()),
    )
    # Exercise the reviewed raw fallback independently of the card-first path.
    monkeypatch.setattr(
        "travel_agent.knowledge.store.Library.search", lambda *a, **kw: {"cards": []}
    )
    reused = start(s)
    assert reused["draft"]["activities"]
    assert reused["automatic_task"]["limits"]["search"] == 0
    s.action(
        reused["session_id"],
        AutomaticAction(action="cancel", expected_revision=reused["revision"]),
        str(uuid4()),
    )
    _, state = s.plans.load(original["session_id"])
    state["planning"]["validation_trip"] = True
    save(s.db, original["session_id"], state, bump=False)
    fresh = start(s)
    assert not fresh["draft"]["activities"]
    assert fresh["automatic_task"]["cache_source_count"] == 0
    assert fresh["automatic_task"]["limits"]["search"] == 1
