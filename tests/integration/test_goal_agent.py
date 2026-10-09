"""Authored synthetic responses through production workers AND Provider serialization; no network."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from uuid import uuid4
import pytest
from travel_agent.persistence.database import Database
from travel_agent.planning.automatic import AutomaticService, recover
from travel_agent.planning.automatic_models import AutomaticStart
from travel_agent.planning.agent_contract import CONSENT, understanding
from travel_agent.planning.agent import run, apply_intake
from travel_agent.planning.flow_models import PlanDraft
from travel_agent.planning.conversation import action as converse, ConversationAction

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "helpers"))
from automatic_fakes import Model, Reader, config  # noqa: E402
from test_workbench_pipeline import dispatches  # noqa: E402


def intake(text, updates, intent="UPDATE"):
    items = []
    for field, value, quote in updates:
        start = text.index(quote)
        items.append(
            dict(field=field, value=value, quote=quote, start=start, end=start + len(quote))
        )
    return dict(
        protocol="TRAVEL_INTAKE_V1",
        intent=intent,
        updates=items,
        summary="已理解明确陈述，未提供条件保留未知。",
        user_needs=[],
    )


def choose(tool, **fields):
    return dict(
        protocol="TRAVEL_SUPERVISOR_V1",
        tool=tool,
        reason="根据当前工具结果与剩余许可选择。",
        **fields,
    )


class Wire:
    def __init__(self, monkeypatch, respond):
        self.sent = []
        self.errors = []
        self.requests = []
        self.respond = respond
        monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *_: self)

    def open(self, request, timeout):
        try:
            return self._open(request, timeout)
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

    def _open(self, request, timeout):
        self.requests.append((request.full_url, timeout))
        assert timeout == 120 and request.full_url == "https://api.deepseek.com/chat/completions"
        body = json.loads(request.data)
        envelope = json.loads(body["messages"][1]["content"])
        self.sent.append(deepcopy(envelope))
        try:
            result = self.respond(envelope["task"], envelope["input"])
        except Exception as exc:
            self.errors.append(repr(exc))
            raise

        class Response:
            status = 200
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def read(self, limit):
                return json.dumps(
                    dict(
                        model="authored",
                        choices=[
                            dict(
                                finish_reason="stop",
                                message=dict(content=json.dumps(result, ensure_ascii=False)),
                            )
                        ],
                    ),
                    ensure_ascii=False,
                ).encode()[:limit]

        return Response()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    with Database(tmp_path / "agent.sqlite3") as db:
        yield AutomaticService(db, "owner")


def test_normal_submit_intake_tool_feedback_generation_stop_and_no_replay(service, monkeypatch):
    text = "我想去合成青谷玩七天，坐飞机然后租车自驾"
    first = intake(
        text,
        [
            ("destination", "合成青谷", "合成青谷"),
            ("days", 7, "七天"),
            ("arrival_transport", "AIR", "坐飞机"),
            ("transport", "SELF_DRIVE", "租车自驾"),
            ("driving", "YES", "租车自驾"),
            ("rental", "YES", "租车自驾"),
        ],
    )
    oracle = Model()

    def respond(task, data):
        if task == "travel_intake_v1":
            return first
        if task == "travel_supervisor_v1":
            assert data["journey"]["arrival_transport"] == "AIR"
            assert data["journey"]["local_transport"] == "SELF_DRIVE"
            if data["proposed"]:
                return choose("FINISH", stop="PARTIAL")
            if not data["previous_results"]:
                return choose("RESEARCH_GAP", query="合成青谷 七天 玩法 体验", gap_key="PLAY")
            assert data["previous_results"][-1]["result"]["accepted"] > 0
            assert data["references"]
            return choose("GENERATE")
        return oracle.structured(task, data, {})

    wire = Wire(monkeypatch, respond)
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    assert wire.sent == [] and v["automatic_task"]["stage"] == "INTAKE"
    provider = config()
    extract, review = dispatches(provider)
    class SingleReader(Reader):
        def search(self, query):
            return super().search(query)[:1]

    reader = SingleReader()
    run(
        service.db.path,
        v["automatic_task"]["task_id"],
        provider=provider,
        reader=reader,
        extract_dispatch=extract,
        review_dispatch=review,
    )
    final = service.plans.get(v["session_id"])
    assert final["automatic_task"]["status"] == "PARTIAL", (
        final["automatic_task"]["reason"],
        wire.errors,
        wire.requests,
        [r["task"] for r in wire.sent],
    )
    assert final["draft"]["arrival_transport"] == "AIR"
    assert final["draft"]["driving"] == "YES" and final["draft"]["rental"] == "YES"
    assert final["draft"]["trip_budget"]["people"] is None
    assert final["draft"]["inputs"]["depart_at"] is None
    assert final["job"]["proposals"] and final["job"]["can_preview"], final["job"]
    assert [r["tool"] for r in final["automatic_task"]["agent_rounds"]] == [
        "RESEARCH_GAP",
        "GENERATE",
    ]
    assert [r["task"] for r in wire.sent] == [
        "travel_intake_v1",
        "travel_supervisor_v1",
        "select_evidence_references_v1",
        "review_evidence_context_v2",
        "travel_supervisor_v1",
        "planning_advisory_v4",
    ]
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL"]
    count = len(wire.sent)
    with Database(service.db.path) as db:
        recover(db)
    run(service.db.path, v["automatic_task"]["task_id"], provider=provider, reader=reader)
    assert len(wire.sent) == count
    assert service.plans.get(v["session_id"])["job"]["proposals"] == final["job"]["proposals"]
    import subprocess

    restored = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "helpers/agent_restore.py"),
            str(service.db.path),
            v["session_id"],
        ],
        capture_output=True,
        text=True,
        encoding="utf8",
        timeout=30,
    )
    assert restored.returncode == 0, restored.stderr
    result = json.loads(restored.stdout)
    assert result["external_attempts"] == 0 and result["proposals"] == len(
        final["job"]["proposals"]
    )
    assert result["transport"] == "SELF_DRIVE" and result["days"] == 7


@pytest.mark.parametrize(
    "text,updates,intent,expected",
    [
        (
            "去合成海城待三天，飞过去，落地自己开租来的车",
            [
                ("days", 3, "三天"),
                ("arrival_transport", "AIR", "飞过去"),
                ("transport", "SELF_DRIVE", "自己开租来的车"),
                ("driving", "YES", "自己开租来的车"),
                ("rental", "YES", "租来的车"),
            ],
            "UPDATE",
            ("AIR", "SELF_DRIVE", "YES", "YES"),
        ),
        (
            "不租车自驾，改坐公共交通",
            [
                ("rental", "NO", "不租车自驾"),
                ("driving", "NO", "不租车自驾"),
                ("transport", "PUBLIC_TRANSIT", "改坐公共交通"),
            ],
            "UPDATE",
            ("UNKNOWN", "PUBLIC_TRANSIT", "NO", "NO"),
        ),
        (
            "我说错了，坐高铁到，再步行逛",
            [("arrival_transport", "RAIL", "坐高铁到"), ("transport", "WALKING", "步行逛")],
            "UPDATE",
            ("RAIL", "WALKING", "UNKNOWN", "UNKNOWN"),
        ),
        (
            "如果落地后租车自己开呢？",
            [],
            "HYPOTHETICAL",
            ("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN"),
        ),
        ("飞机会不会比高铁好？", [], "QUESTION", ("UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN")),
    ],
)
def test_semantics_are_evidenced_and_not_a_keyword_patch(text, updates, intent, expected):
    value = understanding(intake(text, updates, intent), text)
    p = dict(
        draft=PlanDraft(planning_mode="ADVISORY").model_dump(),
        destination="合成区域",
        request="旧输入",
        agent_followup=True,
        agent_input=text,
    )
    apply_intake(p, value)
    assert (
        tuple(p["draft"][k] for k in ("arrival_transport", "transport", "driving", "rental"))
        == expected
    )


def test_false_quote_and_hypothetical_update_rejected():
    text = "如果自驾呢？"
    raw = intake(text, [("driving", "YES", "自驾")], "HYPOTHETICAL")
    with pytest.raises(ValueError, match="NONASSERTED"):
        understanding(raw, text)
    raw["intent"] = "UPDATE"
    raw["updates"][0]["quote"] = "想自驾"
    with pytest.raises(ValueError, match="EVIDENCE"):
        understanding(raw, text)


def test_followup_assertion_question_correction_use_model_before_any_dispatch(service, monkeypatch):
    text = "去合成青谷7天"
    wire = Wire(
        monkeypatch,
        lambda task, data: (
            intake(text, [("destination", "合成青谷", "合成青谷"), ("days", 7, "7天")])
            if task == "travel_intake_v1"
            else choose("FINISH", stop="PARTIAL")
        ),
    )
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=Reader())
    for text, updates, intent in [
        (
            "落地后租车自己开",
            [
                ("transport", "SELF_DRIVE", "租车自己开"),
                ("driving", "YES", "自己开"),
                ("rental", "YES", "租车"),
            ],
            "UPDATE",
        ),
        ("如果改坐高铁呢？", [], "HYPOTHETICAL"),
        (
            "更正，不自己开，坐公共交通",
            [
                ("driving", "NO", "不自己开"),
                ("rental", "NO", "不自己开"),
                ("transport", "PUBLIC_TRANSIT", "坐公共交通"),
            ],
            "UPDATE",
        ),
    ]:
        v = service.plans.get(v["session_id"])
        before = deepcopy(v["draft"])
        wire.respond = lambda task, data, lit=text, values=updates, kind=intent: (
            intake(lit, values, kind)
            if task == "travel_intake_v1"
            else choose("FINISH", stop="PARTIAL")
        )
        v = converse(
            service.db,
            "owner",
            v["session_id"],
            ConversationAction(
                action="submit",
                text=text,
                consent=CONSENT,
                expected_revision=v["revision"],
                expected_conversation_version=v["conversation"]["version"],
            ),
            str(uuid4()),
        )
        assert v["draft"] == before and v["automatic_task"]["stage"] == "INTAKE"
        run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=Reader())
        after = service.plans.get(v["session_id"])
        assert after["automatic_task"]["understanding"]["status"] == "COMPLETED"
        if intent == "HYPOTHETICAL":
            assert after["draft"] == before
    assert after["draft"]["days"] == 7
    assert after["draft"]["transport"] == "PUBLIC_TRANSIT" and after["draft"]["driving"] == "NO"
    assert all(v["task"] in {"travel_intake_v1", "travel_supervisor_v1"} for v in wire.sent)
    assert after["operation"]["cumulative_used"]["model"] == 8


def test_auth_failure_stops_without_retry_and_retains_intake(service, monkeypatch):
    from travel_agent.research.models import ResearchStopped

    text = "去合成青谷7天"

    class LockedReader(Reader):
        def connect(self):
            self.calls.append("CONNECT")
            raise ResearchStopped("VERIFICATION_REQUIRED")

    reader = LockedReader()
    wire = Wire(
        monkeypatch,
        lambda task, data: (
            intake(text, [("destination", "合成青谷", "合成青谷"), ("days", 7, "7天")])
            if task == "travel_intake_v1"
            else choose("RESEARCH_GAP", query="合成青谷 玩法", gap_key="PLAY")
        ),
    )
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(v["session_id"])
    assert reader.calls == ["CONNECT"] and len(wire.sent) == 2
    assert final["automatic_task"]["status"] == "BLOCKED"
    assert final["automatic_task"]["reason"] == "RESEARCH_VERIFICATION_REQUIRED"
    assert final["automatic_task"]["understanding"]["status"] == "COMPLETED"
    assert final["automatic_task"]["budget"]["used"]["connect"] == 1


def test_budget_gate_denies_tools_without_reset_and_stop_is_not_success(service, monkeypatch):
    text = "去合成青谷7天"
    wire = Wire(
        monkeypatch,
        lambda task, data: (
            intake(text, [("destination", "合成青谷", "合成青谷"), ("days", 7, "7天")])
            if task == "travel_intake_v1"
            else choose("KEY_LEG", leg_id="a--b")
        ),
    )
    reader = Reader()
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    original = v["automatic_task"]["limits"]
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(v["session_id"])
    assert reader.calls == [] and len(wire.sent) == 2
    assert final["automatic_task"]["limits"] == original
    assert final["automatic_task"]["budget"]["used"]["model"] == 2
    assert final["automatic_task"]["status"] == "BLOCKED"
    assert final["automatic_task"]["agent_rounds"][0]["result"]["executed"] is False


def test_late_model_result_cannot_apply_after_cancel(service, monkeypatch):
    from travel_agent.planning.automatic import invalidate

    text = "去合成青谷7天，飞过去"

    def respond(task, data):
        with service.db.transaction():
            invalidate(service.db, v["session_id"], "USER_CANCELED")
        return intake(text, [("arrival_transport", "AIR", "飞过去")])

    wire = Wire(monkeypatch, respond)
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=Reader())
    after = service.plans.get(v["session_id"])
    assert after["automatic_task"]["status"] == "CANCELED" and len(wire.sent) == 1
    assert after["draft"]["arrival_transport"] == "UNKNOWN"


def test_second_gap_uses_same_reader_and_failure_keeps_first_qualified_material(
    service, monkeypatch
):
    from travel_agent.research.models import ResearchStopped

    text = "去合成青谷7天"
    oracle = Model()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(text, [("destination", "合成青谷", "合成青谷"), ("days", 7, "7天")])
        if task == "travel_supervisor_v1":
            n = len(data["previous_results"])
            if n:
                assert data["previous_results"][-1]["result"]["accepted"] > 0
                assert data["references"]
            return choose(
                "RESEARCH_GAP",
                query="合成青谷 玩法 " + str(n),
                gap_key=data["research_gaps"][0]["key"],
            )
        return oracle.structured(task, data, {})

    wire = Wire(monkeypatch, respond)

    class SecondFails(Reader):
        def search(self, query):
            candidates = super().search(query)
            return candidates[:1] if self.calls.count("SEARCH") == 1 else candidates[1:]

        def detail(self, candidate, number):
            if number == 2:
                self.calls.append("DETAIL")
                raise ResearchStopped("VERIFICATION_REQUIRED")
            return super().detail(candidate, number)

    reader = SecondFails()
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    run(
        service.db.path,
        v["automatic_task"]["task_id"],
        provider=config(),
        reader=reader,
        extract_dispatch=extract,
        review_dispatch=review,
    )
    final = service.plans.get(v["session_id"])
    assert reader.calls == ["CONNECT", "SEARCH", "DETAIL", "SEARCH", "DETAIL"]
    assert len([x for x in wire.sent if x["task"] == "travel_supervisor_v1"]) == 2
    assert final["references"] and final["draft"]["activities"]
    assert final["automatic_task"]["search_count"] == 2
    assert final["automatic_task"]["new_body_count"] == 1
    assert final["automatic_task"]["reason"] == "RESEARCH_VERIFICATION_REQUIRED"
    assert final["automatic_task"]["budget"]["used"]["connect"] == 1


def test_explicit_destination_field_is_retained_without_fabricated_quote(service, monkeypatch):
    text = "玩两天，飞机到达"
    wire = Wire(
        monkeypatch,
        lambda task, data: (
            intake(text, [("days", 2, "两天"), ("arrival_transport", "AIR", "飞机到达")])
            if task == "travel_intake_v1"
            else choose("FINISH", stop="PARTIAL")
        ),
    )
    v = service.start(
        AutomaticStart(request=text, destination="合成海城", consent=CONSENT), str(uuid4())
    )
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=Reader())
    final = service.plans.get(v["session_id"])
    assert final["destination"] == "合成海城" and final["draft"]["days"] == 2
    assert wire.sent[0]["input"]["explicit_destination"] == "合成海城"
    assert final["automatic_task"]["understanding"]["destination_field"] == "合成海城"
    assert all(
        e["field"] != "destination"
        for e in final["automatic_task"]["understanding"]["input_evidence"]
    )


def test_duplicate_local_action_stops_and_does_not_reset_budget(service, monkeypatch):
    text = "去合成青谷7天"
    Wire(
        monkeypatch,
        lambda task, data: (
            intake(text, [("destination", "合成青谷", "合成青谷")])
            if task == "travel_intake_v1"
            else choose("CACHE")
        ),
    )
    v = service.start(AutomaticStart(request=text, consent=CONSENT), str(uuid4()))
    reader = Reader()
    run(service.db.path, v["automatic_task"]["task_id"], provider=config(), reader=reader)
    final = service.plans.get(v["session_id"])
    assert final["automatic_task"]["reason"] == "NO_PROGRESS" and reader.calls == []
    assert final["automatic_task"]["budget"]["used"]["model"] == 3


def test_migration_18_preserves_legacy_rows_and_limits_one_active_agent_child(
    tmp_path, monkeypatch
):
    from travel_agent.planning.agent_model import create
    from travel_agent.planning.agent import intake_payload
    import sqlite3

    path = tmp_path / "upgrade.sqlite3"
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", config)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", config)
    with Database(path, target_version=17) as old:
        svc = AutomaticService(old, "owner")
        v = svc.start(AutomaticStart(request="去合成青谷7天", consent=CONSENT), str(uuid4()))
        protected = {
            name: [tuple(r) for r in old.connection.execute("SELECT * FROM " + name)]
            for name in (
                "preview_sessions",
                "planning_tasks",
                "research_continuations",
                "continuation_operations",
            )
        }
    with Database(path) as db:
        assert db.version == 18
        for name, rows in protected.items():
            assert [tuple(r) for r in db.connection.execute("SELECT * FROM " + name)] == rows
        db.connection.execute(
            "UPDATE planning_tasks SET status='RUNNING' WHERE task_id=?",
            (v["automatic_task"]["task_id"],),
        )
        _, state = AutomaticService(db, "owner").plans.load(v["session_id"])
        p = state["planning"]
        with db.transaction():
            create(
                db,
                "owner",
                v["session_id"],
                v["revision"],
                p,
                "travel_intake_v1",
                intake_payload(p),
                "first-model",
            )
        before = db.connection.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError), db.transaction():
            create(
                db,
                "owner",
                v["session_id"],
                v["revision"],
                p,
                "travel_intake_v1",
                intake_payload(p),
                "second-model",
            )
        assert (
            db.connection.execute("SELECT count(*) FROM continuation_operations").fetchone()[0]
            == before
        )
