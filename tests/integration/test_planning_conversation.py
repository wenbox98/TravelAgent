"""Production conversation and next payload; authored offline adapters only."""

from copy import deepcopy
from pathlib import Path
import sys
from uuid import uuid4
import pytest
from travel_agent.persistence.database import Database
from travel_agent.planning.automatic import AutomaticService, run_task, recover
from travel_agent.planning.automatic_models import AutomaticStart, CONSENT
from travel_agent.planning.conversation import action, ConversationAction, model_context
from travel_agent.planning.suggestions import payload_for

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
from automatic_fakes import Model, Reader, config, research, planning  # noqa: E402


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    with Database(tmp_path / "conversation.sqlite3") as db:
        s = AutomaticService(db, "owner")
        v = s.start(AutomaticStart(request="我想去合成青谷玩7天", consent=CONSENT), str(uuid4()))
        model, reader = Model(), Reader()
        run_task(
            db.path,
            v["automatic_task"]["task_id"],
            research_runner=research(model, reader),
            planning_runner=planning(model),
        )
        yield s, s.plans.get(v["session_id"]), model, reader


def send(s, v, act, *, key=None, **fields):
    body = ConversationAction(
        action=act,
        expected_revision=v["revision"],
        expected_conversation_version=v["conversation"]["version"],
        **fields,
    )
    return action(s.db, "owner", v["session_id"], body, key or str(uuid4()))


def test_choice_question_constraint_and_next_payload_include_entire_relevant_state(conversation):
    s, v, model, reader = conversation
    original = deepcopy(v["draft"])
    chosen = v["conversation"]["options"][0]["option_id"]
    v = send(s, v, "select", option_id=chosen)
    assert v["draft"] == original and v["adopted"] is None
    assert v["conversation"]["selected"]["option_id"] == chosen and v["job"]["can_preview"]
    _, before = s.plans.load(v["session_id"])
    payload = payload_for(before["planning"], s.db, "owner", v["session_id"])
    usage = v["operation"]["cumulative_used"]
    v = send(s, v, "message", text="为什么推荐这个？")
    _, after = s.plans.load(v["session_id"])
    assert payload_for(after["planning"], s.db, "owner", v["session_id"]) == payload
    assert v["draft"] == original and v["operation"]["cumulative_used"] == usage
    assert v["conversation"]["messages"][-1]["citations"] and v["job"]["can_preview"]
    v = send(s, v, "message", text="只有5天，不想自驾", consent=CONSENT)
    assert v["draft"]["days"] == 5 and v["draft"]["driving"] == "NO"
    captured = []

    class Capture(Model):
        def structured(self, task, data, schema):
            if task == "planning_advisory_v4":
                captured.append(deepcopy(data))
            return super().structured(task, data, schema)

    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(Capture()),
    )
    v = s.plans.get(v["session_id"])
    assert v["job"]["proposals"] and captured, v["automatic_task"]
    data = captured[-1]
    assert data["conversation"]["selected"]["option_id"] == chosen
    assert data["days"] == 5 and data["driving"] == "NO"
    assert "只有5天，不想自驾" in data["conversation"]["user_inputs"]
    assert any("为什么" in m["text"] for m in data["conversation"]["recent_messages"])
    assert data["conversation"]["material_coverage"]["gaps"]
    assert not v["conversation"]["selected_current"]
    with Database(s.db.path) as db:
        recover(db)
        restored = AutomaticService(db, "owner").plans.get(v["session_id"])
        assert restored["conversation"] == v["conversation"]
        assert restored["job"]["proposals"] == v["job"]["proposals"]


def test_exclusion_clear_and_versioned_receipt_are_local(conversation):
    s, v, model, reader = conversation
    choice = v["conversation"]["options"][0]["option_id"]
    used = v["operation"]["cumulative_used"]
    v = send(s, v, "exclude", option_id=choice)
    assert len(v["conversation"]["excluded"]) == 1
    v = send(s, v, "clear", option_id=choice)
    assert not v["conversation"]["excluded"] and v["conversation"]["selected"] is None
    old = deepcopy(v)
    key = str(uuid4())
    v = send(s, v, "select", option_id=choice, key=key)
    again = send(s, old, "select", option_id=choice, key=key)
    assert again["conversation"] == v["conversation"]
    with pytest.raises(ValueError, match="STALE_CONVERSATION_VERSION"):
        send(s, old, "exclude", option_id=choice)
    assert v["operation"]["cumulative_used"] == used
    assert len(model.calls) == 5 and reader.calls.count("CONNECT") == 1


def test_excluded_activity_is_not_recommended_in_next_loop_and_can_be_restored(conversation):
    s, v, model, reader = conversation
    aid = v["draft"]["activities"][0]["activity_id"]
    v = send(s, v, "exclude_activity", activity_id=aid)
    assert aid in v["conversation"]["excluded_activities"]
    v = send(s, v, "restore_activity", activity_id=aid)
    assert aid not in v["conversation"]["excluded_activities"]
    v = send(s, v, "exclude_activity", activity_id=aid)
    v = send(s, v, "continue", consent=CONSENT)
    run_task(
        s.db.path,
        v["automatic_task"]["task_id"],
        research_runner=research(model, reader),
        planning_runner=planning(model),
    )
    v = s.plans.get(v["session_id"])
    assert v["job"]["proposals"], v["automatic_task"]
    assert all(a["activity_id"] != aid for p in v["job"]["proposals"] for a in p["activities"])
    assert v["adopted"] is None


