"""Authored sources only: normal API -> async job -> service -> v3 -> review -> preview."""

import sys
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from travel_agent.persistence.database import Database
from travel_agent.preview.jobs import JobService
from travel_agent.preview.service import PreviewService
from travel_agent.preview.worker import run_job
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.context_review import reserve_review, run_review
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import Candidate, DetailMaterial, ResearchRequest
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.store import EvidenceStore
from travel_agent.domain.source_policy import private_policy
from test_reference_selection import choice
from test_model_context_review import BODY, proposal

GRANT = "synthetic-workbench"


class Provider:
    is_external = True
    is_mock = False

    def __init__(self):
        self.calls = []

    def structured(self, task, data, schema):
        self.calls.append(task)
        if task == "select_evidence_references_v1":
            assert data["extraction_version"] == 3
            return {
                "claims": [
                    choice(data["spans"], 2, (0, 1)),
                    choice(data["spans"], 3, (0, 1), "EXPERIENCE"),
                    choice(data["spans"], 4, (0, 1), "TRANSPORT"),
                ]
            }
        assert task == "review_evidence_context_v2"
        output = []
        for i, c in enumerate(data["candidates"]):
            p = proposal(data, i)
            if c["topic"] == "ROUTE":
                p["object_span_id"] = data["spans"][1]["span_id"]
            output.append(p)
        return {"reviews": output}


def add_source(store, name, provider):
    req = ResearchRequest(destination="合成青谷")
    run = store.begin(name, 0, req.to_dict(), "owner")
    policy = store._latest_policy("private-local-research-owner") or private_policy(
        "owner", now=store.db.clock()
    )
    store.register_policy(run, 0, policy)
    store.reserve_operation(run, 0, "DETAIL", "xhs:" + name, 1)
    content = store.save_source(
        run,
        0,
        DetailMaterial("xhs:" + name, "自编合成青谷路线", BODY, "PARTIAL_TEXT", store.db.stamp()),
        policy,
        req.destination,
    )
    return ExtractionRecovery(store, EvidenceExtractor(provider)).execute(
        run_id=run,
        revision=0,
        content_id=content,
        account_scope="owner",
        policy=policy,
        batch_id=name,
        max_attempts=1,
    )["attempt_id"]


