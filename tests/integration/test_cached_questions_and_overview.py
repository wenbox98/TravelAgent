# ruff: noqa: F811
"""Synthetic production-path regressions; every external transport is denied."""

from copy import deepcopy
from uuid import uuid4
import pytest
from travel_agent.persistence.database import Database
from travel_agent.planning import questions, reference_overview
from travel_agent.planning.flow_models import PlanAction, PlanDraft
from test_planning_conversation import conversation, send  # noqa: F401


class AnswerModel:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def structured(self, task, data, schema):
        self.calls.append((task, deepcopy(data)))
        if self.callback:
            self.callback()
        return dict(
            advice="可以先比较来源中的安排；交通仍需核实。",
            citation_ids=[r["citation_id"] for r in data["references"][:1]],
            gaps=["公共交通衔接未知"],
            intent="MIXED",
            proposed_conditions=dict(days=5, driving="NO", pace="RELAXED"),
        )


def test_zero_activities_keeps_citable_routes_as_explicit_local_version(conversation):
    s, v, model, reader = conversation
    old = deepcopy(v["automatic_task"])
    before = s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    draft = PlanDraft.model_validate(v["draft"])
    draft.activities = []
    v = s.plans.mutate(
        v["session_id"],
        PlanAction(action="save", expected_revision=v["revision"], draft=draft),
        str(uuid4()),
    )
    assert not v["activity_candidates"] or v["draft"]["activities"] == []
    assert v["reference_overview"]["available"] and not v["reference_overview"]["current"]
    v = send(s, v, "derive_overview")
    saved = v["reference_overview"]
    assert saved["valid"] and saved["current"]["cards"]
    assert all(c["source_count"] == 1 for c in saved["current"]["cards"])
    assert saved["current"]["kind"] == "LOCAL_REFERENCE_OVERVIEW"
    assert not v["draft"]["activities"] and v["adopted"] is None
    assert v["automatic_task"] == old
    exported = reference_overview.export(s.db, "owner", v["session_id"])
    assert "不是已采用攻略" in exported["markdown"] and "角色" in exported["markdown"]
    assert s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == before
    v = send(s, v, "select_reference", option_id=saved["current"]["cards"][0]["option_id"])
    with Database(s.db.path) as db:
        from travel_agent.planning.flow import PlanningService

        restored = PlanningService(db, "owner").get(v["session_id"])
        assert restored["reference_overview"] == v["reference_overview"]
    assert len(model.calls) == 5 and reader.calls.count("CONNECT") == 1


def test_punctuation_does_not_swallow_asserted_constraint_change(conversation):
    s, v, _, _ = conversation
    from travel_agent.planning.automatic_models import CONSENT

    v = send(s, v, "message", text="只有5天，不想自驾，轻松一点吗？", consent=CONSENT)
    assert v["draft"]["days"] == 5 and v["draft"]["driving"] == "NO"
    assert v["draft"]["pace"] == "RELAXED" and v["automatic_task"]["status"] == "QUEUED"


def test_hypothetical_question_does_not_change_conditions_or_call_model(conversation):
    s, v, _, _ = conversation
    before = deepcopy(v["draft"])
    v = send(s, v, "message", text="如果只有5天，不自驾会不会太赶？")
    assert v["draft"] == before and not v["answer_job"]
    assert v["conversation"]["pending_ai_question"]


