# ruff: noqa: F811
"""Synthetic intake failures through the production HTTP serializer and landing path."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import pytest
from jsonschema import Draft202012Validator

from travel_agent.planning.agent import run
from travel_agent.planning.agent_contract import CONSENT, Understanding, understanding
from travel_agent.planning.agent import apply_intake, intake_payload
from travel_agent.planning.flow_models import PlanDraft
from travel_agent.planning.automatic_models import AutomaticStart
from test_goal_agent import Wire, intake, choose, service  # noqa: F401
from automatic_fakes import Reader, config


def test_unique_verbatim_quote_repairs_only_offsets_with_audit():
    text = "改成五天，不自驾。"
    raw = intake(text, [("days", 5, "五天"), ("driving", "NO", "不自驾")])
    raw["updates"][0].update(start=0, end=2)
    result = understanding(raw, text)
    assert result.updates[0].start == text.index("五天")
    assert result._normalizations == [dict(field="days", rule="UNIQUE_VERBATIM_QUOTE_OFFSET_V1",
        received_start=0, received_end=2, start=2, end=4)]
    assert raw["updates"][0]["start"] == 0


@pytest.mark.parametrize("text,quote", [("五天改成六天", "七天"), ("五天还是五天", "五天")])
def test_offset_repair_rejects_missing_or_ambiguous_quote(text, quote):
    raw = intake("五天还是五天七天", [("days", 5, quote)])
    raw["updates"][0].update(start=1, end=2)
    with pytest.raises(ValueError, match="INTAKE_INVALID_EVIDENCE"):
        understanding(raw, text)


def test_quote_repair_does_not_apply_hypothetical():
    raw = intake("如果五天呢", [("days", 5, "五天")], "HYPOTHETICAL")
    raw["updates"][0].update(start=0, end=2)
    with pytest.raises(ValueError, match="INTAKE_NONASSERTED_UPDATE"):
        understanding(raw, "如果五天呢")


def test_evidenced_boolean_driving_lands_as_enum_without_new_research(service, monkeypatch):
    text = "合成松海七天，两个人，自驾"
    response = intake(text, [("destination", "合成松海", "合成松海"),
        ("days", 7, "七天"), ("people", 2, "两个人"), ("driving", True, "自驾")])
    wire = Wire(monkeypatch, lambda task, _: response if task == "travel_intake_v1"
                else choose("FINISH", stop="PARTIAL"))
    view = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    reader = Reader()
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(view["session_id"])
    assert final["automatic_task"]["understanding"]["status"] == "COMPLETED"
    assert final["draft"]["driving"] == "YES"
    assert final["draft"]["days"] == 7 and final["draft"]["trip_budget"]["people"] == 2
    assert reader.calls == [] and len(wire.sent) == 2
    audit = final["automatic_task"]["understanding"]["normalizations"]
    assert audit == [dict(field="driving", rule="EXPLICIT_DRIVING_BOOL_V1",
                          received_type="boolean", received_value=True, value="YES")]


def test_invalid_field_value_reports_stage_and_keeps_executed_model(service, monkeypatch):
    text = "合成松海，自驾"
    response = intake(text, [("destination", "合成松海", "合成松海"),
                            ("driving", "INVALID", "自驾")])
    wire = Wire(monkeypatch, lambda *_: response)
    view = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    before = deepcopy(view["draft"])
    reader = Reader()
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(view["session_id"])
    task = final["automatic_task"]
    assert task["understanding"]["model_executed"] is True
    assert task["reason"] == "INTAKE_INVALID_VALUE"
    assert task["understanding"]["failure"]["field"] == "driving"
    assert task["understanding"]["failure"]["phase"] == "INTAKE_SCHEMA"
    assert task["changes"] == []
    assert final["draft"] == before
    child = service.db.connection.execute("SELECT summary_json FROM preview_jobs WHERE job_id=?",
                                        (task["understanding"]["job_id"],)).fetchone()
    assert json.loads(child[0])["diagnostic"]["http_status"] == 200
    assert len(wire.sent) == 1 and reader.calls == []


VALID = [
    ("destination", "合成松海", "合成松海"), ("days", 7, "七天"),
    ("days", None, "天数未定"), ("people", 2, "两人"), ("people", None, "人数未定"),
    ("target_fen", 120000, "预算1200元"), ("target_fen", None, "预算未定"),
    ("arrival_transport", "AIR", "坐飞机"), ("arrival_transport", "RAIL", "坐高铁"),
    ("arrival_transport", "ROAD", "乘汽车"), ("arrival_transport", "UNKNOWN", "到达方式未定"),
    ("transport", "PUBLIC_TRANSIT", "公共交通"), ("transport", "WALKING", "步行"),
    ("transport", "LOCAL_SERVICE", "比较当地服务"), ("transport", "UNKNOWN", "当地交通未定"),
    ("driving", "YES", "自驾"), ("driving", "NO", "不自驾"), ("driving", "UNKNOWN", "驾驶未定"),
    ("driving", True, "租车自驾"), ("driving", False, "不愿意自己开车"),
    ("driving", True, "开车自驾去"), ("driving", False, "不想开车自驾去"),
    ("rental", "YES", "租车"), ("rental", "NO", "不租车"), ("rental", "UNKNOWN", "租车未定"),
    ("pace", "RELAXED", "轻松一些"), ("pace", "UNKNOWN", "节奏未定"),
    ("walking_allowed", True, "愿意步行"), ("walking_allowed", False, "不愿步行"),
    ("walking_allowed", None, "步行未定"),
    ("spatial", "CITY_CORE", "只在市区"), ("spatial", "CITY_AND_SURROUNDINGS", "城市及周边"),
    ("spatial", "REGIONAL", "区域旅行"), ("spatial", "UNDECIDED", "范围未定"),
    ("activity_start", "10:05", "10:05开始"), ("activity_start", None, "开始时间未定"),
    ("return_deadline", "22:15", "22:15前返回"), ("return_deadline", None, "返回时间未定"),
    ("depart_at", "2027-03-01T08:30", "2027-03-01T08:30出发"),
    ("return_by", "2027-03-05T22:15+08:00", "2027-03-05T22:15+08:00返回"),
    ("depart_at", None, "日期未定"), ("return_by", None, "返回日期未定"),
]


@pytest.mark.parametrize("field,value,quote", VALID)
def test_each_field_production_serialization_and_landing(service, monkeypatch, field, value, quote):
    text = "合成松海，" + quote
    updates = [(field, value, quote)]
    if field != "destination":
        updates.insert(0, ("destination", "合成松海", "合成松海"))
    raw = intake(text, updates)

    class SchemaWire(Wire):
        def _open(self, request, timeout):
            body = json.loads(request.data)
            assert body["response_format"]["type"] == "json_object"
            if not self.sent:
                prompt = body["messages"][0]["content"]
                schema = json.loads(prompt.split("Required JSON Schema: ")[1])
                assert schema == Understanding.model_json_schema()
                update_schema = schema["properties"]["updates"]["items"]
                assert update_schema["discriminator"]["propertyName"] == "field"
                assert len(update_schema["discriminator"]["mapping"]) == 15
                assert Draft202012Validator(schema).is_valid(raw)
                assert 'not booleans' in prompt and 'integer Chinese fen' in prompt
            return super()._open(request, timeout)

    wire = SchemaWire(monkeypatch, lambda task, _: raw if task == "travel_intake_v1"
                      else choose("FINISH", stop="PARTIAL"))
    view = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    reader = Reader()
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(view["session_id"])
    assert final["automatic_task"]["understanding"]["status"] == "COMPLETED", wire.errors
    d = final["draft"]
    received = (final["destination"] if field == "destination" else d["trip_budget"][field]
        if field in {"people", "target_fen"} else d["spatial"]["intent"] if field == "spatial"
        else d["inputs"][field] if field in {"activity_start", "depart_at", "return_by"} else d[field])
    expected = ("YES" if value else "NO") if field == "driving" and type(value) is bool else value
    if field in {"depart_at", "return_by"}:
        from travel_agent.planning.models import TripInputs
        expected = TripInputs.date(value)
    assert received == expected
    if field != "people":
        assert d["trip_budget"]["people"] is None
    if field != "target_fen":
        assert d["trip_budget"]["target_fen"] is None
    if field != "arrival_transport":
        assert d["arrival_transport"] == "UNKNOWN"
    assert len(wire.sent) == 2 and reader.calls == []


INVALID = [
    ("days", True), ("days", "7"), ("days", 0), ("days", 91),
    ("people", 2.5), ("people", False), ("people", "两人"), ("people", 101),
    ("target_fen", "120000"), ("target_fen", -1), ("target_fen", 100_000_001),
    ("arrival_transport", True), ("arrival_transport", "FLIGHT"),
    ("transport", True), ("transport", "CAR"), ("transport", None),
    ("driving", 1), ("driving", 0), ("driving", "true"), ("driving", "false"),
    ("driving", None), ("rental", True), ("pace", False), ("pace", "NORMAL"),
    ("walking_allowed", "false"), ("walking_allowed", 0),
    ("spatial", "REGION"), ("spatial", True),
    ("activity_start", "25:30"), ("return_deadline", "10点"),
    ("depart_at", "这周"), ("depart_at", "2027-02-30T10:00"),
    ("return_by", "2027-03-01"), ("destination", None), ("destination", True),
]


@pytest.mark.parametrize("field,value", INVALID)
def test_bad_types_enums_and_ranges_stop_atomically_without_io(service, monkeypatch, field, value):
    text = "合成松海，七天，自编条件"
    raw = intake(text, [("days", 7, "七天")]) if field != "days" else intake(text, [])
    raw["updates"].extend(intake(text, [(field, value, "自编条件")])["updates"])
    wire = Wire(monkeypatch, lambda *_: raw)
    view = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    before = deepcopy(view["draft"])
    reader = Reader()
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(view["session_id"])
    task = final["automatic_task"]
    assert task["status"] == "BLOCKED" and task["reason"] == "INTAKE_INVALID_VALUE", (task, wire.errors)
    assert task["understanding"]["failure"]["field"] == field
    assert task["understanding"]["model_executed"] is True
    assert final["draft"] == before  # Even the valid sibling days update is not partially committed.
    assert task["budget"]["used"]["model"] == 1 and task["search_count"] == 0
    assert len(wire.sent) == 1 and reader.calls == []


@pytest.mark.parametrize("value,quote,intent", [(True,"不自驾","UPDATE"), (False,"自驾","UPDATE"),
    (True,"如果自驾","UPDATE"), (True,"交通未定","UPDATE"), (True,"自驾","HYPOTHETICAL"),
    (False,"不自驾","QUESTION")])
def test_boolean_compatibility_requires_matching_asserted_evidence(value, quote, intent):
    with pytest.raises(ValueError, match="INTAKE_(BOOLEAN_EVIDENCE_REQUIRED|NONASSERTED_UPDATE)"):
        understanding(intake(quote, [("driving", value, quote)], intent), quote)


def test_lock_conflict_retains_model_execution_and_never_commits_sibling_update(service, monkeypatch):
    from travel_agent.planning.automatic import save
    from travel_agent.planning.conversation import action, ConversationAction
    first = service.start(AutomaticStart(request="合成松海七天", consent=CONSENT), str(uuid4()))
    wire = Wire(monkeypatch, lambda task, data: intake(data["user_text"], []) if task == "travel_intake_v1"
                else choose("FINISH", stop="PARTIAL"))
    run(service.db.path, first["automatic_task"]["task_id"], provider=config(), reader=Reader())
    _, state = service.plans.load(first["session_id"])
    state["planning"]["draft"]["trip_budget"].update(target_fen=100000, target_locked=True)
    save(service.db, first["session_id"], state)
    first = service.plans.get(first["session_id"])
    text = "改为三天，预算两千元"
    wire.respond = lambda *_: intake(text, [("days", 3, "三天"), ("target_fen", 200000, "两千元")])
    view = action(service.db, "owner", first["session_id"], ConversationAction(action="submit", text=text,
        consent=CONSENT, expected_revision=first["revision"],
        expected_conversation_version=first["conversation"]["version"]), str(uuid4()))
    before = deepcopy(view["draft"])
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=Reader())
    final = service.plans.get(view["session_id"])
    assert final["draft"] == before
    assert final["automatic_task"]["reason"] == "BUDGET_LOCKED_LINE"
    assert final["automatic_task"]["understanding"]["model_executed"] is True


def test_legacy_failure_is_diagnosed_read_only_and_restored_without_replay(service):
    from travel_agent.planning.agent_model import create
    from travel_agent.planning.automatic import save
    view = service.start(AutomaticStart(request="合成松海，自驾", consent=CONSENT), str(uuid4()))
    _, state = service.plans.load(view["session_id"])
    p = state["planning"]
    service.db.connection.execute("UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?",
                                  (view["automatic_task"]["task_id"],))
    jid = create(service.db, "owner", view["session_id"], view["revision"], p, "travel_intake_v1",
                 intake_payload(p), "authored-original-failure")
    p["agent_understanding"].update(status="FAILED", reason="AGENT_STOPPED", model_executed=False)
    save(service.db, view["session_id"], state, bump=False)
    service.db.connection.execute("UPDATE preview_jobs SET status='COMPLETED',summary_json=? WHERE job_id=?",
        (json.dumps(dict(result=intake("合成松海，自驾", [("driving",True,"自驾")]),
            purpose="travel_intake_v1", model_executed=True, diagnostic=dict(http_status=200,http_attempts=1))),jid))
    service.db.connection.execute("UPDATE planning_tasks SET status='BLOCKED',summary_json=? WHERE task_id=?",
        (json.dumps(dict(reason="AGENT_STOPPED")),view["automatic_task"]["task_id"]))
    before = list(service.db.connection.iterdump())
    final = service.plans.get(view["session_id"])
    u = final["automatic_task"]["understanding"]
    assert u["reason"] == "INTAKE_LEGACY_VALUE_TYPE" and u["failure"]["historical"]
    assert u["failure"]["field"] == "driving" and u["model_executed"] and u["job_id"] == jid
    assert final["automatic_task"]["reason"] == "AGENT_STOPPED"
    assert before == list(service.db.connection.iterdump())
    restored = subprocess.run([sys.executable, str(Path(__file__).parents[1]/"helpers/intake_restore.py"),
        str(service.db.path), view["session_id"]], capture_output=True, text=True, encoding="utf8", timeout=30)
    assert restored.returncode == 0, restored.stderr
    result = json.loads(restored.stdout)
    assert result["model_executed"] and result["failure"]["historical"] and result["attempts"] == 0
    assert result["used_model"] == 1
    assert before == list(service.db.connection.iterdump())


def test_strict_fields_cannot_guess_relative_date_or_infer_omitted_transport():
    text = "合成松海，自驾，这周"
    p = dict(draft=PlanDraft(planning_mode="ADVISORY").model_dump(), destination="合成区域",
             agent_followup=False, agent_input=text, request=text)
    apply_intake(p, understanding(intake(text, [("destination","合成松海","合成松海"),
        ("driving",True,"自驾")]),text))
    assert p["draft"]["driving"] == "YES" and p["draft"]["transport"] == "UNKNOWN"
    assert p["draft"]["rental"] == "UNKNOWN" and p["draft"]["inputs"]["depart_at"] is None


def test_json_schema_transport_sends_same_discriminated_contract(service, monkeypatch):
    from dataclasses import replace
    provider = replace(config(), response_format="json_schema")
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", lambda: provider)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", lambda: provider)
    text = "合成松海，自驾"
    seen = []

    class SchemaWire(Wire):
        def _open(self, request, timeout):
            body = json.loads(request.data)
            output = body["response_format"]
            assert output["type"] == "json_schema" and output["json_schema"]["strict"]
            if not seen:
                assert output["json_schema"]["schema"] == Understanding.model_json_schema()
            seen.append(output["json_schema"]["name"])
            return super()._open(request, timeout)

    wire = SchemaWire(monkeypatch, lambda task, _: intake(text, [("destination","合成松海","合成松海"),
        ("driving",True,"自驾")]) if task == "travel_intake_v1" else choose("FINISH",stop="PARTIAL"))
    view = service.start(AutomaticStart(request=text,consent=CONSENT),str(uuid4()))
    run(service.db.path, view["automatic_task"]["task_id"], provider=provider, reader=Reader())
    final = service.plans.get(view["session_id"])
    assert final["draft"]["driving"] == "YES" and len(wire.sent) == 2
