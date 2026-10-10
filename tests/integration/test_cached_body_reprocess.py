# ruff: noqa: F811
"""Explicit cache-body operations and intake boundaries; synthetic data only."""

import json
import sqlite3
from uuid import uuid4
import pytest
from travel_agent.planning.agent_contract import CONSENT, cached_body_reprocess_requested, understanding
from travel_agent.planning.automatic_models import AutomaticStart
from travel_agent.planning.agent import run
from travel_agent.planning.conversation import action, ConversationAction
from travel_agent.preview import worker
from travel_agent.research.cached_reprocess import prepare
from test_goal_agent import Wire, choose, intake, service  # noqa: F401
from test_goal_research_budget import MultiModel, MultiReader
from test_workbench_pipeline import dispatches
from automatic_fakes import config


def test_play_request_matches_actual_play_detail_gap_without_unrelated_reanalysis():
    from travel_agent.research.cached_reprocess import gap_keys
    gaps = [dict(key="PLAY_DETAIL"), dict(key="LODGING"), dict(key="TRANSPORT")]
    assert gap_keys("用已缓存正文按当前玩法缺口重新分析", gaps) == ("PLAY_DETAIL",)


def test_play_reanalysis_ranks_concrete_bound_content_before_newer_generic_note(monkeypatch):
    from types import SimpleNamespace
    import travel_agent.research.cached_reprocess as module
    def content(identifier, text, time):
        return dict(content_id=identifier, source_id="synthetic:" + identifier, content_hash="a" * 64,
            normalization_version=1, policy_id="authored", policy_version=1,
            content_completeness="FULL_TEXT", normalized_text=text, retrieved_at=time)
    rows = [content("new-generic", "游玩攻略很好看。", "2026-10-10T12:00:00"),
        content("play-a", "合成青谷公园可以散步、观赏，合成南馆可以参观、看展。", "2026-10-10T10:00:00"),
        content("play-b", "合成南馆可以欣赏、体验展陈。", "2026-10-10T09:00:00")]
    monkeypatch.setattr("travel_agent.planning.workbench.local_contents", lambda *args: rows)
    monkeypatch.setattr(module, "external_allowed", lambda *args: True)
    db = SimpleNamespace(connection=SimpleNamespace(execute=lambda *args: []))
    p = dict(draft=dict(activities=[dict(name="合成青谷公园"), dict(name="合成南馆")]))
    result = prepare(db, "owner", "authored-session", p, "用已缓存正文按当前玩法缺口重新分析", [dict(key="PLAY_DETAIL")])
    assert [s["content_id"] for s in result["snapshots"]] == ["play-a", "play-b"]


@pytest.mark.parametrize("text,expected", [
    ("用已缓存正文按当前住宿缺口重新分析", True),
    ("请使用已缓存的正文按当前缺口重新提取。本次最多6次模型请求。", True),
    ("用已缓存正文按当前缺口重新分析，不要搜索，不必排满每天", True),
    ("用已缓存资料生成建议", False),
    ("如果用已缓存正文重新分析呢", False),
    ("能否用已缓存正文重新分析？", False),
    ("不要用已缓存正文重新分析", False),
    ('作者说“用已缓存正文重新分析”', False),
    ("我想了解用已缓存正文重新分析的作用", False),
])
def test_explicit_cached_body_intent(text, expected):
    assert cached_body_reprocess_requested(text) is expected


@pytest.mark.parametrize("text", ["不要求精确时刻", "不必排满每天", "不用把每天排满，也不用精确时间"])
def test_output_flexibility_cannot_set_relaxed_pace(text):
    with pytest.raises(ValueError, match="INTAKE_PACE_EVIDENCE_REQUIRED"):
        understanding(intake(text, [("pace", "RELAXED", text)]), text)


@pytest.mark.parametrize("text", ["轻松一些", "我想悠闲地逛", "慢一点，不赶路"])
def test_explicit_relaxed_pace_remains_supported(text):
    assert understanding(intake(text, [("pace", "RELAXED", text)]), text).updates[0].value == "RELAXED"


