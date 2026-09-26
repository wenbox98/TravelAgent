"""Local replay uses authored fixtures only; never a provider or browser."""

import pytest
import json
from concurrent.futures import ThreadPoolExecutor
from travel_agent.research.context_review import _digest
from travel_agent.research.review_replay import replay, convert_legacy
from travel_agent.research.store import EvidenceStore
from travel_agent.persistence.database import Database
from travel_agent.research.context_review import build_input, check_decision
from test_reference_selection import execute, choice
from test_model_context_review import proposal


def test_legacy_day_route_contract_conflict(tmp_path, clock):
    body = "我计划秋季出发，还没出发。\n行程草案。\nDay4：合成甲地到合成乙地。"
    with Database(tmp_path / "replay.sqlite3", clock=clock) as db:
        store, _, out = execute(db, clock, lambda s: [choice(s, 2, (0, 1))], body)
        data, ctx = build_input(store, out["attempt_id"], "owner", {}, version=1)
        p = proposal(data)
        p["duration_scope"] = "DAY_SEGMENT"
        with pytest.raises(ValueError, match="DURATION_SCOPE_MISMATCH"):
            check_decision(p, data, ctx)
        from travel_agent.research.review_replay import convert_legacy

        converted, audit = convert_legacy(p, data, ctx)
        assert audit["old"] == "DAY_SEGMENT" and audit["new"] == "NONE"
        assert check_decision(converted, data | {"review_version": 2}, ctx)["action"] == "ACCEPT"


SHA = "a" * 40
BODY = "我计划秋季出发，还没出发。\n行程草案。\nDay4：合成甲地到合成乙地。\nDay4：我想在湖边散步。\nDay4：大巴每天八点发车。\n景色也许很美。"


def legacy(db, clock, mode="RUNTIME"):
    store, _, out = execute(
        db,
        clock,
        lambda s: [
            choice(s, 2, (0, 1)),
            choice(s, 3, (0, 1), "EXPERIENCE"),
            choice(s, 4, (0, 1), "TRANSPORT"),
            choice(s, 5, (0, 1), "SEASON"),
        ],
        BODY,
    )
    data, ctx = build_input(store, out["attempt_id"], "owner", {}, version=1)
    rows = []
    for i in range(4):
        p = proposal(data, i)
        p["duration_scope"] = "DAY_SEGMENT"
        if i == 3:
            p.update(
                decision="NEEDS_REVIEW", reason_code="CONTEXT_UNCERTAIN", duration_scope="NONE"
            )
        try:
            result = check_decision(p, data, ctx)
        except ValueError as e:
            result = dict(action="NEEDS_REVIEW", reason_code=str(e))
        rows.append(dict(candidate_index=i, proposal=p, program=result))
    con = db.connection
    con.execute(
        "INSERT INTO research_continuations VALUES('fixture-closed','owner','fixture','{}',?,NULL,?,'{}','{}')",
        (db.stamp(), db.stamp()),
    )
    con.execute(
        "INSERT INTO context_review_runs VALUES('review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb','fixture-closed',?,'owner',?,0,?,'{}','COMPLETED',NULL,?,?,?,1,1)",
        (out["attempt_id"], mode, _digest(data), json.dumps(rows), db.stamp(), db.stamp()),
    )
    return store, out, data, ctx


def frozen(db):
    return {
        t: [tuple(r) for r in db.connection.execute("SELECT * FROM " + t)]
        for t in [
            "context_review_runs",
            "extraction_candidates",
            "extraction_attempts",
            "extraction_batches",
            "research_continuations",
            "continuation_operations",
        ]
    }


