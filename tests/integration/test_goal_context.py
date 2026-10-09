# ruff: noqa: F811
"""Current choices and cited answers cross the actual model serialization boundary."""

from copy import deepcopy
from uuid import uuid4
from test_planning_conversation import conversation, send  # noqa: F401
from test_goal_agent import Wire, intake, choose
from automatic_fakes import Model, Reader, config
from travel_agent.planning.conversation import action, ConversationAction
from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CONSENT


def test_current_selected_and_excluded_state_enters_supervisor_and_answer(
    conversation, monkeypatch
):
    s, v, _, _ = conversation
    selected = v["conversation"]["options"][0]["option_id"]
    v = send(s, v, "select", option_id=selected)
    excluded = v["draft"]["activities"][-1]["activity_id"]
    v = send(s, v, "exclude_activity", activity_id=excluded)
    before = deepcopy(v["draft"])
    usage = v["operation"]["cumulative_used"]["model"]
    text = "如果少一天会怎样？"
    oracle = Model()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(text, [], "HYPOTHETICAL")
        assert data["conversation"]["selected"]["option_id"] == selected
        assert excluded in data["conversation"]["excluded_activity_ids"]
        assert data["references"]
        if task == "travel_supervisor_v1":
            return choose("ANSWER")
        return oracle.structured(task, data, {})

    wire = Wire(monkeypatch, respond)
    key = str(uuid4())
    request = ConversationAction(
        action="submit",
        text=text,
        consent=CONSENT,
        expected_revision=v["revision"],
        expected_conversation_version=v["conversation"]["version"],
    )
    v = action(s.db, "owner", v["session_id"], request, key)
    assert v["conversation"]["intent_key"] == key
    again = action(s.db, "owner", v["session_id"], request, key)
    assert again["automatic_task"]["task_id"] == v["automatic_task"]["task_id"]
    reader = Reader()
    run(s.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = s.plans.get(v["session_id"])
    assert final["draft"] == before and reader.calls == []
    assert final["conversation"]["messages"][-2]["origin"] == "AI_CACHED_ADVICE"
    assert final["conversation"]["messages"][-2]["citations"]
    assert final["operation"]["cumulative_used"]["model"] == usage + 3
    assert [r["task"] for r in wire.sent] == [
        "travel_intake_v1",
        "travel_supervisor_v1",
        "cached_travel_question_v1",
    ]
