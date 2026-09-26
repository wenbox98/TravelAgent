"""Fixed authorization, restart-safe budgets and new-source deadline wiring; offline."""

import json
import sys
import pytest
from pydantic import SecretStr

from travel_agent.persistence.database import Database
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.continuation import CONTINUATION, ContinuationBudget
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import DetailMaterial, ResearchRequest
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.retry import authorize_extra, reserve_extra, supervise_continuation
from travel_agent.research.retry import supervise_reserved
from travel_agent.research.store import EvidenceStore
from test_candidate_grounding import prepare, candidate, Provider, BODY
from test_extraction_recovery import Timeout
from travel_agent.research.service import ResearchService
from travel_agent.research.models import Candidate, ResearchBudget
from travel_agent.research.candidate_review import review_candidates
from test_candidate_grounding import accept


def setup(db, clock):
    store, _, _, kwargs = prepare(db, clock, [])
    recovery = ExtractionRecovery(store, EvidenceExtractor(Timeout(), clock=clock))
    recovery.execute(**kwargs)
    failed = recovery.execute(**kwargs, retry_fix_commit="a" * 40)
    provider = OpenAICompatibleProvider("https://api.deepseek.com", "synthetic-model", SecretStr("synthetic-secret"),
                                        timeout=120, response_format="json_object")
    authorize_extra(store, base_attempt_id=failed["attempt_id"], fix_commit="b" * 40, provider=provider, deadline=180)
    reserve_extra(store, base_attempt_id=failed["attempt_id"], fix_commit="b" * 40, provider=provider, deadline=180)
    return store, kwargs, provider


