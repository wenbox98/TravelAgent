"""Failure durability, real loopback HTTP, and independent model-only recovery."""

from asyncio import CancelledError
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.domain.source_policy import private_policy
from travel_agent.persistence.database import Database
from travel_agent.providers.diagnostics import Diagnostic
from travel_agent.providers.llm import LLMError
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import Candidate, ResearchBudget, ResearchRequest
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.retry import retry_saved
from travel_agent.research.service import ResearchService
from travel_agent.research.store import EvidenceStore
from test_private_source_content import FixtureProvider, material


class Timeout(FixtureProvider):
    def structured(self, *args):
        self.calls += 1
        raise LLMError(diagnostic=Diagnostic(stage="TRANSPORT", category="TIMEOUT", http_attempts=1))


def setup(store, clock, provider=None, source="xhs:synthetic-a"):
    policy = private_policy("owner", now=clock())
    run = store.begin("recovery", 0, ResearchRequest(destination="synthetic-region").to_dict(), "owner")
    store.register_policy(run, 0, policy)
    note = material(clock, source=source)
    store.reserve_operation(run, 0, "DETAIL", source, 3)
    content_id = store.save_source(run, 0, note, policy, "synthetic-region")
    return policy, dict(run_id=run, revision=0, content_id=content_id, account_scope="owner",
                       policy=policy, batch_id="fixed-batch", max_attempts=4)


def test_failed_source_survives_process_exit_real_http_retry_and_no_version_duplication(clock, tmp_path):
    path = tmp_path / "cache.sqlite3"
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        policy, kwargs = setup(store, clock)
        result = ExtractionRecovery(store, EvidenceExtractor(Timeout(), clock=clock)).execute(**kwargs)
        assert result["status"] == "FAILED" and result["diagnostic"]["category"] == "TIMEOUT"
        assert not store.lookup("recovery", "synthetic-region", "owner")
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        before = store.contents.load("xhs:synthetic-a", "owner")
        digest = sha256(json.dumps(before, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, str(root / "tests/helpers/recovery_http_probe.py"),
                            str(path), result["attempt_id"]], cwd=root, capture_output=True, text=True, timeout=15)
    assert child.returncode == 0, child.stdout + child.stderr
    restored = json.loads(child.stdout)
    assert restored["status"] == "SUCCEEDED", restored
    assert restored["content_unchanged"] and restored["digest"] == digest
    assert restored["versions"] == 1 and restored["blocks"] == 5 and restored["body_present"]
    assert restored["http_requests"] == 1 and restored["no_browser_modules"]
    assert restored["xhs_calls"] == {"connect": 0, "search": 0, "detail": 0}
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        provider = FixtureProvider()
        cached = retry_saved(store, EvidenceExtractor(provider), attempt_id=result["attempt_id"], fix_commit="a" * 40)
        assert cached["cache_hit"] and provider.calls == 0
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 4
        assert db.connection.execute("SELECT count(*) FROM extraction_attempts").fetchone()[0] == 2


def test_retry_budget_persists_and_all_batch_sources_share_one_retry(clock, tmp_path):
    path = tmp_path / "cache.sqlite3"
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        _, kwargs = setup(store, clock)
        first = ExtractionRecovery(store, EvidenceExtractor(Timeout(), clock=clock)).execute(**kwargs)
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        provider = Timeout()
        second = retry_saved(store, EvidenceExtractor(provider, clock=clock), attempt_id=first["attempt_id"], fix_commit="b" * 40)
        assert second["status"] == "FAILED" and provider.calls == 1
        with pytest.raises(ValueError, match="BUDGET_OR_RETRY_DENIED"):
            retry_saved(store, EvidenceExtractor(provider, clock=clock), attempt_id=first["attempt_id"], fix_commit="c" * 40)
        _, kwargs = setup(store, clock, source="xhs:synthetic-b")
        second_source = ExtractionRecovery(store, EvidenceExtractor(provider, clock=clock)).execute(**kwargs)
        with pytest.raises(ValueError, match="BUDGET_OR_RETRY_DENIED"):
            retry_saved(store, EvidenceExtractor(provider, clock=clock), attempt_id=second_source["attempt_id"], fix_commit="d" * 40)
        assert provider.calls == 2


@pytest.mark.parametrize("fault", ["grounding", "cancel", "stale"])
def test_failed_or_late_extraction_never_saves_claims_and_retains_body(clock, fault):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        _, kwargs = setup(store, clock)
        class Fault(FixtureProvider):
            def structured(self, *args):
                if fault == "cancel":
                    raise CancelledError()
                rows = super().structured(*args)
                if fault == "grounding":
                    rows["claims"][0]["quote"] = "不存在的引用"
                else:
                    store.begin("recovery", 1, ResearchRequest(destination="synthetic-region", days=5).to_dict(), "owner")
                return rows
        runner = ExtractionRecovery(store, EvidenceExtractor(Fault(), clock=clock))
        if fault == "cancel":
            with pytest.raises(CancelledError):
                runner.execute(**kwargs)
        else:
            result = runner.execute(**kwargs)
            assert result["status"] == ("FAILED" if fault == "grounding" else "OBSOLETE")
            if fault == "grounding":
                assert result["diagnostic"]["category"] == "UNGROUNDED"
        assert store.contents.load("xhs:synthetic-a", "owner")
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0


@pytest.mark.parametrize("fault", ["source_save", "report_save", "model_timeout"])
def test_service_failure_boundaries_and_safe_report(clock, monkeypatch, fault):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        note = material(clock)
        class Reader:
            text_first = False
            def connect(self): pass
            def search(self, _): return (Candidate(note.source_id, "synthetic-region 路线", "normal", True),)
            def detail(self, *args): return note
            def disable_text_first(self): raise AssertionError()
        provider = Timeout() if fault == "model_timeout" else FixtureProvider()
        if fault == "source_save":
            monkeypatch.setattr(store.contents, "put", lambda *args: (_ for _ in ()).throw(OSError("SECRET_SENTINEL")))
        if fault == "report_save":
            monkeypatch.setattr(store, "finish", lambda *args: (_ for _ in ()).throw(OSError("SECRET_SENTINEL")))
        service = ResearchService(store, Reader(), EvidenceExtractor(provider, clock=clock), private_policy("owner", now=clock()))
        def run():
            return service.run(ResearchRequest(destination="synthetic-region"), research_id="service", revision=0,
                               account_scope="owner", budget=ResearchBudget(1, 1))
        if fault == "report_save":
            with pytest.raises(OSError):
                run()
        else:
            report = run().safe_summary()
            assert "SECRET_SENTINEL" not in json.dumps(report)
            assert report["locator_coverage"] is None
            assert report["extraction_diagnostics"][0]["category"] == ("TIMEOUT" if fault == "model_timeout" else "SOURCE_SAVE_FAILED")
        assert provider.calls == (0 if fault == "source_save" else 1)
        assert db.connection.execute("SELECT count(*) FROM source_contents").fetchone()[0] == (0 if fault == "source_save" else 1)
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == (4 if fault == "report_save" else 0)
