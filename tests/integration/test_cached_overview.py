"""P01 authored fixtures; cache presentation must never initiate research."""
import json
from copy import deepcopy

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.candidate_review import review_candidates
from test_candidate_grounding import accept, candidate, prepare


def seed(db, clock):
    body = "我计划秋季自驾，还未出发。\n甲路线草案。\n" + "\n".join(
        f"Day{i}：合成地点{i}→合成地点{i+1}。" for i in range(1, 8))
    body += "\n乙路线草案。\nDay4：合成山谷散步。"
    rows = [candidate(line, i, "ROUTE", [{"text": body.splitlines()[0],
            "quote": body.splitlines()[0], "source_block_id": 0}])
            for i, line in enumerate(body.splitlines()) if line.startswith("Day")]
    for row in rows:
        row["source_block_ids"].append(0)
    store, runner, _, kwargs = prepare(db, clock, rows, body=body)
    out = runner.execute(**kwargs)
    review_candidates(store, attempt_id=out["attempt_id"], account_scope="owner", decisions={
        i: accept(reference_scope="AUTHOR_PROPOSED_PLAN", route_association={
            "object_quote": "甲路线草案。" if i < 7 else "乙路线草案。",
            "object_block_id": 1 if i < 7 else 9, "scope": "SEGMENT"}) for i in range(8)})
    return store


def service(db):
    from travel_agent.preview.service import PreviewService
    return PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW")


def test_vague_request_cards_schedule_not_duration(tmp_path, clock):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        view = service(db).open("partial", "国庆想去合成青谷玩", "create-0001")
        assert len(view["options"]) == 2
        assert view["preferences"]["budget_cny_fen"] is None
        assert view["preferences"]["traveler_count"] is None
        assert view["preferences"]["time_hint"] == "国庆"
        a, b = view["options"]
        assert a["source_schedule"]["day_count"] == 7
        assert a["source_schedule"]["basis"] == "DERIVED_FROM_SOURCE_SCHEDULE"
        assert a["verified_duration_days"] is None and a["cost_cny_fen"] is None
        assert b["source_schedule"]["day_count"] is None
        assert len(a["source_schedule"]["entries"]) == 7
        assert all(e["evidence_ids"] for e in a["source_schedule"]["entries"])
        assert a["reference_kinds"] == ["AUTHOR_PROPOSED_PLAN"]
        assert a["independent_source_count"] is None
        assert len(view["questions"]) == 2


def test_switch_cancel_revision_idempotence_and_restart(tmp_path, clock):
    path = tmp_path / "cache.sqlite3"
    with Database(path, clock=clock) as db:
        seed(db, clock)
        s = service(db)
        v = s.open("partial", "", "create-0002")
        original = deepcopy(v["options"])
        a, b = [o["option_id"] for o in original]
        def change(action, key, **values):
            nonlocal v
            v = s.mutate(v["session_id"], {"action": action, "expected_revision": v["revision"], **values}, key)
        change("preferences", "prefs-001", preferences={"days": 5, "driving": "NO"})
        assert not v["questions"] and v["options"] == original
        assert "接驳" in " ".join(v["gaps"])
        change("preview", "preview-a", option_id=a)
        change("confirm", "confirm-a", option_id=a)
        change("preview", "preview-b", option_id=b)
        assert v["confirmed_option_id"] == a and v["preview"]["option_id"] == b
        assert v["preview"]["removed"] and v["preview"]["added"]
        change("cancel", "cancel-b1")
        assert v["confirmed_option_id"] == a and v["preview"] is None
        change("preview", "preview-b2", option_id=b)
        payload = {"action": "confirm", "expected_revision": v["revision"], "option_id": b}
        v = s.mutate(v["session_id"], payload, "confirm-b")
        assert s.mutate(v["session_id"], payload, "confirm-b") == v
        with pytest.raises(ValueError, match="STALE_REVISION"):
            s.mutate(v["session_id"], payload, "old-confirm")
        with pytest.raises(ValueError, match="OPTION_UNAVAILABLE"):
            s.mutate(v["session_id"], {"action": "preview", "expected_revision": v["revision"], "option_id": "other-scope"}, "bad-option")
    with Database(path, clock=clock) as db:
        assert service(db).get(v["session_id"]) == v
        assert service(db).get(v["session_id"])["preferences"]["driving"] == "NO"