def test_replay_partial_retention_history_immutable_and_recovery(tmp_path, clock):
    path = tmp_path / "local.sqlite3"
    with Database(path, clock=clock) as db:
        store, _, _, _ = legacy(db, clock)
        before = frozen(db)
        dry = replay(store, "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "owner", SHA)
        assert dry["converted"] == 3
        assert dry["accepted"] == 2 and dry["pending"] == 2 and dry["added"] == 2
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert frozen(db) == before
        result = replay(
            store, "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "owner", SHA, dry_run=False
        )
        assert result["added"] == 2 and frozen(db) == before
        assert result["results"][2]["program"]["reason_code"] == "UNVERIFIED_IMPORTANT_FACT"
        assert result["results"][3]["program"]["reason_code"] == "CONTEXT_UNCERTAIN"
        assert (
            replay(store, "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "owner", SHA, dry_run=False)[
                "revalidation_id"
            ]
            == result["revalidation_id"]
        )
    with Database(path, clock=clock) as db:
        from travel_agent.preview.service import PreviewService

        row = db.connection.execute("SELECT research_id FROM review_revalidations").fetchone()
        q, ev = PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW")._cache(row[0])
        assert sum(len(b["claims"]) for b in ev) == 2
        assert {m["context_review_status"] for b in ev for m in b["claim_metadata"].values()} == {
            "LOCAL_REVALIDATION"
        }
        assert frozen(db) == before


def test_evaluation_never_publishes(tmp_path, clock):
    with Database(tmp_path / "eval.sqlite3", clock=clock) as db:
        store, _, _, _ = legacy(db, clock, "EVALUATION")
        before = frozen(db)
        r = replay(store, "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "owner", SHA, dry_run=False)
        assert r["accepted"] == 2 and r["added"] == 0
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert (
            db.connection.execute("SELECT research_id FROM review_revalidations").fetchone()[0]
            is None
        )
        assert frozen(db) == before


@pytest.mark.parametrize("defect", ["scope", "revision", "hash", "snapshot", "policy", "missing"])
def test_replay_rejects_stale_revoked_missing(tmp_path, clock, defect):
    with Database(tmp_path / "stale.sqlite3", clock=clock) as db:
        store, out, _, ctx = legacy(db, clock)
        if defect == "revision":
            db.connection.execute(
                "UPDATE research_questions SET current_revision=current_revision+1"
            )
        elif defect == "hash":
            db.connection.execute("UPDATE context_review_runs SET input_hash='changed'")
        elif defect == "snapshot":
            db.connection.execute("UPDATE extraction_attempts SET content_hash='changed'")
        elif defect == "policy":
            p = store._latest_policy(ctx["content"]["policy_id"]).to_dict()
            p.update(version=p["version"] + 1, allow_read=False)
            db.connection.execute(
                "INSERT INTO source_policies VALUES(?,?,?,?,?)",
                (p["policy_id"], p["version"], json.dumps(p), p["reviewed_at"], p["expires_at"]),
            )
        elif defect == "missing":
            db.connection.execute("UPDATE context_review_runs SET results_json=NULL")
        with pytest.raises((ValueError, PermissionError)):
            replay(
                store,
                "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "stranger" if defect == "scope" else "owner",
                SHA,
                dry_run=False,
            )
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0


@pytest.mark.parametrize(
    "defect",
    [
        "foreign",
        "unsent",
        "no_anchor",
        "amount",
        "model_pending",
        "model_reject",
        "topic",
        "omitted",
        "role",
        "whole",
    ],
)
def test_compatibility_is_not_blanket_accept(tmp_path, clock, defect):
    with Database(tmp_path / "guards.sqlite3", clock=clock) as db:
        store, _, data, ctx = legacy(db, clock)
        p = proposal(data)
        p["duration_scope"] = "DAY_SEGMENT"
        if defect in {"foreign", "unsent"}:
            p["object_span_id"] = "Pnot-sent-other-source"
        elif defect == "no_anchor":
            p = proposal(data, 3)
            p["duration_scope"] = "DAY_SEGMENT"
        elif defect == "amount":
            ctx["raw"][0]["quote"] += "全程四天。"
        elif defect in {"model_pending", "model_reject"}:
            p.update(
                decision="NEEDS_REVIEW" if defect == "model_pending" else "REJECT",
                reason_code="CONTEXT_UNCERTAIN",
            )
            converted, audit = convert_legacy(p, data, ctx)
            assert audit is None and converted["decision"] == p["decision"]
            return
        elif defect == "topic":
            p["candidate_topic"] = "DURATION"
            p["duration_scope"] = "NONE"
            with pytest.raises(ValueError):
                check_decision(p, data | {"review_version": 2}, ctx)
            return
        elif defect == "omitted":
            p["context_span_ids"] = []
        elif defect == "role":
            p["reference_scope"] = "AUTHOR_RECORDED_TRIP"
        elif defect == "whole":
            p["duration_scope"] = "WHOLE_TRIP"
        from travel_agent.providers.llm import LLMError

        with pytest.raises((ValueError, LLMError)):
            converted, _ = convert_legacy(p, data, ctx)
            check_decision(converted, data | {"review_version": 2}, ctx)


def test_concurrent_replay_exactly_once(tmp_path, clock):
    path = tmp_path / "parallel.sqlite3"
    with Database(path, clock=clock) as db:
        legacy(db, clock)

    def run(_):
        with Database(path, clock=clock) as db:
            return replay(
                EvidenceStore(db),
                "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "owner",
                SHA,
                dry_run=False,
            )["revalidation_id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(run, [1, 2]))
    assert ids[0] == ids[1]
    with Database(path, clock=clock) as db:
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 2


def test_orphan_dependency_after_conversion_still_pending(tmp_path, clock):
    with Database(tmp_path / "orphan.sqlite3", clock=clock) as db:
        store, _, data, _ = legacy(db, clock)
        rows = json.loads(
            db.connection.execute("SELECT results_json FROM context_review_runs").fetchone()[0]
        )
        rows[1]["proposal"]["object_span_id"] = data["candidates"][1]["statement_span_id"]
        db.connection.execute("UPDATE context_review_runs SET results_json=?", (json.dumps(rows),))
        r = replay(store, "review-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "owner", SHA, dry_run=False)
        assert r["accepted"] == 1 and r["added"] == 1
        assert r["results"][1]["conversion"]
        assert r["results"][1]["program"]["reason_code"] == "DEPENDENCY_UNRESOLVED"


@pytest.mark.parametrize("topic", ["ROUTE", "EXPERIENCE", "TRANSPORT"])
def test_ordinal_is_not_elapsed_duration(tmp_path, clock, topic):
    with Database(tmp_path / "ordinal.sqlite3", clock=clock) as db:
        body = "我计划秋季出发，还没出发。\n行程草案。\nDay12：我想从甲地骑车到乙地。"
        store, _, out = execute(db, clock, lambda s: [choice(s, 2, (0, 1), topic)], body)
        data, ctx = build_input(store, out["attempt_id"], "owner", {}, version=1)
        p = proposal(data)
        p["duration_scope"] = "DAY_SEGMENT"
        p, audit = convert_legacy(p, data, ctx)
        d = check_decision(p, data | {"review_version": 2}, ctx)
        assert d["action"] == "ACCEPT" and "duration_scope" not in d and audit


@pytest.mark.parametrize(
    "body,kind,scope,allowed",
    [
        (
            "这是去年走过的路线。\n记录。\n全程实际用了五天。",
            "AUTHOR_RECORDED_TRIP",
            "WHOLE_TRIP",
            True,
        ),
        (
            "我打算明年出发。\n计划。\n打算全程安排五天。",
            "AUTHOR_PROPOSED_PLAN",
            "WHOLE_TRIP",
            True,
        ),
        (
            "我打算明年出发。\n计划。\nDay4 在甲地走两小时。",
            "AUTHOR_PROPOSED_PLAN",
            "DAY_SEGMENT",
            True,
        ),
        (
            "我打算明年出发。\n计划。\nDay4：合成甲地。",
            "AUTHOR_PROPOSED_PLAN",
            "DAY_SEGMENT",
            False,
        ),
        (
            "我打算明年出发。\n计划。\n打算全程安排五天。",
            "AUTHOR_RECORDED_TRIP",
            "WHOLE_TRIP",
            False,
        ),
    ],
)
def test_duration_protocol_and_role(tmp_path, clock, body, kind, scope, allowed):
    with Database(tmp_path / "duration.sqlite3", clock=clock) as db:
        store, _, out = execute(
            db, clock, lambda s: [choice(s, 2, (0, 1), "DURATION", kind=kind)], body
        )
        data, ctx = build_input(store, out["attempt_id"], "owner", {"days": 5})
        p = proposal(data)
        p.update(reference_scope=kind, duration_scope=scope)
        if allowed:
            assert check_decision(p, data, ctx)["action"] == "ACCEPT"
        else:
            with pytest.raises(ValueError):
                check_decision(p, data, ctx)


def test_explanations_whitelist_readonly_and_adoption(tmp_path, clock):
    from fastapi.testclient import TestClient
    from travel_agent.main import create_app
    from travel_agent.settings import Settings
    from travel_agent.preview.api import PreviewConfig
    from travel_agent.preview.service import PreviewService
    from travel_agent.preview.replay_api import review_index
    from travel_agent.research.candidate_review import review_candidates
    from test_candidate_grounding import accept

    path = tmp_path / "api.sqlite3"
    with Database(path, clock=clock) as db:
        store, out, data, ctx = legacy(db, clock)
        # Authored existing Work-reviewed reference; replay must preserve it.
        d = accept()
        d.update(reference_scope="AUTHOR_PROPOSED_PLAN")
        review_candidates(
            store, attempt_id=out["attempt_id"], account_scope="owner", decisions={0: d}
        )
        service = PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW")
        v = service.open(ctx["attempt"]["research_id"], "五天，不自驾", "test-open")
        option = v["options"][0]["option_id"]
        v = service.mutate(
            v["session_id"],
            dict(action="preview", option_id=option, expected_revision=v["revision"]),
            "test-preview",
        )
        v = service.mutate(
            v["session_id"],
            dict(action="confirm", option_id=option, expected_revision=v["revision"]),
            "test-confirm",
        )
        original = frozen(db)
        result = replay(store, "review-" + "b" * 32, "owner", SHA, dry_run=False)
        assert result["added"] == 1
        before_changes = db.connection.total_changes
        idx = review_index(db, "owner", "CACHED_PRIVATE_PREVIEW")
        assert db.connection.total_changes == before_changes
        assert idx["updates"] and all(i["explanation"] and i["next_action"] for i in idx["items"])
        assert not {"proposal", "context_span_ids", "binding_json"} & idx["items"][0].keys()
        assert frozen(db) == original
    config = PreviewConfig(
        path, "owner", "CACHED_PRIVATE_PREVIEW", b"a" * 32, ticket="test-ticket", local_replay=True
    )
    with TestClient(
        create_app(Settings.load(preferred_port=8877), preview=config),
        base_url="http://127.0.0.1:8877",
    ) as c:
        assert c.get("/api/v1/preview/reviews").status_code == 401
        c.get("/bootstrap?ticket=test-ticket")
        assert 'ta_preview_8877' in c.cookies and 'ta_preview' not in c.cookies
        index = c.get("/api/v1/preview").json()
        before = index["session"]
        for _ in range(2):
            assert c.get("/api/v1/preview/reviews").status_code == 200
        assert c.get("/api/v1/preview").json()["session"] == before
        assert c.post("/api/v1/preview/jobs", json={}).status_code in {403, 404}
        headers = {
            "Origin": "http://127.0.0.1:8877",
            "X-CSRF-Token": index["csrf_token"],
            "Idempotency-Key": "adopt-replay",
        }
        payload = dict(
            session_id=v["session_id"],
            revalidation_id=result["revalidation_id"],
            expected_revision=v["revision"],
        )
        res = c.post("/api/v1/preview/review-update", json=payload, headers=headers)
        assert res.status_code == 200, res.text
        adopted = res.json()
        assert adopted["evidence_count"] == 2 and adopted["preferences"] == before["preferences"]
        assert (
            adopted["confirmed_option_id"] == before["confirmed_option_id"]
            or not adopted["interest_needs_confirmation"]
        )
        assert (
            c.post("/api/v1/preview/review-update", json=payload, headers=headers).json() == adopted
        )
    with Database(path, clock=clock) as db:
        assert PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW").latest() == adopted
        assert frozen(db) == original