def test_no_consent_does_not_dispatch_and_private_free_text_stays_local(conversation):
    s, v, _, _ = conversation
    usage = v["operation"]["cumulative_used"]
    with pytest.raises(ValueError, match="OPERATION_NOT_AUTHORIZED"):
        send(s, v, "message", text="只有5天")
    v = send(s, v, "message", text="我家地址在合成路123号，为什么推荐这里？")
    _, container = s.plans.load(v["session_id"])
    data = model_context(container["planning"])
    assert "合成路123号" not in str(data)
    assert v["operation"]["cumulative_used"] == usage
    assert v["conversation"]["messages"][-1]["origin"] == "LOCAL_REFERENCE_EXPLANATION"


def test_excluded_combination_rejects_only_same_order_proposal(conversation):
    from travel_agent.planning.advisory import validate
    from test_advisory_guide import proposal

    s, v, _, _ = conversation
    _, container = s.plans.load(v["session_id"])
    data = payload_for(container["planning"], s.db, "owner", v["session_id"])
    good = proposal(data)["proposals"][0]
    excluded = deepcopy(good)
    data["conversation"]["excluded"] = [
        dict(order=[a["activity_id"] for a in excluded["activities"]])
    ]
    good["activities"] = list(reversed(good["activities"]))
    for a in good["activities"]:
        a["day"] = 1
    result = validate(dict(protocol_version=4, proposals=[excluded, good]), data)
    assert result["accepted_count"] == 1 and result["rejected_count"] == 1
    assert result["decisions"][0]["reason"] == "CONVERSATION_EXCLUDED_COMBINATION"


def test_actual_conversation_api_requires_origin_csrf_and_never_dispatches_question(
    conversation, monkeypatch
):
    from fastapi.testclient import TestClient
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    from travel_agent.settings import Settings

    s, v, _, _ = conversation
    launches = []
    monkeypatch.setattr(
        "travel_agent.planning.suggestions.launch", lambda *a, **kw: launches.append(kw)
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
        create_app(Settings.load(preferred_port=18775), preview=cfg),
        base_url="http://127.0.0.1:18775",
    ) as client:
        url = "/api/v1/preview/conversation/" + v["session_id"]
        body = dict(
            action="message",
            text="为什么推荐这些？",
            expected_revision=v["revision"],
            expected_conversation_version=v["conversation"]["version"],
        )
        assert client.post(url, json=body).status_code == 401
        client.get("/bootstrap?ticket=" + cfg.ticket)
        assert client.post(url, json=body).status_code == 403
        csrf = client.get("/api/v1/preview").json()["csrf_token"]
        headers = {
            "origin": "http://127.0.0.1:18775",
            "x-csrf-token": csrf,
            "idempotency-key": str(uuid4()),
        }
        result = client.post(url, json=body, headers=headers)
        assert result.status_code == 200, result.text
        assert (
            result.json()["conversation"]["messages"][-1]["origin"] == "LOCAL_REFERENCE_EXPLANATION"
        )
        again = client.post(url, json=body, headers=headers)
        assert again.json()["conversation"] == result.json()["conversation"]
        assert not launches


def test_plain_language_exclusion_uses_current_identity_and_can_revert(conversation):
    s, v, _, _ = conversation
    a = v["draft"]["activities"][0]
    usage = v["operation"]["cumulative_used"]
    v = send(s, v, "message", text="不想去" + a["name"])
    assert a["activity_id"] in v["conversation"]["excluded_activities"]
    v = send(s, v, "restore_activity", activity_id=a["activity_id"])
    assert not v["conversation"]["excluded_activities"]
    assert v["operation"]["cumulative_used"] == usage


def test_status_projection_cannot_mix_completed_task_and_old_conversation(
    conversation, monkeypatch
):
    """A writer completes between the first read and later task projection."""
    import json
    import threading
    from fastapi.testclient import TestClient
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    from travel_agent.settings import Settings
    from travel_agent.planning.flow import PlanningService

    s, v, _, _ = conversation
    trigger, committed = threading.Event(), threading.Event()
    previous_version = v["conversation"]["version"]
    original = PlanningService.load
    observed = []
    errors = []

    def complete():
        trigger.wait(3)
        try:
            with Database(s.db.path) as db, db.transaction():
                row, state = original(PlanningService(db, "owner"), v["session_id"])
                state["planning"]["conversation"]["version"] += 1
                db.connection.execute(
                    "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
                    (json.dumps(state), v["session_id"]),
                )
                db.connection.execute(
                    "UPDATE planning_tasks SET status='BLOCKED' WHERE task_id=?",
                    (v["automatic_task"]["task_id"],),
                )
            committed.set()
        except Exception as e:
            errors.append(type(e).__name__)

    def intervened(self, sid):
        result = original(self, sid)
        if not observed:
            observed.append(True)
            trigger.set()
            # Before the fix, the writer commits here and the rest of get()
            # observes its new task status with the previous conversation.
            committed.wait(0.15)
        return result

    cfg = PreviewConfig(
        s.db.path,
        "owner",
        "CACHED_PRIVATE_PREVIEW",
        b"fixture",
        product_flow=True,
        daily_workbench=True,
    )
    with TestClient(
        create_app(Settings.load(preferred_port=18775), preview=cfg),
        base_url="http://127.0.0.1:18775",
    ) as client:
        client.get("/bootstrap?ticket=" + cfg.ticket)
        thread = threading.Thread(target=complete)
        monkeypatch.setattr(PlanningService, "load", intervened)
        thread.start()
        data = client.get("/api/v1/preview/planning/" + v["session_id"]).json()
        thread.join(5)
        assert committed.is_set() and not errors
        assert data["conversation"]["version"] == previous_version
        assert data["automatic_task"]["status"] == v["automatic_task"]["status"]
        latest = client.get("/api/v1/preview/planning/" + v["session_id"]).json()
        assert latest["conversation"]["version"] == previous_version + 1
        assert latest["automatic_task"]["status"] == "BLOCKED"