def test_explicit_single_question_uses_current_choices_and_minimal_refs(conversation):
    s, v, _, _ = conversation
    v = send(s, v, "derive_overview")
    option = v["reference_overview"]["current"]["cards"][0]["option_id"]
    v = send(s, v, "select_reference", option_id=option)
    v = send(s, v, "exclude_activity", activity_id=v["draft"]["activities"][-1]["activity_id"])
    v = send(s, v, "message", text="这两种玩法的取舍是什么？")
    used = v["operation"]["cumulative_used"]["model"]
    with pytest.raises(ValueError, match="OPERATION_NOT_AUTHORIZED"):
        send(s, v, "ask")
    key = str(uuid4())
    before = deepcopy(v)
    v = send(s, v, "ask", consent=questions.CONSENT, key=key)
    again = send(s, before, "ask", consent=questions.CONSENT, key=key)
    assert again["answer_job"] == v["answer_job"]
    assert v["operation"]["cumulative_used"]["model"] == used + 1
    model = AnswerModel()
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    v = s.plans.get(v["session_id"])
    assert len(model.calls) == 1 and v["answer_job"]["status"] == "COMPLETED"
    data = model.calls[0][1]
    assert data["conversation"]["selected_reference"]["option_id"] == option
    assert data["conversation"]["excluded_activity_ids"]
    assert data["conditions"]["days"] == 7 and data["references"]
    assert all("duration_scope" in r and "route_association" in r for r in data["references"])
    assert "BodyBlock" not in str(data) and "location" not in str(data)
    assert v["conversation"]["messages"][-1]["origin"] == "AI_CACHED_ADVICE"
    assert v["draft"]["days"] == 7 and v["operation"]["current"]["closed"]
    v = send(s, v, "confirm_intent")
    assert v["draft"]["days"] == 5 and v["draft"]["driving"] == "NO"
    with Database(s.db.path) as db:
        from travel_agent.planning.flow import PlanningService

        assert (
            PlanningService(db, "owner").get(v["session_id"])["conversation"] == v["conversation"]
        )


def test_late_question_after_selection_change_cannot_commit(conversation):
    s, v, _, _ = conversation
    v = send(s, v, "ask", text="这次如何取舍？", consent=questions.CONSENT)
    jid = v["answer_job"]["job_id"]
    model = AnswerModel(
        lambda: send(
            s,
            s.plans.get(v["session_id"]),
            "exclude_activity",
            activity_id=v["draft"]["activities"][0]["activity_id"],
        )
    )
    questions.run(s.db.path, jid, model)
    v = s.plans.get(v["session_id"])
    assert len(model.calls) == 1 and v["answer_job"]["status"] == "CANCELED"
    assert not any(m.get("origin") == "AI_CACHED_ADVICE" for m in v["conversation"]["messages"])


def test_question_unknown_citation_failure_is_counted_and_not_retried(conversation):
    s, v, _, _ = conversation
    v = send(s, v, "ask", text="如何取舍？", consent=questions.CONSENT)

    class Bad(AnswerModel):
        def structured(self, *args):
            result = super().structured(*args)
            result["citation_ids"] = ["invented"]
            return result

    model = Bad()
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    v = s.plans.get(v["session_id"])
    assert len(model.calls) == 1 and v["answer_job"]["reason"] == "QUESTION_UNKNOWN_REFERENCE"
    assert v["operation"]["current"]["closed"] and not v["adopted"]


def test_restart_never_replays_queued_question_or_recovers_its_quota(conversation):
    from travel_agent.planning.automatic import recover

    s, v, _, _ = conversation
    v = send(s, v, "ask", text="如何比较现有资料？", consent=questions.CONSENT)
    used = v["operation"]["cumulative_used"]
    recover(s.db)
    v = s.plans.get(v["session_id"])
    assert v["answer_job"]["status"] == "CANCELED"
    assert v["operation"]["current"]["closed"] and v["operation"]["cumulative_used"] == used
    model = AnswerModel()
    questions.run(s.db.path, v["answer_job"]["job_id"], model)
    assert not model.calls


def test_private_address_is_omitted_from_question_and_known_budget_is_kept(conversation):
    s, v, _, _ = conversation
    _, state = s.plans.load(v["session_id"])
    p = state["planning"]
    p["draft"]["trip_budget"]["people"] = 2
    p["draft"]["trip_budget"]["target_fen"] = 100000
    data = questions.payload(s.db, "owner", v["session_id"], p, "我家在虚构路123号，想比较交通？")
    assert "虚构路123号" not in str(data)
    assert (
        data["budget_conditions"]["people"] == 2
        and data["budget_conditions"]["target_fen"] == 100000
    )
    assert data["walking_conditions"]["walking_origin"] == p["draft"]["walking_origin"]
