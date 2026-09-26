"""T06.3: authored fixtures, strict quotes, explicit simulated Work review, no live data."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.domain.source_policy import private_policy
from travel_agent.persistence.database import Database
from travel_agent.research.canonical import canonicalize
from travel_agent.research.candidate_review import review_candidates
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.grounding import REVIEW_DIMENSIONS, check_grounding
from travel_agent.research.models import DetailMaterial, ResearchRequest, ResearchReport
from travel_agent.research.model_input import outbound_blocks
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.store import EvidenceStore
from test_extraction_recovery import Timeout

BODY = "合成路线连接青谷和镜湖。\n作者在湖边散步。\n作者说明不能一天走完。\n我自驾用了五天。\n如果下雨就取消步行。"


def candidate(text, index=0, topic="ROUTE", conditions=()):
    return {"claim": text, "quote": text, "source_block_ids": [index], "topic": topic,
            "kind": "AUTHOR_OPINION", "confidence": "MEDIUM", "applicable_conditions": list(conditions),
            "extraction_basis": "自编离线材料"}


def accept(**extra):
    return {"action": "ACCEPT", "reason_code": "WORK_CONTEXT_VERIFIED",
            "dimension_checks": {k: True for k in REVIEW_DIMENSIONS}, **extra}


class Provider:
    is_external = True
    is_mock = False
    def __init__(self, rows): self.rows, self.calls = rows, 0
    def structured(self, *args):
        self.calls += 1
        return {"claims": deepcopy(self.rows)}


def prepare(db, clock, rows, body=BODY):
    store = EvidenceStore(db)
    policy = private_policy("owner", now=clock())
    run = store.begin("partial", 0, ResearchRequest(destination="合成青谷").to_dict(), "owner")
    store.register_policy(run, 0, policy)
    store.reserve_operation(run, 0, "DETAIL", "xhs:synthetic-t063", 1)
    content_id = store.save_source(run, 0, DetailMaterial("xhs:synthetic-t063", "自编样本", body,
        "PARTIAL_TEXT", clock().isoformat()), policy, "合成青谷")
    provider = Provider(rows)
    runner = ExtractionRecovery(store, EvidenceExtractor(provider, clock=clock, protocol_version=2))
    kwargs = dict(run_id=run, revision=0, content_id=content_id, account_scope="owner", policy=policy,
                  batch_id="fixed-t063", max_attempts=2)
    return store, runner, provider, kwargs


@pytest.mark.parametrize("change,reason", [
    ({"claim": "不存在"}, "CLAIM_QUOTE_MISMATCH"),
    ({"quote": "不存在", "claim": "不存在"}, "QUOTE_NOT_IN_CITED_BLOCK"),
    ({"source_block_ids": [80]}, "BLOCK_ID_OUT_OF_RANGE"),
    ({"source_block_ids": [0, 1]}, "UNSUPPORTED_EXTRA_BLOCK_REFERENCE"),
    ({"source_block_ids": [0, 0]}, "DUPLICATE_BLOCK_REFERENCE"),
    ({"applicable_conditions": [{"text": "晴天", "quote": "雨天", "source_block_id": 0}]}, "CONDITION_QUOTE_MISMATCH"),
    ({"applicable_conditions": [{"text": "晴天", "quote": "晴天", "source_block_id": 0}]}, "CONDITION_NOT_IN_CITED_BLOCK"),
    ({"quote": "见图", "claim": "见图"}, "IMAGE_INFORMATION_REQUIRED"),
])
def test_exact_reason(change, reason):
    row = candidate(BODY.splitlines()[0]) | change
    result = check_grounding(row, canonicalize(BODY).blocks)
    assert not result.passed and result.reason_code == reason
    assert set(result.safe_dict(0)) == {"candidate_index", "passed", "reason_code", "block_ids", "rule_version"}


def test_normalization_coordinates_and_filtered_ids():
    body = "  我\t自驾用了５天。\r\n微信：不发送。\r\n不能一天走完。 Cafe\u0301！  "
    view = canonicalize(body)
    assert [b.block_index for b in outbound_blocks(view.blocks)] == [0, 2]
    assert check_grounding(candidate(view.blocks[1].text, 1), view.blocks, {0, 2}).reason_code == "UNSENT_BLOCK_REFERENCED"
    for b in view.blocks:
        assert b.text == b.normalized_text == view.text[b.start:b.end]
    assert check_grounding(candidate("我 自驾用了５天。"), view.blocks).passed
    assert not check_grounding(candidate("我 自驾用了5天。"), view.blocks).passed
    assert not check_grounding(candidate("我 自驾用了５天!"), view.blocks).passed


def test_two_independent_accepted_one_rejected_partial_restart_zero_network(clock, tmp_path):
    path = tmp_path / "partial.sqlite3"
    rows = [candidate(BODY.splitlines()[0]), candidate(BODY.splitlines()[1], 1, "EXPERIENCE"), candidate("不存在")]
    with Database(path, clock=clock) as db:
        store, runner, provider, kwargs = prepare(db, clock, rows)
        result = runner.execute(**kwargs)
        assert result["status"] == "PENDING_REVIEW" and not store.lookup("partial", "合成青谷", "owner")
        reviewed = review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0: accept(), 1: accept()})
        assert reviewed["status"] == "PARTIAL_SUCCESS"
        assert reviewed["counts"] == dict(generated_candidates=3, locator_passed_candidates=2, rejected_candidates=1,
                                          context_review_pending=0, persisted_evidence=2)
        assert len(store.lookup("partial", "合成青谷", "owner")) == 1
        assert reviewed["summary"]["completeness"] == ["PARTIAL_TEXT"]
        assert reviewed["summary"]["extraction_results"][0]["status"] == "PARTIAL_SUCCESS"
        assert runner.execute(**kwargs)["cache_hit"] and provider.calls == 1
        again = review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0: accept(), 1: accept()})
        assert again["counts"]["persisted_evidence"] == 2
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, str(root / "tools/private_cache_probe.py"), "--database", str(path),
        "--account-scope", "owner", "--research-id", "partial"], capture_output=True, text=True, cwd=root, timeout=15)
    restored = json.loads(child.stdout)
    assert child.returncode == 0 and restored["status"] == "PASS", restored
    assert restored["model_calls"] == restored["browser_sessions"] == 0
    assert all(restored["checks"].values()) and restored["summary"]["evidence_count"] == 2
    assert {"DAYS_FIT", "NON_SELF_DRIVE"} <= {r["gap_id"] for r in restored["incremental"]["gaps"]}


def test_invalid_condition_is_whole_candidate_rejection_and_dependency_is_held(clock):
    bad = candidate(BODY.splitlines()[0], conditions=[{"text": "晴天", "quote": "下雨", "source_block_id": 4}])
    bad["source_block_ids"] = [0, 4]
    rows = [bad, candidate(BODY.splitlines()[4], 4, "TRADEOFF"), candidate(BODY.splitlines()[1], 1, "EXPERIENCE")]
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, rows)
        result = runner.execute(**kwargs)
        reviewed = review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={2: accept()})
        assert reviewed["counts"]["persisted_evidence"] == 1 and reviewed["counts"]["context_review_pending"] == 1
        with pytest.raises(ValueError, match="DEPENDENCY_UNRESOLVED"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={1: accept()})
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 1
        with pytest.raises(ValueError, match="REJECTED_LOCATOR"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0: accept()})


def test_negation_and_transport_cannot_be_changed_and_empty_is_not_pass(clock):
    rows = [candidate("一天走完", 2, "DURATION"), candidate("不自驾五天可行", 3, "TRANSPORT")]
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, rows)
        result = runner.execute(**kwargs)
        assert result["status"] == "NO_ACCEPTED_EVIDENCE"
        assert result["candidate_checks"][0]["passed"] is True
        assert result["candidate_checks"][0]["context_reason"] == "CONTEXT_NEGATION_OMITTED"
        assert result["candidate_checks"][1]["reason_code"] == "QUOTE_NOT_IN_CITED_BLOCK"
        report = ResearchReport("partial", 0, kwargs["run_id"], ResearchRequest(), (), (), "SOURCE_UNAVAILABLE", {}, 0).safe_summary()
        assert report["locator_coverage"] is None and report["unsupported_published_claims"] is None
        assert not store.lookup("partial", "合成青谷", "owner")


def test_context_anchor_and_atomic_lineage_report_failure(clock, monkeypatch):
    rows = [candidate("用了五天", 3, "DURATION")]
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, rows)
        result = runner.execute(**kwargs)
        with pytest.raises(ValueError, match="CONTEXT_REVIEW_INCOMPLETE"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0: {"action":"ACCEPT","reason_code":"WORK_CONTEXT_VERIFIED"}})
        decision = accept(context_conditions=[{"text":"我自驾用了五天", "quote":"我自驾用了五天", "source_block_id":3}])
        monkeypatch.setattr(store, "finish", lambda *args: (_ for _ in ()).throw(OSError("PRIVATE_REPORT_SENTINEL")))
        with pytest.raises(OSError):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0:decision})
        row = db.connection.execute("SELECT claim_id FROM extraction_candidates").fetchone()
        assert row[0] and db.connection.execute("SELECT status FROM extraction_attempts").fetchone()[0] == "SUCCEEDED"
        bundle, = store.lookup("partial", "合成青谷", "owner")
        assert bundle["claim_metadata"][row[0]]["applicable_conditions"] == ["我自驾用了五天"]


def test_sensitive_response_blocks_whole_batch_and_never_retains_raw(clock):
    rows = [candidate(BODY.splitlines()[0]), candidate("Authorization: Bearer SECRET_AUTHORIZATION")]
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, rows)
        result = runner.execute(**kwargs)
        assert result["status"] == "FAILED" and result["diagnostic"]["stage"] == "POLICY"
        assert "SECRET_AUTHORIZATION" not in json.dumps(result["diagnostic"])
        assert "SECRET_AUTHORIZATION" not in "\n".join(db.connection.iterdump())
        assert db.connection.execute("SELECT count(*) FROM extraction_candidates").fetchone()[0] == 0
        assert result["counts"]["rejected_candidates"] == 2


def test_version_new_run_and_new_batch_do_not_reset_retry_budget(clock, monkeypatch):
    with Database(Path(":memory:"), clock=clock) as db:
        store, _, _, kwargs = prepare(db, clock, [])
        failing = ExtractionRecovery(store, EvidenceExtractor(Timeout(), clock=clock, protocol_version=2))
        first = failing.execute(**kwargs)
        monkeypatch.setattr("travel_agent.research.recovery.EXTRACTION_VERSION", 3)
        second = failing.execute(**kwargs, retry_fix_commit="a" * 40)
        assert first["status"] == second["status"] == "FAILED"
        assert db.connection.execute("SELECT attempt_number FROM extraction_attempts ORDER BY rowid DESC LIMIT 1").fetchone()[0] == 2
        run = store.begin("partial", 0, ResearchRequest(destination="合成青谷").to_dict(), "owner")
        with pytest.raises(ValueError, match="BUDGET_OR_RETRY_DENIED"):
            failing.execute(**(kwargs | {"run_id":run}), retry_fix_commit="b" * 40)
        with pytest.raises(ValueError, match="CONTENT_BATCH_IMMUTABLE"):
            failing.execute(**(kwargs | {"run_id":run,"batch_id":"new-batch"}))


def test_stale_scope_and_cache_clear_cover_private_audit(clock, tmp_path):
    profile = tmp_path / "owned-profile"
    profile.mkdir()
    (profile / "marker").write_text("synthetic-profile")
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, [candidate(BODY.splitlines()[0])])
        result = runner.execute(**kwargs)
        with pytest.raises(ValueError, match="SCOPE_REVISION"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="other", decisions={0:accept()})
        store.begin("partial", 1, ResearchRequest(destination="合成青谷", days=5).to_dict(), "owner")
        with pytest.raises(ValueError, match="SCOPE_REVISION"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={0:accept()})
        store.clear_research_cache("owner")
        assert db.connection.execute("SELECT count(*) FROM extraction_candidates").fetchone()[0] == 0
        assert (profile / "marker").read_text() == "synthetic-profile"


def test_v6_failed_history_survives_migration_and_retry_is_number_two(clock, tmp_path):
    path = tmp_path / "v6.sqlite3"
    with Database(path, clock=clock, target_version=6) as db:
        store, _, _, kwargs = prepare(db, clock, [])
        db.connection.execute("INSERT INTO extraction_batches VALUES('fixed-t063','owner',2)")
        original = {"generated_claims": 12, "rejected_claims": 1}
        db.connection.execute("INSERT INTO extraction_attempts VALUES(?,?,?,?,?,1,1,1,'FAILED',?,NULL,?,?)",
            ("original", "fixed-t063", kwargs["run_id"], 0, kwargs["content_id"], json.dumps(original), db.stamp(), db.stamp()))
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        old = db.connection.execute("SELECT * FROM extraction_attempts WHERE attempt_id='original'").fetchone()
        assert old["status"] == "FAILED" and json.loads(old["diagnostic_json"]) == original
        assert old["content_hash"] == store.contents.load("xhs:synthetic-t063", "owner")[0]["content_hash"]
        retry = ExtractionRecovery(store, EvidenceExtractor(Provider([candidate(BODY.splitlines()[0])]), clock=clock, protocol_version=2))
        result = retry.execute(**kwargs, retry_fix_commit="a" * 40)
        assert result["status"] == "PENDING_REVIEW"
        assert db.connection.execute("SELECT attempt_number,extraction_version FROM extraction_attempts WHERE attempt_id=?",
                                     (result["attempt_id"],)).fetchone()[:] == (2, 2)
        assert db.connection.execute("SELECT status FROM extraction_attempts WHERE attempt_id='original'").fetchone()[0] == "FAILED"


def test_same_review_rejection_dependency_and_mid_commit_rollback(clock, monkeypatch):
    condition = {"text": BODY.splitlines()[4], "quote": BODY.splitlines()[4], "source_block_id": 4}
    first = candidate(BODY.splitlines()[0], conditions=[condition])
    first["source_block_ids"].append(4)
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kwargs = prepare(db, clock, [first, candidate(BODY.splitlines()[4], 4)])
        result = runner.execute(**kwargs)
        decisions = {0: {"action": "REJECT", "reason_code": "CONTEXT_UNCERTAIN"}, 1: accept()}
        with pytest.raises(ValueError, match="DEPENDENCY_UNRESOLVED"):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions=decisions)
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        original = store.save_evidence
        def fail_after_save(*args, **kw):
            original(*args, **kw)
            raise OSError("synthetic crash before candidate status")
        monkeypatch.setattr(store, "save_evidence", fail_after_save)
        with pytest.raises(OSError):
            review_candidates(store, attempt_id=result["attempt_id"], account_scope="owner", decisions={1: accept()})
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert runner.outcome(result["attempt_id"])["counts"]["context_review_pending"] == 2


def test_review_cli_works_without_provider_or_browser(clock, tmp_path):
    path = tmp_path / "cli.sqlite3"
    with Database(path, clock=clock) as db:
        _, runner, _, kwargs = prepare(db, clock, [candidate(BODY.splitlines()[0])])
        result = runner.execute(**kwargs)
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, str(root / "scripts/retry_extraction.py"), "--review-stdin",
        "--database", str(path), "--attempt-id", result["attempt_id"], "--account-scope", "owner"],
        input=json.dumps({0: accept()}), capture_output=True, text=True, cwd=root, timeout=15)
    safe = json.loads(child.stdout)
    assert child.returncode == 0 and safe["status"] == "SUCCEEDED", safe
    assert safe["network_guard"] == "DENY_ALL" and safe["browser_modules_absent"]
    assert BODY.splitlines()[0] not in child.stdout
