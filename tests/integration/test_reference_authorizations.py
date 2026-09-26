"""Reuse the existing grants; migration, replay and failure stop use synthetic data."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.continuation import ContinuationBudget, CONTINUATION
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import DetailMaterial, ResearchRequest
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.retry import authorize_extra, reserve_extra, supervise_extra
from travel_agent.research.store import EvidenceStore
from test_candidate_grounding import Provider
from test_continuation_budget import setup
from test_reference_selection import BODY, ReferenceProvider, choice


def prepare_grants(path,clock):
    with Database(path,clock=clock,target_version=9) as db:
        store,kw,provider=setup(db,clock)
        budget=ContinuationBudget(store)
        budget.grant('owner','partial',provider)
        budget.start()
        run=store.begin(CONTINUATION,0,ResearchRequest(destination='合成青谷').to_dict(),'owner')
        store.register_policy(run,0,kw['policy'])
        for index in range(2):
            sid=f'xhs:reference-{index}'
            store.reserve_operation(run,0,'DETAIL',sid,2)
            content=store.save_source(run,0,DetailMaterial(sid,'合成标题五天四晚',BODY,'PARTIAL_TEXT',db.stamp()),kw['policy'],'合成青谷')
            result=ExtractionRecovery(store,EvidenceExtractor(Provider([]),clock=clock, protocol_version=2)).execute(run_id=run,revision=0,
                content_id=content,account_scope='owner',policy=kw['policy'],batch_id=CONTINUATION,max_attempts=2)
            assert result['status']=='NO_ACCEPTED_EVIDENCE'
        budget.finish()
        bases=[r[0] for r in db.connection.execute("SELECT attempt_id FROM extraction_attempts WHERE batch_id=? ORDER BY created_at,attempt_id",(CONTINUATION,))]
        before={t:[tuple(r) for r in db.connection.execute('SELECT * FROM '+t)] for t in
                ['extraction_attempts','extraction_candidates','extraction_authorizations','claims','source_contents','source_body_blocks']}
    return provider,bases,before


def test_v9_history_grants_120_180_cross_process_single_use(tmp_path,clock,monkeypatch):
    path=tmp_path/'grant.sqlite3'
    provider,bases,before=prepare_grants(path,clock)
    with Database(path,clock=clock) as db:
        assert db.version==Database.LATEST_VERSION
        for t,expected in before.items():
            assert [tuple(r) for r in db.connection.execute('SELECT * FROM '+t)]==expected
        store=EvidenceStore(db)
        for alias,base in zip(['S2','S3'],bases):
            args=dict(base_attempt_id=base,fix_commit='c'*40,provider=provider,deadline=180,reference_source=alias)
            assert authorize_extra(store,**args)['status']=='GRANTED'
            assert authorize_extra(store,**args)['status']=='GRANTED'
        with pytest.raises(ValueError,match='COMPLETED_SNAPSHOT'):
            authorize_extra(store,base_attempt_id=bases[1],fix_commit='c'*40,provider=provider,deadline=180,reference_source='S2')
        dispatched=[]
        def supervisor(database,attempt,*,provider,deadline,command):
            assert provider.timeout==120 and deadline==180 and '--extra-worker' in command
            fake=ReferenceProvider(lambda spans:[choice(spans)])
            result=ExtractionRecovery(store,EvidenceExtractor(fake,clock=clock,protocol_version=3)).run_reserved(attempt)
            dispatched.append(attempt)
            return result
        monkeypatch.setattr('travel_agent.research.retry.supervise_reserved',supervisor)
        result=supervise_extra(path,base_attempt_id=bases[0],fix_commit='c'*40,provider=provider,reference_source='S2')
        assert result['status']=='PENDING_REVIEW' and len(dispatched)==1
        with pytest.raises(ValueError,match='NOT_REVIEWED_OR_FAILED'):
            reserve_extra(store,base_attempt_id=bases[1],fix_commit='c'*40,provider=provider,deadline=180,reference_source='S3')
    code='''import sys,json
sys.path.insert(0,'apps/api')
from travel_agent.persistence.database import Database
from travel_agent.research.store import EvidenceStore
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.retry import reserve_extra
from pydantic import SecretStr
with Database(sys.argv[1]) as db:
 try:
  reserve_extra(EvidenceStore(db),base_attempt_id=sys.argv[2],fix_commit='c'*40,
    provider=OpenAICompatibleProvider('https://api.deepseek.com','synthetic-model',SecretStr('synthetic-secret'),timeout=120,response_format='json_object'),deadline=180,reference_source='S2')
 except ValueError as e:
  print(str(e))
 else:
  raise AssertionError('REPLAY_ALLOWED')
'''
    child=subprocess.run([sys.executable,'-c',code,str(path),bases[0]],cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,timeout=10)
    assert child.returncode==0 and 'CONSUMED' in child.stdout
    with Database(path,clock=clock) as db:
        store=EvidenceStore(db)
        # A transport/storage failure must stop the second dispatch, not refund S2.
        db.connection.execute("UPDATE extraction_attempts SET status='FAILED' WHERE authorization_id='t066-reference-s2-once'")
        with pytest.raises(ValueError,match='NOT_REVIEWED_OR_FAILED'):
            reserve_extra(store,base_attempt_id=bases[1],fix_commit='c'*40,provider=provider,deadline=180,reference_source='S3')
        assert db.connection.execute("SELECT count(*) FROM extraction_attempts WHERE authorization_id LIKE 't066-%'").fetchone()[0]==1
        assert [tuple(r) for r in db.connection.execute("SELECT * FROM extraction_authorizations WHERE authorization_id='t064-response-timeout-once'")]==before['extraction_authorizations']
        assert all(tuple(r) in [tuple(v) for v in db.connection.execute('SELECT * FROM extraction_attempts')] for r in before['extraction_attempts'])
        assert 'synthetic-secret' not in json.dumps([dict(r) for r in db.connection.execute('SELECT * FROM extraction_authorizations')])