def setup(db, provider_config=None):
    from test_cached_overview import seed

    seed(db, db.clock)
    store = EvidenceStore(db)
    provider = Provider()
    attempts = [add_source(store, "eval-" + str(i), provider) for i in range(2)]
    budget = BoundedBudget(store, GRANT)
    budget.grant(
        "owner",
        "partial",
        provider_config
        or OpenAICompatibleProvider("http://127.0.0.1", "synthetic", SecretStr("fixture"), 120),
        attempts,
    )
    old = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_candidates")]
    oldclaims = [tuple(r) for r in db.connection.execute("SELECT * FROM claims")]
    for attempt in attempts:
        rid = reserve_review(
            store, budget, attempt, "owner", {"days": 5, "driving": "NO"}, evaluation=True
        )
        result = run_review(store, provider, rid)
        assert (
            result["status"] == "COMPLETED" and result["accepted"] == 2 and result["pending"] == 1
        )
    assert old == [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_candidates")]
    assert oldclaims == [tuple(r) for r in db.connection.execute("SELECT * FROM claims")]
    budget.conclude_evaluation(True)
    preview = PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW")
    v = preview.open("partial", "五天，不自驾", "start-private")
    option = v["options"][0]["option_id"]
    v = preview.mutate(
        v["session_id"],
        {"action": "preview", "expected_revision": v["revision"], "option_id": option},
        "preview-first",
    )
    v = preview.mutate(
        v["session_id"],
        {"action": "confirm", "expected_revision": v["revision"], "option_id": option},
        "confirm-first",
    )
    return v, provider


def test_review_persists_final_provider_diagnostic(tmp_path, clock, monkeypatch):
    class Response:
        status = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return json.dumps({"model": "synthetic", "choices": [{
                "finish_reason": "stop", "message": {"content": '{"reviews":[]}'},
            }]}).encode()[:limit]

    class Opener:
        def open(self, request, timeout):
            assert timeout == 120
            return Response()

    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    with Database(tmp_path / "diagnostic.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        attempts = [add_source(store, f"diagnostic-{i}", Provider()) for i in range(2)]
        provider = OpenAICompatibleProvider("http://127.0.0.1", "synthetic", SecretStr("fixture"), 120)
        budget = BoundedBudget(store, GRANT)
        budget.grant("owner", "partial", provider, attempts)
        rid = reserve_review(store, budget, attempts[0], "owner", {}, evaluation=True)
        result = run_review(store, provider, rid)
        assert result["status"] == "COMPLETED"
        diagnostic = result["diagnostic"]
        assert diagnostic == provider.last_diagnostic.safe_dict()
        assert diagnostic["category"] == "SUCCESS" and diagnostic["finish_reason"] == "stop"
        assert diagnostic["elapsed_seconds"] is not None
        assert diagnostic["http_attempts"] == 1 and diagnostic["response_bytes"] > 0


class Reader:
    text_first = False

    def __init__(self):
        self.calls = []

    def connect(self):
        self.calls.append("connect")

    def search(self, query):
        self.calls.append("search")
        assert "5天" in query and "不自驾" in query and "甲路线" in query
        assert "公共交通" not in query
        return (Candidate("xhs:new-fixture", "合成青谷五天路线", "normal", True),)

    def detail(self, c, n):
        self.calls.append("detail")
        return DetailMaterial(
            c.source_id, c.title, BODY, "PARTIAL_TEXT", "2026-09-26T00:00:00+00:00"
        )

    def disable_text_first(self):
        raise AssertionError("NO_RETRY")


def dispatches(provider):
    def extract(store, attempt, gaps):
        a = store.db.connection.execute(
            "SELECT * FROM extraction_attempts WHERE attempt_id=?", (attempt,)
        ).fetchone()
        assert a["extraction_version"] == 3
        assert (
            store.db.connection.execute(
                "SELECT count(*) FROM source_contents WHERE content_id=?", (a["content_id"],)
            ).fetchone()[0]
            == 1
        )
        return ExtractionRecovery(store, EvidenceExtractor(provider)).run_reserved(
            attempt, research_gaps=gaps
        )

    def review(store, budget, attempt, scope, target):
        rid = reserve_review(store, budget, attempt, scope, target)
        return run_review(store, provider, rid)

    return extract, review


def test_normal_api_service_v3_review_adoption_and_restart(tmp_path, clock, monkeypatch):
    from travel_agent.main import create_app
    from travel_agent.preview.api import PreviewConfig

    path = tmp_path / "normal.sqlite3"
    with Database(path, clock=clock) as db:
        v, provider = setup(db)
    queued = []
    monkeypatch.setattr(
        "travel_agent.preview.worker.launch_job", lambda database, job: queued.append(job)
    )
    config = PreviewConfig(
        path, "owner", "CACHED_PRIVATE_PREVIEW", b"a" * 32, continuation=GRANT, live_ready=True
    )
    with TestClient(create_app(preview=config), base_url="http://127.0.0.1:8765") as client:
        client.get("/bootstrap?ticket=" + config.ticket)
        headers = {
            "Origin": "http://127.0.0.1:8765",
            "X-CSRF-Token": client.get("/api/v1/preview").json()["csrf_token"],
            "Idempotency-Key": "run-once-0001",
        }
        calls = len(provider.calls)
        for _ in range(3):
            assert client.get("/api/v1/preview/workbench").json()["enabled"]
        assert len(provider.calls) == calls
        body = {"session_id": v["session_id"], "expected_revision": v["revision"]}
        assert client.post("/api/v1/preview/jobs", json=body).status_code == 403
        first = client.post("/api/v1/preview/jobs", json=body, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "QUEUED"
        assert (
            client.post("/api/v1/preview/jobs", json=body, headers=headers).json() == first.json()
        )
        assert len(queued) == 1
        second = client.post(
            "/api/v1/preview/jobs",
            json=body,
            headers=headers | {"Idempotency-Key": "different-key"},
        )
        assert second.status_code != 200
        reader = Reader()
        extract, review = dispatches(provider)
        run_job(
            path,
            queued[0],
            reader=reader,
            provider=provider,
            extract_dispatch=extract,
            review_dispatch=review,
        )
        job = client.get("/api/v1/preview/jobs/" + queued[0]).json()
        assert reader.calls == ["connect", "search", "detail"]
        assert provider.calls[calls:] == [
            "select_evidence_references_v1",
            "review_evidence_context_v2",
        ]
        assert job["new_evidence_count"] == 2 and job["can_adopt"], job
        assert (
            client.get("/api/v1/preview").json()["session"]["confirmed_option_id"]
            == v["confirmed_option_id"]
        )
        # A preference edit while/after work never gets overwritten by old captured prefs.
        changed = client.post(
            "/api/v1/preview/sessions/" + v["session_id"],
            json={
                "action": "preferences",
                "expected_revision": v["revision"],
                "preferences": {"days": 6, "driving": "NO"},
            },
            headers=headers | {"Idempotency-Key": "change-prefs"},
        ).json()
        adopted = client.post(
            "/api/v1/preview/jobs/" + queued[0],
            json={"action": "adopt", "expected_revision": changed["revision"]},
            headers=headers | {"Idempotency-Key": "adopt-once"},
        ).json()
        assert adopted["preferences"]["days"] == 6 and adopted["preferences"]["driving"] == "NO"
        assert adopted["evidence_count"] > v["evidence_count"]
        rows = [e for o in adopted["options"] for e in o["evidence"]] + adopted["other_clues"]
        assert any(e["review_status"] == "MODEL_CONTEXT_REVIEWED" for e in rows)
        assert all(e["conditions"] and e["locator"] for e in rows)
        assert client.get("/api/v1/preview/workbench").json()["budget"]["remaining"] == dict(
            connect=0, search=0, detail=0, model=0
        )
    with Database(path, clock=clock) as db:
        assert PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW").latest() == adopted
        with pytest.raises(ValueError):
            BoundedBudget(EvidenceStore(db), GRANT).reserve("MODEL", "another-source")


@pytest.mark.parametrize("canceled", [True, False])
def test_cancel_and_restart_never_redispatch(tmp_path, clock, canceled):
    path = tmp_path / "stopped.sqlite3"
    with Database(path, clock=clock) as db:
        v, provider = setup(db)
        s = JobService(db, "owner", "CACHED_PRIVATE_PREVIEW", GRANT)
        job = s.create(v["session_id"], v["revision"], None, "cancel-one", ready=True)
        if canceled:
            s.cancel(job["job_id"])
        else:
            s.reconcile_restart()
        counts = BoundedBudget(EvidenceStore(db), GRANT).summary()
    reader = Reader()
    run_job(path, job["job_id"], reader=reader, provider=provider)
    assert not reader.calls
    with Database(path, clock=clock) as db:
        assert BoundedBudget(EvidenceStore(db), GRANT).summary() == counts
        assert PreviewService(db, "owner", "CACHED_PRIVATE_PREVIEW").latest() == v


def test_review_failure_no_work_fallback_and_no_second_claim(tmp_path, clock):
    with Database(tmp_path / "failed.sqlite3", clock=clock) as db:
        _, provider = setup(db)
        store = EvidenceStore(db)
        # Evaluation records are immutable one-shot even when caller tries another key.
        attempt = db.connection.execute(
            "SELECT attempt_id FROM context_review_runs LIMIT 1"
        ).fetchone()[0]
        budget = BoundedBudget(store, GRANT)
        with pytest.raises(ValueError):
            reserve_review(store, budget, attempt, "owner", {}, evaluation=True)
        rid = db.connection.execute("SELECT review_id FROM context_review_runs LIMIT 1").fetchone()[
            0
        ]
        calls = len(provider.calls)
        with pytest.raises(ValueError):
            run_review(store, provider, rid)
        assert len(provider.calls) == calls


def test_cancel_after_extraction_keeps_raw_and_skips_review(tmp_path, clock):
    path = tmp_path / "cancel-after.sqlite3"
    with Database(path, clock=clock) as db:
        v, provider = setup(db)
        job = JobService(db, "owner", "CACHED_PRIVATE_PREVIEW", GRANT).create(
            v["session_id"], v["revision"], None, "start-cancel-after", ready=True
        )
    extract, review = dispatches(provider)

    def cancel(store, attempt, gaps):
        out = extract(store, attempt, gaps)
        JobService(store.db, "owner", "CACHED_PRIVATE_PREVIEW", GRANT).cancel(job["job_id"])
        return out

    before = len(provider.calls)
    run_job(
        path,
        job["job_id"],
        reader=Reader(),
        provider=provider,
        extract_dispatch=cancel,
        review_dispatch=review,
    )
    assert provider.calls[before:] == ["select_evidence_references_v1"]
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        assert store.contents.load("xhs:new-fixture", "owner")
        assert BoundedBudget(store, GRANT).summary()["used"]["model"] == 3
        assert (
            JobService(db, "owner", "CACHED_PRIVATE_PREVIEW", GRANT).get(job["job_id"])["status"]
            == "CANCELED"
        )


def test_review_supervision_uses_same_deadline_and_keeps_consumed_permit(tmp_path, clock):
    from travel_agent.research.retry import supervise_reserved

    path = tmp_path / "deadline.sqlite3"
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        fake = Provider()
        attempts = [add_source(store, "timeout-" + str(i), fake) for i in range(2)]
        provider = OpenAICompatibleProvider(
            "http://127.0.0.1", "synthetic", SecretStr("fixture"), 120
        )
        budget = BoundedBudget(store, GRANT)
        budget.grant("owner", "partial", provider, attempts)
        rid = reserve_review(store, budget, attempts[0], "owner", {}, evaluation=True)
    result = supervise_reserved(
        path,
        rid,
        provider=provider,
        deadline=0.1,
        command=[sys.executable, "-c", "import time; time.sleep(2)"],
        context_review=True,
    )
    assert (
        result["status"] == "INTERRUPTED"
        and result["deadline_reached"]
        and result["owned_worker_exited"]
    )
    with Database(path, clock=clock) as db:
        assert BoundedBudget(EvidenceStore(db), GRANT).summary()["used"]["model"] == 1
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