@pytest.fixture
def cached_trip(service, monkeypatch):
    oracle = MultiModel()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [("destination", "合成青谷", "合成青谷"), ("days", 3, "三天")])
        if task == "travel_supervisor_v1":
            return choose("FINISH", stop="PARTIAL") if data["previous_results"] else choose(
                "RESEARCH_GAP", query="合成青谷 玩法交通", gap_key="PLAY")
        if task == "select_evidence_references_v1":
            result = oracle.structured(task, data, {})
            result["claims"] = [c for c in result["claims"] if c["topic"] != "TRADEOFF"]
            return result
        return oracle.structured(task, data, {})

    wire = Wire(monkeypatch, respond)
    view = service.start(AutomaticStart(request="合成青谷三天", consent=CONSENT), str(uuid4()))
    extract, review = dispatches(config())
    run(service.db.path, view["automatic_task"]["task_id"], provider=config(), reader=MultiReader(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(view["session_id"])
    assert service.db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0] == 2
    return service, final, wire, oracle


def submit(service, view, text):
    return action(service.db, "owner", view["session_id"], ConversationAction(
        action="submit", text=text, consent=CONSENT, expected_revision=view["revision"],
        expected_conversation_version=view["conversation"]["version"]), str(uuid4()))


def test_normal_dialogue_reextracts_cached_bodies_through_child_and_strict_review(cached_trip, monkeypatch):
    service, view, wire, oracle = cached_trip
    old = {table: [tuple(row) for row in service.db.connection.execute("SELECT * FROM " + table)]
           for table in ("extraction_attempts", "extraction_candidates", "context_review_runs", "continuation_operations", "claims")}
    old_grant = view["automatic_task"]["budget"]
    wire.sent.clear()
    text = "用已缓存正文按当前住宿缺口重新分析。本次最多8次模型请求。"
    wire.respond = lambda task, data: (intake(data["user_text"], []) if task == "travel_intake_v1"
        else choose("FINISH", stop="PARTIAL") if task == "travel_supervisor_v1"
        else oracle.structured(task, data, {}))
    commands = []

    def supervised(database, attempt, *, command, **kwargs):
        commands.append(command)
        gaps = tuple(command[command.index("--research-gaps") + 1:])
        with worker.Database(database) as db:
            store = worker.EvidenceStore(db)
            worker.extract_worker(store, config(), attempt, research_gaps=gaps)
            return worker.ExtractionRecovery(store, worker.EvidenceExtractor(config())).outcome(attempt)

    monkeypatch.setattr(worker, "supervise_reserved", supervised)
    def forbidden(*args, **kwargs):
        pytest.fail("cached-body path constructed a site reader")
    monkeypatch.setattr("travel_agent.research.live.LiveResearchReader", forbidden)
    created = submit(service, view, text)
    limits = created["automatic_task"]["limits"]
    assert all(limits[k] == 0 for k in ("connect", "search", "detail", "map_place", "map_route"))
    assert limits["model"] == 8
    _, review = dispatches(config())
    run(service.db.path, created["automatic_task"]["task_id"], provider=config(), review_dispatch=review)
    final = service.plans.get(view["session_id"])
    extracts = [e for e in wire.sent if e["task"] == "select_evidence_references_v1"]
    assert len(extracts) == len(commands) == 2, (final["automatic_task"], wire.errors)
    assert all(e["input"]["research_gaps"] == ["LODGING"] for e in extracts)
    assert len([e for e in wire.sent if e["task"] == "review_evidence_context_v2"]) == 2
    assert final["automatic_task"]["budget"]["used"]["model"] == 6, (final["automatic_task"], wire.errors)
    assert final["automatic_task"]["agent_rounds"][0]["tool"] == "CACHED_BODY"
    result = final["automatic_task"]["agent_rounds"][0]["result"]
    assert result["accepted"] == 2
    assert result["reused"] == len(old["claims"])
    assert result["available"] == result["accepted"] + result["reused"]
    assert result["reviewed"] >= result["accepted"]
    assert final["automatic_task"]["search_count"] == final["automatic_task"]["new_body_count"] == 0
    assert not wire.errors
    for table, rows in old.items():
        now = [tuple(row) for row in service.db.connection.execute("SELECT * FROM " + table)]
        assert now[:len(rows)] == rows, table
    assert old_grant["closed"]
    count = len(wire.sent)
    with pytest.raises(ValueError, match="CACHE_BODY_NO_CURRENT_GAP"):
        submit(service, final, text)
    assert len(wire.sent) == count
    _, state = service.plans.load(view["session_id"])
    with pytest.raises(ValueError, match="CACHE_BODY_NO_ELIGIBLE_OR_NEW_SNAPSHOT"):
        prepare(service.db, "owner", view["session_id"], state["planning"], text, [{"key": "LODGING"}])
    # A genuinely changed gap or prompt version has a different analysis recipe.
    assert prepare(service.db, "owner", view["session_id"], state["planning"],
                   "用已缓存正文按当前玩法缺口重新分析", [{"key": "PLAY"}])["gaps"] == ["PLAY"]
    monkeypatch.setattr("travel_agent.research.cached_reprocess.REFERENCE_PROMPT_VERSION", "synthetic-next-version")
    assert prepare(service.db, "owner", view["session_id"], state["planning"], text,
                   [{"key": "LODGING"}])["prompt_version"] == "synthetic-next-version"


@pytest.mark.parametrize("damage", ["missing", "cleared", "revoked", "external_revoked", "hash", "normalization", "summary"])
def test_invalid_cached_snapshot_never_issues_grant_or_calls_model(cached_trip, damage):
    service, view, wire, _ = cached_trip
    con = service.db.connection
    if damage == "missing":
        con.execute("DELETE FROM source_contents")
    elif damage == "cleared":
        con.execute("UPDATE knowledge_raw_state SET state='USER_CLEARED',changed_at=?", (service.db.stamp(),))
    elif damage in {"revoked", "external_revoked"}:
        for row in con.execute("SELECT policy_id,version,policy_json FROM source_policies").fetchall():
            policy = json.loads(row[2])
            policy["allow_inference" if damage == "revoked" else "allow_external_model"] = False
            con.execute("UPDATE source_policies SET policy_json=? WHERE policy_id=? AND version=?",
                        (json.dumps(policy), row[0], row[1]))
    elif damage == "hash":
        con.execute("UPDATE source_contents SET content_hash=?", ("0" * 64,))
    elif damage == "normalization":
        with pytest.raises(sqlite3.IntegrityError, match="normalization_version"):
            con.execute("UPDATE source_contents SET normalization_version=99")
        return
    else:
        with pytest.raises(sqlite3.IntegrityError, match="content_completeness"):
            con.execute("UPDATE source_contents SET content_completeness='SUMMARY_ONLY'")
        return
    grants = con.execute("SELECT count(*) FROM research_continuations").fetchone()[0]
    count = len(wire.sent)
    _, state = service.plans.load(view["session_id"])
    with pytest.raises((ValueError, PermissionError)):
        prepare(service.db, "owner", view["session_id"], state["planning"],
                "用已缓存正文按当前住宿缺口重新分析", [{"key": "LODGING"}])
    assert con.execute("SELECT count(*) FROM research_continuations").fetchone()[0] == grants
    assert len(wire.sent) == count


@pytest.mark.parametrize("stage", ["select_evidence_references_v1", "review_evidence_context_v2"])
def test_cancel_before_model_late_result_cannot_commit_or_continue(cached_trip, stage):
    from travel_agent.planning.automatic_models import AutomaticAction

    service, view, wire, oracle = cached_trip
    prior = [tuple(r) for r in service.db.connection.execute("SELECT * FROM claims")]
    created = submit(service, view, "用已缓存正文按当前住宿缺口重新分析")
    wire.sent.clear()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [])
        if task == stage:
            latest = service.plans.get(view["session_id"])
            service.action(view["session_id"], AutomaticAction(action="cancel",
                expected_revision=latest["revision"]), str(uuid4()))
        return oracle.structured(task, data, {})

    wire.respond = respond
    extract, review = dispatches(config())
    run(service.db.path, created["automatic_task"]["task_id"], provider=config(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(view["session_id"])
    assert [tuple(r) for r in service.db.connection.execute("SELECT * FROM claims")] == prior
    assert final["automatic_task"]["status"] == "CANCELED"
    assert final["automatic_task"]["budget"]["closed"]
    assert [e["task"] for e in wire.sent][-1] == stage
    assert len(wire.sent) == (2 if stage == "select_evidence_references_v1" else 3)


@pytest.mark.parametrize("defect", ["envelope", "all_invalid_items"])
def test_second_body_failure_keeps_independent_first_body_without_retry(cached_trip, defect):
    service, view, wire, oracle = cached_trip
    created = submit(service, view, "用已缓存正文按当前住宿缺口重新分析")
    wire.sent.clear()
    extraction_count = 0

    def respond(task, data):
        nonlocal extraction_count
        if task == "travel_intake_v1":
            return intake(data["user_text"], [])
        if task == "select_evidence_references_v1":
            extraction_count += 1
            if extraction_count == 2:
                return {"claims": "invalid envelope"} if defect == "envelope" else {"claims": [{"invalid": "synthetic failure"}]}
        return oracle.structured(task, data, {})

    wire.respond = respond
    extract, review = dispatches(config())
    before = service.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    run(service.db.path, created["automatic_task"]["task_id"], provider=config(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(view["session_id"])
    assert service.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == before + 1
    assert extraction_count == 2
    if defect == "envelope":
        assert len(wire.sent) == 4
        assert final["automatic_task"]["reason"] == "CACHE_BODY_EXTRACTION_NOT_COMPLETED"
    else:
        assert not final["automatic_task"]["reason"].startswith("CACHE_BODY_")
        assert final["automatic_task"]["agent_rounds"][0]["result"]["reason"] is None
    assert final["automatic_task"]["agent_rounds"][0]["result"]["accepted"] > 0


def test_policy_revoked_after_permission_stops_before_extraction(cached_trip):
    service, view, wire, oracle = cached_trip
    created = submit(service, view, "用已缓存正文按当前住宿缺口重新分析")
    wire.sent.clear()

    def respond(task, data):
        assert task == "travel_intake_v1"
        for row in service.db.connection.execute("SELECT policy_id,version,policy_json FROM source_policies").fetchall():
            policy = json.loads(row[2])
            policy["allow_external_model"] = False
            service.db.connection.execute("UPDATE source_policies SET policy_json=? WHERE policy_id=? AND version=?",
                                          (json.dumps(policy), row[0], row[1]))
        return intake(data["user_text"], [])

    wire.respond = respond
    extract, review = dispatches(config())
    run(service.db.path, created["automatic_task"]["task_id"], provider=config(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(view["session_id"])
    assert len(wire.sent) == 1
    assert final["automatic_task"]["status"] in {"BLOCKED", "PARTIAL"}
    assert final["automatic_task"]["reason"] == "CACHE_BODY_SNAPSHOT_OR_POLICY_DENIED"
    assert service.db.connection.execute("SELECT count(*) FROM extraction_attempts WHERE batch_id=(SELECT grant_id FROM planning_tasks WHERE task_id=?)",
        (created["automatic_task"]["task_id"],)).fetchone()[0] == 0


def test_accepted_duplicates_are_not_reported_as_new_evidence(cached_trip):
    service, view, wire, oracle = cached_trip
    before = service.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    created = submit(service, view, "用已缓存正文按当前住宿缺口重新分析")
    wire.sent.clear()

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [])
        if task == "travel_supervisor_v1":
            return choose("FINISH", stop="PARTIAL")
        result = oracle.structured(task, data, {})
        if task == "select_evidence_references_v1":
            result["claims"] = [c for c in result["claims"] if c["topic"] != "TRADEOFF"]
        return result

    wire.respond = respond
    extract, review = dispatches(config())
    run(service.db.path, created["automatic_task"]["task_id"], provider=config(),
        extract_dispatch=extract, review_dispatch=review)
    final = service.plans.get(view["session_id"])
    result = final["automatic_task"]["agent_rounds"][0]["result"]
    assert service.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == before
    assert result["accepted"] == 0 and result["reviewed"] > 0
    assert result["available"] == result["reused"] == before
    assert len(wire.sent) == 6 and final["automatic_task"]["budget"]["closed"]


@pytest.mark.parametrize("boundary", ["before_parent_review", "before_review_child", "late_review_reply"])
def test_external_permission_revocation_at_review_boundaries(cached_trip, boundary):
    from travel_agent.research.context_review import reserve_review, run_review

    service, view, wire, oracle = cached_trip
    before = [tuple(r) for r in service.db.connection.execute("SELECT * FROM claims")]
    created = submit(service, view, "用已缓存正文按当前住宿缺口重新分析")
    wire.sent.clear()

    def revoke():
        for row in service.db.connection.execute("SELECT policy_id,version,policy_json FROM source_policies").fetchall():
            policy = json.loads(row[2])
            policy["allow_external_model"] = False
            service.db.connection.execute("UPDATE source_policies SET policy_json=? WHERE policy_id=? AND version=?",
                                         (json.dumps(policy), row[0], row[1]))

    def respond(task, data):
        if task == "travel_intake_v1":
            return intake(data["user_text"], [])
        if task == "review_evidence_context_v2":
            assert boundary == "late_review_reply"
            revoke()
        return oracle.structured(task, data, {})

    wire.respond = respond
    extract, review = dispatches(config())
    def wrapped_extract(store, attempt, gaps):
        result = extract(store, attempt, gaps)
        if boundary == "before_parent_review":
            revoke()
        return result

    def wrapped_review(store, budget, attempt, scope, target):
        if boundary == "before_review_child":
            rid = reserve_review(store, budget, attempt, scope, target)
            revoke()
            return run_review(store, config(), rid)
        return review(store, budget, attempt, scope, target)

    run(service.db.path, created["automatic_task"]["task_id"], provider=config(),
        extract_dispatch=wrapped_extract, review_dispatch=wrapped_review)
    final = service.plans.get(view["session_id"])
    assert [tuple(r) for r in service.db.connection.execute("SELECT * FROM claims")] == before
    assert len(wire.sent) == (3 if boundary == "late_review_reply" else 2)
    assert final["automatic_task"]["budget"]["closed"]
    assert final["automatic_task"]["agent_rounds"][0]["result"]["accepted"] == 0


def test_normal_conversation_http_routes_cache_analysis_without_external_dispatch(cached_trip, monkeypatch):
    from fastapi.testclient import TestClient
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.main import create_app
    from travel_agent.settings import Settings

    service, view, wire, _ = cached_trip
    launches = []
    monkeypatch.setattr("travel_agent.planning.suggestions.launch", lambda *a, **kw: launches.append(kw))
    cfg = PreviewConfig(service.db.path, "owner", "CACHED_PRIVATE_PREVIEW", b"fixture",
                        product_flow=True, daily_workbench=True)
    calls = len(wire.sent)
    with TestClient(create_app(Settings.load(preferred_port=18775), preview=cfg),
                    base_url="http://127.0.0.1:18775") as client:
        client.get("/bootstrap?ticket=" + cfg.ticket)
        csrf = client.get("/api/v1/preview").json()["csrf_token"]
        headers = {"origin": "http://127.0.0.1:18775", "x-csrf-token": csrf,
                   "idempotency-key": str(uuid4())}
        body = dict(action="submit", text="用已缓存正文按当前住宿缺口重新分析", consent=CONSENT,
                    expected_revision=view["revision"], expected_conversation_version=view["conversation"]["version"])
        url = "/api/v1/preview/conversation/" + view["session_id"]
        first = client.post(url, json=body, headers=headers)
        assert first.status_code == 200, first.text
        again = client.post(url, json=body, headers=headers)
        assert again.status_code == 200
        assert first.json()["automatic_task"]["task_id"] == again.json()["automatic_task"]["task_id"]
        assert first.json()["automatic_task"]["limits"]["search"] == 0
        assert len(wire.sent) == calls and launches