def test_pending_rejected_modes_scope_and_cache_miss(tmp_path, clock):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        s = service(db)
        missing = s.open(None, "没有缓存的地区", "missing-01")
        assert missing["options"] == [] and missing["input_text"] == "没有缓存的地区"
        assert missing["cache_message"] == "本次预览未启用新资料研究；当前没有足够本地材料"
        row = db.connection.execute("SELECT source_id,claim_metadata_json FROM sources").fetchone()
        meta = json.loads(row[1])
        first = next(iter(meta))
        meta[first]["context_review_status"] = "PENDING"
        meta[first].pop("route_association", None)
        meta[first].pop("reference_scope", None)
        db.connection.execute("UPDATE sources SET claim_metadata_json=?", (json.dumps(meta),))
        v = s.open("partial", "", "pending-01")
        assert first not in {e["claim_id"] for o in v["options"] for e in o["evidence"]}
        from travel_agent.preview.service import PreviewService
        assert PreviewService(db, "owner", "SYNTHETIC_DEMO").researches() == []
        assert PreviewService(db, "other", "CACHED_PRIVATE_PREVIEW").researches() == []
        with pytest.raises(ValueError, match="SESSION_UNAVAILABLE"):
            PreviewService(db, "other", "CACHED_PRIVATE_PREVIEW").get(v["session_id"])


@pytest.mark.parametrize("labels", [[1, 1, 2], [1, 3], [4], [1, 2, 1, 2]])
def test_incomplete_duplicate_or_alternative_schedules_not_counted(labels):
    from travel_agent.preview.projection import source_schedule
    result = source_schedule([{"text": f"Day{x}：合成路线", "claim_id": str(i)} for i, x in enumerate(labels)])
    assert result["day_count"] is None


def test_limited_intent_does_not_guess_conflicting_negation():
    from travel_agent.preview.projection import parse_preferences
    prefs, question = parse_preferences("我只有五天，而且不想自驾")
    assert prefs == {"days": 5, "driving": "NO"} and question is None
    for text in ("不是不想自驾", "五天或七天", "不一定五天", "可能自驾也可能不自驾"):
        prefs, question = parse_preferences(text)
        assert not prefs and question


def test_review_policy_and_research_revision_are_rechecked(tmp_path, clock):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        s = service(db)
        v = s.open("partial", "", "create-policy")
        cid = v["options"][0]["evidence"][0]["claim_id"]
        db.connection.execute("UPDATE extraction_candidates SET context_status='REJECTED' WHERE claim_id=?", (cid,))
        changed = s.get(v["session_id"])
        assert changed["stale"] and cid not in {e["claim_id"] for o in changed["options"] for e in o["evidence"]}
        with pytest.raises(ValueError, match="RESEARCH_CHANGED"):
            s.mutate(v["session_id"], {"action": "cancel", "expected_revision": 0}, "stale-cancel")
        db.connection.execute("UPDATE research_questions SET current_revision=1")
        assert not s.researches()
        assert not s.get(v["session_id"])["options"]


def test_latest_policy_denial_and_expiry_do_not_delete_cache(tmp_path, clock):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        before = db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0]
        db.connection.execute("UPDATE source_contents SET expires_at='2020-01-01T00:00:00+00:00'")
        assert not service(db).researches()
        assert db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0] == before
        db.connection.execute("UPDATE source_contents SET expires_at=NULL")
        row = db.connection.execute("SELECT * FROM source_policies").fetchone()
        policy = json.loads(row["policy_json"])
        policy.update(version=2, allow_read=False)
        db.connection.execute("INSERT INTO source_policies VALUES(?,?,?,?,?)", (policy["policy_id"], 2, json.dumps(policy), policy["reviewed_at"], None))
        assert not service(db).researches()


