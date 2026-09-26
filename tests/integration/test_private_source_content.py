"""P01–P14 use fabricated note text; no real XHS content or model access."""

from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.domain.models import SourcePolicy
from travel_agent.domain.source_policy import private_policy
from travel_agent.persistence.database import Database
from travel_agent.research.content_store import audit_grounding
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import Candidate, DetailMaterial, ResearchBudget, ResearchRequest
from travel_agent.research.service import ResearchService
from travel_agent.research.store import EvidenceStore


class FixtureProvider:
    """Fake transport exercises the external-provider permission path with synthetic text."""
    is_external = True
    is_mock = False
    def __init__(self, malformed=False):
        self.calls = 0
        self.malformed = malformed
    def structured(self, task, payload, schema):
        self.calls += 1
        if self.malformed:
            return {"claims": "malformed"}
        return {"claims": [
            {"topic": topic, "kind": "AUTHOR_OPINION", "claim": b["text"], "quote": b["text"],
             "source_block_ids": [b["block_index"]], "confidence": "MEDIUM",
             "applicable_conditions": [], "extraction_basis": "离线逐字夹具"}
            for topic, b in zip(("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT"), payload["blocks"])
        ]}


def review_fixture(store, outcome):
    """Explicit simulated Work review of self-authored full-block fixtures only."""
    from travel_agent.research.candidate_review import review_candidates
    from travel_agent.research.grounding import REVIEW_DIMENSIONS
    return review_candidates(store, attempt_id=outcome["attempt_id"], account_scope="owner", decisions={
        c["candidate_index"]: {"action": "ACCEPT", "reason_code": "WORK_CONTEXT_VERIFIED",
            "dimension_checks": {key: True for key in REVIEW_DIMENSIONS}, "dependency_resolution": "INDEPENDENT"}
        for c in outcome["candidate_checks"] if c["context_status"] == "PENDING"})


def material(clock, name="合成青岭路线", source="xhs:synthetic-a", **changes):
    body = (f"{name}：连接虚构山谷与湖泊。\n{name}：体验湖畔步行。\n"
            f"{name}：作者自驾用了五天。\n{name}：作者需要提前安排包车。\n旅行日期：2026-09-01")
    return replace(DetailMaterial(source, name, body, "FULL_TEXT", clock().isoformat(),
                                  clock().isoformat()), **changes)


def write(store, clock, note=None, *, policy=None, reserve=True, provider=None, revision=0):
    note = note or material(clock)
    policy = policy or private_policy("owner", now=clock())
    run = store.begin("private", revision, ResearchRequest(destination="synthetic-region").to_dict(), "owner")
    store.register_policy(run, revision, policy)
    if reserve:
        assert store.reserve_operation(run, revision, "DETAIL", note.source_id, 3)
    result = EvidenceExtractor(provider or FixtureProvider(), clock=clock).extract(
        source_id=note.source_id, source_title=note.title, body=note.body, dom_body=note.dom_body,
        completeness=note.completeness, fetched_at=note.fetched_at, source_published_at=note.published_at,
        destination="synthetic-region", policy=policy, image_count=note.image_count)
    store.save_detail(run, revision, note, result, policy, {"identity_match": note.identity_match})
    return run, result, policy


def test_p01_p10_p11_raw_normalized_blocks_and_grounding(clock, tmp_path):
    with Database(tmp_path / "private.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        note = material(clock, image_count=3)
        run, result, policy = write(store, clock, note)
        assert policy["basis"] == "UNKNOWN" and policy["allow_export"] is False
        content, = store.contents.load(note.source_id, "owner")
        assert content["raw_text"] == note.body
        assert content["normalized_text"] == result.canonical.text
        assert len(content["body_blocks"]) == 5 and content["image_count"] == 3
        assert content["image_status"] == "IMAGE_NOT_ANALYZED"
        assert not any("url" in key or key in {"images", "image_bytes"} for key in content)
        assert audit_grounding(result.bundle, (content,)) == {
            "checked": 4, "unsupported": 0, "locator_coverage": 1.0}
        assert store.contents.load(note.source_id, "other") == ()
        assert store.lookup("private", "synthetic-region", "owner")
        store.finish(run, 0, [], {})


@pytest.mark.parametrize("reserve,changes", [(False, {}), (True, {"identity_match": False}),
                                             (True, {"completeness": "SUMMARY_ONLY"})])
def test_p02_only_successful_researched_details_can_be_retained(clock, reserve, changes):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        with pytest.raises(ValueError):
            write(store, clock, material(clock, **changes), reserve=reserve)
        assert db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0] == 0
        assert db.connection.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