def test_continuation_budgets_survive_restart_and_new_run(tmp_path, clock):
    path = tmp_path / "cache.sqlite3"
    with Database(path, clock=clock, target_version=8) as db:
        store, _, provider = setup(db, clock)
        before = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts")]
        grants = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_authorizations")]
    with Database(path, clock=clock) as db:
        budget = ContinuationBudget(EvidenceStore(db))
        budget.grant("owner", "partial", provider)
        budget.start()
        for kind, values in {"CONNECT":["one"], "SEARCH":["query"], "DETAIL":["a","b"], "MODEL":["a","b"]}.items():
            for value in values:
                budget.reserve(kind,value)
            with pytest.raises(ValueError, match="BUDGET_OR_DUPLICATE"):
                budget.reserve(kind,"extra")
        assert before == [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts")]
        assert grants == [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_authorizations")]
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        store.begin("changed-run-id",0,ResearchRequest().to_dict(),"owner")
        budget = ContinuationBudget(store)
        budget.grant("owner", "partial", provider)
        with pytest.raises(ValueError, match="NO_RETRY"):
            budget.start()
        assert set(budget.summary()["remaining"].values()) == {0}
        with pytest.raises(ValueError, match="IMMUTABLE"):
            budget.grant("owner", "changed-predecessor", provider)
        store.clear_research_cache("owner")
        assert set(budget.summary()["remaining"].values()) == {0}


def test_normal_source_reservation_uses_120_180_and_no_second_dispatch(tmp_path, clock, monkeypatch):
    with Database(tmp_path / "cache.sqlite3", clock=clock) as db:
        store, kw, provider = setup(db, clock)
        budget = ContinuationBudget(store)
        budget.grant("owner", "partial", provider)
        budget.start()
        run = store.begin(CONTINUATION,0,ResearchRequest(destination="合成青谷").to_dict(),"owner")
        policy = kw["policy"]
        store.register_policy(run,0,policy)
        budget.reserve("DETAIL","xhs:new-synthetic")
        store.reserve_operation(run,0,"DETAIL","xhs:new-synthetic",2)
        content = store.save_source(run,0,DetailMaterial("xhs:new-synthetic","合成新资料",BODY,"PARTIAL_TEXT",db.stamp()),policy,"合成青谷")
        observed = []
        def supervisor(path, attempt, *, provider, deadline, command, finish_report):
            assert provider.timeout == 120 and deadline == 180
            assert finish_report is False  # The active service owns its final report.
            assert "--continuation-worker" in command and "ROUTES,DURATION" in command
            ContinuationBudget(store).check_worker(attempt,provider)
            observed.append(attempt)
            fake = Provider([candidate(BODY.splitlines()[0])])
            return ExtractionRecovery(store,EvidenceExtractor(fake,clock=clock)).run_reserved(attempt)
        monkeypatch.setattr("travel_agent.research.retry.supervise_reserved",supervisor)
        def dispatch(attempt,gaps):
            return supervise_continuation(store,attempt,gaps,provider)
        recovery = ExtractionRecovery(store,EvidenceExtractor(provider))
        args = dict(run_id=run,revision=0,content_id=content,account_scope="owner",policy=policy,
                    batch_id=CONTINUATION,max_attempts=2,research_gaps=("ROUTES","DURATION"),dispatch=dispatch)
        result = recovery.execute(**args)
        assert result["status"] == "PENDING_REVIEW" and len(observed) == 1
        assert recovery.execute(**args)["cache_hit"] and len(observed) == 1
        assert budget.summary()["used"]["model"] == 1
        changed = OpenAICompatibleProvider(provider.base_url,"changed",provider.api_key,timeout=120,response_format="json_object")
        with pytest.raises(ValueError,match="WORKER_DENIED"):
            budget.check_worker(result["attempt_id"],changed)
        assert "synthetic-secret" not in json.dumps(result,default=str)


@pytest.mark.parametrize("first_empty", [False, True])
def test_continuation_service_keeps_partial_then_stops_transport_failure(tmp_path,clock,first_empty):
    class Reader:
        text_first = False
        def __init__(self): self.calls = []
        def connect(self): self.calls.append("connect")
        def search(self, query):
            self.calls.append("search")
            return tuple(Candidate(f"xhs:next-{i}",f"合成青谷路线{i}","normal",True) for i in range(3))
        def detail(self, c, number):
            self.calls.append("detail")
            return DetailMaterial(c.source_id,c.title,BODY,"PARTIAL_TEXT",clock().isoformat())
        def disable_text_first(self): raise AssertionError("NO_RETRY")
    with Database(tmp_path / "service.sqlite3",clock=clock) as db:
        store, kw, provider = setup(db,clock)
        before = [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts")]
        budget = ContinuationBudget(store)
        budget.grant("owner","partial",provider)
        budget.start()
        reader = Reader()
        dispatched = []
        def dispatch(attempt,gaps):
            source = db.connection.execute("SELECT source_id FROM source_contents JOIN extraction_attempts USING(content_id) WHERE attempt_id=?",(attempt,)).fetchone()[0]
            budget.reserve("MODEL",source)
            dispatched.append(attempt)
            fake = (Provider([] if first_empty else [candidate(BODY.splitlines()[0]),candidate("不存在")])
                    if len(dispatched) == 1 else Timeout())
            return ExtractionRecovery(store,EvidenceExtractor(fake,clock=clock)).run_reserved(attempt) | {"result":None}
        def review(out):
            review_candidates(store,attempt_id=out["attempt_id"],account_scope="owner",decisions={0:accept()})
        service = ResearchService(store,reader,EvidenceExtractor(provider),kw["policy"],
            model_batch_id=CONTINUATION,model_max_attempts=2,continuation=budget,
            extraction_dispatch=dispatch,after_extraction=review)
        report = service.run(ResearchRequest(destination="合成青谷"),research_id=CONTINUATION,revision=0,
                             account_scope="owner",budget=ResearchBudget(1,2))
        assert report.diagnostic == "LIVE_LLM_EXTRACTION_FAILED"
        assert reader.calls == ["connect","search","detail","detail"] and len(dispatched) == 2
        assert sum(len(b["claims"]) for b in report.evidence) == (0 if first_empty else 1)
        assert store.contents.load("xhs:next-1","owner")
        assert [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_attempts WHERE batch_id='fixed-t063'")] == before
        assert budget.summary()["remaining"]["model"] == 0


def test_owned_new_source_worker_exit_keeps_service_run_open(tmp_path,clock):
    with Database(tmp_path / "worker.sqlite3",clock=clock) as db:
        store, kw, provider = setup(db,clock)
        run = store.begin("active-service",0,ResearchRequest(destination="合成青谷").to_dict(),"owner")
        store.register_policy(run,0,kw["policy"])
        store.reserve_operation(run,0,"DETAIL","xhs:worker-source",1)
        content = store.save_source(run,0,DetailMaterial("xhs:worker-source","合成材料",BODY,"PARTIAL_TEXT",db.stamp()),kw["policy"],"合成青谷")
        def dispatch(attempt,gaps):
            return supervise_reserved(db.path,attempt,provider=provider,deadline=3,
                                      command=[sys.executable,"-c","pass"],finish_report=False)
        result = ExtractionRecovery(store,EvidenceExtractor(provider)).execute(run_id=run,revision=0,
            content_id=content,account_scope="owner",policy=kw["policy"],batch_id="new-worker-test",max_attempts=1,dispatch=dispatch)
        assert result["status"] == "INTERRUPTED" and result["owned_worker_exited"]
        assert store.is_current(run,0) and store.contents.load("xhs:worker-source","owner")
        assert result["diagnostic"]["http_attempts"] == 0