def test_projection_deduplicates_opinions_and_keeps_source_lineage(tmp_path, clock):
    from travel_agent.domain.models import EvidenceBundle
    from travel_agent.preview.projection import project
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        _, evidence = service(db)._cache("partial")
        original = evidence[0].to_dict()
        duplicate = deepcopy(original["claims"][0])
        old_id = duplicate["claim_id"]
        duplicate["claim_id"] = "duplicate-record"
        original["claims"].append(duplicate)
        original["claim_metadata"]["duplicate-record"] = deepcopy(original["claim_metadata"][old_id])
        p = project((EvidenceBundle(original),), scope="owner", research_id="partial", now=clock())
        assert p["options"][0]["opinion_count"] == 7
        assert p["options"][0]["source_count"] == 1
        assert p["options"][0]["source_schedule"]["day_count"] == 7
        assert all(e["locator"] and e["block_locators"] and e["conditions"] for o in p["options"] for e in o["evidence"])


def test_unknown_choice_saved_and_idempotency_body_conflict(tmp_path, clock):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        seed(db, clock)
        s = service(db)
        v = s.open("partial", "", "create-unknown")
        patch = {"action": "preferences", "expected_revision": 0, "preferences": {"days": None, "driving": "UNKNOWN"}}
        v = s.mutate(v["session_id"], patch, "save-unknown")
        assert not v["questions"] and v["preferences"]["days"] is None
        with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
            s.mutate(v["session_id"], patch | {"expected_revision": 1}, "save-unknown")


def test_api_auth_csrf_host_origin_safe_errors_and_no_live_construction(tmp_path, clock, monkeypatch):
    from fastapi.testclient import TestClient
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.providers.llm import OpenAICompatibleProvider
    from travel_agent.research.service import ResearchService
    path = tmp_path / "cache.sqlite3"
    with Database(path, clock=clock) as db:
        seed(db, clock)
    def forbidden(*args, **kwargs):
        pytest.fail("缓存路径不得构造研究服务或模型")
    monkeypatch.setattr(OpenAICompatibleProvider, "__init__", forbidden)
    monkeypatch.setattr(ResearchService, "__init__", forbidden)
    config = PreviewConfig(path, "owner", "CACHED_PRIVATE_PREVIEW", b"a" * 32)
    with TestClient(create_app(preview=config), base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/v1/preview").status_code == 401
        assert client.get("/bootstrap?ticket=" + config.ticket, headers={"Host": "evil.invalid"}).status_code == 403
        response = client.get("/bootstrap?ticket=" + config.ticket, follow_redirects=False)
        assert response.status_code == 303 and "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/bootstrap?ticket=" + config.ticket).status_code == 401
        data = client.get("/api/v1/preview").json()
        headers = {"Origin": "http://127.0.0.1:8765", "X-CSRF-Token": data["csrf_token"], "Idempotency-Key": "http-create-1"}
        assert client.post("/api/v1/preview/sessions", json={"research_id": "partial"}).status_code == 403
        assert client.get("/api/v1/preview", headers={"Origin": "https://evil.invalid"}).status_code == 403
        good = client.post("/api/v1/preview/sessions", json={"research_id": "partial", "text": "五天、不自驾"}, headers=headers)
        assert good.status_code == 200 and good.json()["preferences"]["driving"] == "NO"
        assert good.headers["Cache-Control"] == "no-store" and "connect-src 'self'" in good.headers["Content-Security-Policy"]
        assert good.json()["business_calls"] == dict(connect=0, search=0, detail=0, xhs_browser=0, model=0)
        assert not any(key in good.text for key in [str(path), "raw_text", "normalized_text", "auth_key", "content_hash", "audit_attempt_id"])
        bad = client.post("/api/v1/preview/sessions", json={"text": "api_key=SECRET_API"}, headers=headers)
        assert bad.status_code == 422 and "SECRET_API" not in bad.text
        assert client.post("/api/v1/auth/xhs/sessions", json={}, headers=headers).status_code == 404
    # A fresh app process uses the same local-only key and persisted selection, without new calls.
    with TestClient(create_app(preview=config), base_url="http://127.0.0.1:8765") as restored:
        restored.cookies.update(client.cookies)
        assert restored.get("/api/v1/preview").json()["session"] == good.json()