@pytest.mark.parametrize("secret", ["Cookie: SECRET_COOKIE", "Authorization: Bearer SECRET_AUTHORIZATION",
    "session_secret=SECRET_SESSION", "qr_code=SECRET_QR", "https://example.invalid/?xsec_token=SECRET_XSEC",
    "data:image/png;base64,SECRET_QR", "api_key=SECRET_API", "session_id=SECRET_SESSION"])
def test_p03_secret_rejected_before_model_and_atomic_db_write(clock, secret):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        provider = FixtureProvider()
        with pytest.raises(ValueError):
            write(store, clock, material(clock, body=secret), provider=provider)
        assert provider.calls == 0
        assert secret not in "\n".join(db.connection.iterdump())
        assert db.connection.execute("SELECT count(*) FROM sources").fetchone()[0] == 0


def test_p06_p07_versions_deduplicate_without_overwriting_old_body_or_evidence(clock):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        run, first, _ = write(store, clock)
        store.finish(run, 0, [], {})
        store.db.connection.execute("DELETE FROM research_ops")  # Independent explicit re-read fixture.
        run, _, _ = write(store, clock, material(clock, fetched_at=(clock() + timedelta(hours=1)).isoformat()))
        assert len(store.contents.load(first.bundle["source_id"], "owner")) == 1
        store.finish(run, 0, [], {})
        store.db.connection.execute("DELETE FROM research_ops")
        changed = material(clock, body=material(clock).body.replace("五天", "七天"))
        write(store, clock, changed)
        versions = store.contents.load(first.bundle["source_id"], "owner")
        assert len(versions) == 2 and versions[0]["content_hash"] != versions[1]["content_hash"]
        assert "五天" in versions[0]["raw_text"] and "七天" in versions[1]["raw_text"]
        assert store.lookup("private", "synthetic-region", "owner")[0].to_dict() == first.bundle.to_dict()
        assert audit_grounding(first.bundle, versions)["unsupported"] == 0


@pytest.mark.parametrize("retention,days,retained", [("7_DAYS", 8, False), ("30_DAYS", 31, False),
                                                     ("PERSISTENT", 1000, True), ("EPHEMERAL", 0, False)])
def test_retention_is_enforced_and_expired_blocks_are_removed(clock, retention, days, retained):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        write(store, clock, policy=private_policy("owner", retention=retention, now=clock()))
        db.clock = lambda: clock() + timedelta(days=days)
        assert bool(store.contents.load("xhs:synthetic-a", "owner")) is retained
        assert bool(db.connection.execute("SELECT count(*) FROM source_body_blocks").fetchone()[0]) is retained


def test_private_policy_cannot_cross_scope_or_disguise_as_author_permission(clock):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        run = store.begin("private", 0, {}, "other")
        with pytest.raises(PermissionError):
            store.register_policy(run, 0, private_policy("owner", now=clock()))
        policy = private_policy("owner", now=clock()).to_dict()
        for changes in ({"allow_export": True}, {"allow_embed": True}, {"local_account_scope": ""}):
            with pytest.raises(Exception):
                SourcePolicy(policy | changes)
        policy.pop("usage_mode")
        with pytest.raises(Exception):
            SourcePolicy(policy)  # UNKNOWN without explicit private mode still fails closed.


def test_p08_p09_clear_cache_is_independent_from_real_profile_lifecycle(clock, tmp_path):
    from xhs_sidecar.profile import ProfileStore
    from xhs_sidecar.browser import BrowserManager, FakeBrowserBackend
    from xhs_sidecar.login import LoginLifecycle
    project = tmp_path / "project"
    project.mkdir()
    profile = ProfileStore(project, root=tmp_path / "owned-profile")
    path = profile.prepare()
    (path / "synthetic-state").write_text("keep", encoding="utf-8")
    with Database(project / "cache.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        run, result, _ = write(store, clock)
        store.finish(run, 0, [], {})
        assert store.clear_research_cache("owner")["source_contents"] == 1
        for table in ("source_contents", "source_body_blocks", "sources", "claims", "research_runs",
                      "research_reports", "research_run_contents"):
            assert db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert store.contents.load(result.bundle["source_id"], "owner") == ()
    browser = BrowserManager(FakeBrowserBackend())
    lifecycle = LoginLifecycle(browser, profile)
    assert lifecycle.status().status == "SESSION_PRESENT_UNVERIFIED"
    assert (path / "synthetic-state").read_text() == "keep"
    lifecycle.shutdown()


def test_p13_malformed_schema_falls_back_without_claiming_live_model_pass(clock):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        _, result, _ = write(store, clock, provider=FixtureProvider(malformed=True))
        assert result.mode == "LOCAL_EXTRACTIVE"
        assert "LLM_UNAVAILABLE_OR_INVALID" in result.gaps
        assert audit_grounding(result.bundle, store.contents.load(result.bundle["source_id"], "owner"))["unsupported"] == 0


def test_p04_p05_p14_independent_process_restores_source_content_and_incremental(clock, tmp_path):
    database = tmp_path / "private.sqlite3"
    with Database(database, clock=clock) as db:
        store = EvidenceStore(db)
        policy = private_policy("owner", now=clock())
        notes = (material(clock), material(clock, name="虚构苍河路线", source="xhs:synthetic-b"))
        class Reader:
            text_first = False
            def connect(self): pass
            def search(self, query): return tuple(Candidate(n.source_id, "synthetic-region " + n.title, "normal", True) for n in notes)
            def detail(self, candidate, number): return next(n for n in notes if n.source_id == candidate.source_id)
            def disable_text_first(self): raise AssertionError("no fallback")
        request = ResearchRequest(destination="synthetic-region")
        service = ResearchService(store, Reader(), EvidenceExtractor(FixtureProvider(), clock=clock), policy,
                                  after_extraction=lambda outcome: review_fixture(store, outcome))
        first = service.run(request, research_id="private", revision=0, account_scope="owner", budget=ResearchBudget(1, 3))
        assert first.stop_reason == "EVIDENCE_SUFFICIENT", first.safe_summary()
        assert first.operations == {"search": 1, "detail": 2}  # Early stop before detail 3.
        class Never(Reader):
            def connect(self): raise AssertionError("cache must be before connect")
        cached = ResearchService(store, Never(), EvidenceExtractor(), policy).run(
            request, research_id="private", revision=0, account_scope="owner", budget=ResearchBudget(1, 3))
        assert cached.stop_reason == "EVIDENCE_SUFFICIENT" and cached.operations == {"search": 0, "detail": 0}
    project = Path(__file__).resolve().parents[2]
    output = subprocess.run([sys.executable, str(project / "tools/private_cache_probe.py"),
                             "--database", str(database), "--account-scope", "owner", "--research-id", "private"],
                            cwd=project, text=True, capture_output=True, timeout=30, check=False)
    assert output.returncode == 0, output.stdout + output.stderr
    result = json.loads(output.stdout)
    assert result["pid"] != os.getpid()
    assert result["status"] == "PASS" and all(result["checks"].values())
    assert result["source_content_count"] == 2 and result["calls"] == {"connect": 0, "search": 0, "detail": 0}


def test_p12_unsupported_model_claim_is_rejected(clock):
    class Hallucinating(FixtureProvider):
        def structured(self, task, payload, schema):
            result = super().structured(task, payload, schema)
            result["claims"][0].update(claim="正文没有的免费公交", quote="正文没有的免费公交")
            return result
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        _, result, _ = write(store, clock, provider=Hallucinating())
        assert result.rejected_claims == 1
        assert all("免费公交" not in c["text"] for c in result.bundle["claims"])


def test_policy_revocation_hides_content_without_touching_other_scope(clock):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        run, result, policy = write(store, clock)
        assert store.contents.load(result.bundle["source_id"], "owner")
        revoked = SourcePolicy(policy.to_dict() | {"version": 2, "allow_read": False})
        store.register_policy(run, 0, revoked)
        assert store.contents.load(result.bundle["source_id"], "owner") == ()
        assert store.lookup("private", "synthetic-region", "owner") == ()
