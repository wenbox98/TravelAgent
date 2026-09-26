"""Authored span fixtures. Valid IDs never substitute for simulated Work review."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.canonical import canonicalize
from travel_agent.research.candidate_review import review_candidates
from travel_agent.research.content_store import audit_grounding
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.references import catalog, materialize, payload, validate_reference
from travel_agent.research.recovery import ExtractionRecovery
from travel_agent.research.reporting import render_private_report
from test_candidate_grounding import prepare, accept

BODY = "我计划今年秋季自驾，还没出发。\n行程草案：青谷→镜湖。\n第二天在镜湖待一整天。\n去年曾到山城。去年曾到山城。\n另一段说的是西谷，与上述计划无关。\n微信：不应发送。"


class ReferenceProvider:
    is_external = True
    is_mock = False
    def __init__(self, select): self.select, self.calls = select, 0
    def structured(self, task, data, schema):
        assert task == "select_evidence_references_v1"
        assert "blocks" not in data and "source_title" not in data
        assert not {"claim", "quote", "source_block_ids"} & schema["properties"]["claims"]["items"]["properties"].keys()
        self.calls += 1
        self.data = data
        return {"claims": self.select(data["spans"])}


def choice(spans, block=1, conditions=(0,), topic="ROUTE", occurrence=0, kind="AUTHOR_PROPOSED_PLAN"):
    return {"topic": topic, "statement_span_id": [s for s in spans if s["parent_block"] == block][occurrence]["span_id"],
            "condition_span_ids": [s["span_id"] for s in spans if s["parent_block"] in conditions],
            "proposed_reference_kind": kind}


def execute(db, clock, select, body=BODY):
    store, _, _, kwargs = prepare(db, clock, [], body=body)
    provider = ReferenceProvider(select)
    outcome = ExtractionRecovery(store, EvidenceExtractor(provider, clock=clock, protocol_version=3)).execute(**kwargs)
    return store, provider, outcome


def test_catalog_exact_positions_filtering_and_long_context():
    view = canonicalize("  Café\u0301\t😀。 同句。 同句。\r\n微信：秘密内容。\n" + "长段否定不能删掉，" * 90)
    directory = catalog(view, "synthetic:a", "content-a", "a" * 64)
    sent = payload(directory, view)
    assert not any(s["parent_block"] == 1 for s in sent)
    assert sum(len(s["text"]) for s in sent) <= 6000
    assert all(len(s["text"]) <= 120 for s in sent)
    assert all(s["text"] == view.text[directory["spans"][s["span_id"]]["start"]:directory["spans"][s["span_id"]]["end"]] for s in sent)
    assert "".join(s["text"] for s in sent if s["parent_block"] > 1) == "".join(b.text for b in view.blocks[2:])
    assert all(s["context_required"] for s in sent)
    selected = {"topic":"EXPERIENCE", "statement_span_id":sent[2]["span_id"], "condition_span_ids":[], "proposed_reference_kind":"UNKNOWN"}
    row = materialize(selected,directory,view)
    assert row["reference_selection"]["statement"]["start"] > view.text.index("同句")
    validate_reference(row,view,"synthetic:a")
    bad = deepcopy(row)
    bad["reference_selection"]["statement"]["start"] -= 4
    with pytest.raises(ValueError,match="MISMATCH"):
        validate_reference(bad,view,"synthetic:a")
    for other in [catalog(view,"synthetic:b","content-a","a"*64),catalog(view,"synthetic:a","content-b","a"*64)]:
        with pytest.raises(ValueError,match="NOT_SENT"):
            materialize(selected,other,view)
    oversized=canonicalize("\n".join("句"*100 for _ in range(80)))
    sent=payload(catalog(oversized,"s","c","b"*64),oversized)
    assert sum(len(s["text"]) for s in sent)==6000


def test_program_union_second_occurrence_persistence_and_zero_access_recovery(tmp_path,clock):
    path=tmp_path/"reference.sqlite3"
    with Database(path,clock=clock) as db:
        store,provider,out=execute(db,clock,lambda spans:[choice(spans),choice(spans,3,(0,),"EXPERIENCE",1,"AUTHOR_RECORDED_TRIP")])
        assert out["status"]=="PENDING_REVIEW" and out["counts"]["locator_passed_candidates"]==2
        assert all(m['context_review_status']=='PENDING' for m in out['result'].bundle['claim_metadata'].values())
        assert not store.lookup("partial","合成青谷","owner")
        raw=json.loads(db.connection.execute('SELECT candidate_json FROM extraction_candidates WHERE candidate_index=0').fetchone()[0])
        assert raw["source_block_ids"]==[0,1] and raw["claim"]==raw["quote"]
        # Deliberately wrong selected condition is not silently approved.
        review_candidates(store,attempt_id=out["attempt_id"],account_scope="owner",decisions={
            0:accept(reference_scope="AUTHOR_PROPOSED_PLAN",dependency_resolution="INDEPENDENT"),
            1:{"action":"REJECT","reason_code":"CONTEXT_CONDITION_OMITTED"}})
        assert provider.calls==1
        ev=store.lookup("partial","合成青谷","owner")
        assert ev[0]["claim_metadata"][ev[0]["claims"][0]["claim_id"]]["reference_scope"]=="AUTHOR_PROPOSED_PLAN"
        assert audit_grounding(ev[0],store.contents.load(ev[0]["source_id"],"owner"))["unsupported"]==0
    root=Path(__file__).resolve().parents[2]
    child=subprocess.run([sys.executable,str(root/'tools/private_cache_probe.py'),'--database',str(path),
                          '--account-scope','owner','--research-id','partial'],capture_output=True,text=True,timeout=15)
    restored=json.loads(child.stdout)
    assert child.returncode==0 and all(restored['checks'].values())
    assert restored['summary']['evidence_count']==1 and restored['model_calls']==restored['browser_sessions']==0
    assert restored['calls']=={'connect':0,'search':0,'detail':0}


def test_selected_second_identical_sentence_keeps_authoritative_locator(clock):
    with Database(Path(':memory:'),clock=clock) as db:
        store,_,out=execute(db,clock,lambda spans:[choice(spans,3,(),"EXPERIENCE",1,"AUTHOR_RECORDED_TRIP")])
        row=json.loads(db.connection.execute('SELECT candidate_json FROM extraction_candidates').fetchone()[0])
        span=row['reference_selection']['statement']
        result=review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={
            0:accept(reference_scope='AUTHOR_RECORDED_TRIP',context_span_ids=[span['span_id']])})
        assert result['counts']['persisted_evidence']==1
        bundle=store.lookup('partial','合成青谷','owner')[0]
        claim=bundle['claims'][0]
        assert claim['locator']==span['locator']
        assert span['start']==canonicalize(BODY).text.rindex('去年曾到山城。')
        assert not audit_grounding(bundle,store.contents.load(bundle['source_id'],'owner'))['unsupported']


@pytest.mark.parametrize('defect',['unknown','unsent','other_snapshot'])
def test_invalid_id_only_rejects_affected_candidate(clock,defect):
    def selected(spans):
        bad=choice(spans)
        bad['condition_span_ids']=[{'unknown':'Punknown','unsent':'P'+'a'*20+'-5-0-1',
            'other_snapshot':'P'+'b'*20+'-0-0-1'}[defect]]
        return [bad,choice(spans)]
    with Database(Path(':memory:'),clock=clock) as db:
        store,_,out=execute(db,clock,selected)
        assert out['counts']['generated_candidates']==2
        assert out['counts']['locator_passed_candidates']==1
        assert out['candidate_checks'][0]['reason_code']=='REFERENCE_ID_NOT_SENT'
        with pytest.raises(ValueError,match='REJECTED_LOCATOR'):
            review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={0:accept(reference_scope='AUTHOR_PROPOSED_PLAN')})


@pytest.mark.parametrize('dimension',['subject','negation','hypothesis','time','transport','scope','source_kind','images'])
def test_valid_ids_do_not_approve_missing_context(clock,dimension):
    with Database(Path(':memory:'),clock=clock) as db:
        store,_,out=execute(db,clock,lambda spans:[choice(spans)])
        decision=accept(reference_scope='AUTHOR_RECORDED_TRIP')
        decision['dimension_checks'][dimension]=False
        with pytest.raises(ValueError,match='CONTEXT_REVIEW_INCOMPLETE'):
            review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={0:decision})
        assert not store.lookup('partial','合成青谷','owner')


def test_proposed_role_is_untrusted_and_day_segment_not_whole_trip(clock):
    with Database(Path(':memory:'),clock=clock) as db:
        store,_,out=execute(db,clock,lambda spans:[choice(spans,2,(0,),"DURATION",kind='AUTHOR_RECORDED_TRIP')])
        with pytest.raises(ValueError,match='REFERENCE_KIND_REVIEW_REQUIRED'):
            review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={0:accept()})
        with pytest.raises(ValueError,match='DURATION_SCOPE_REVIEW_REQUIRED'):
            review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={0:accept(reference_scope='AUTHOR_PROPOSED_PLAN')})
        result=review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={
            0:accept(reference_scope='AUTHOR_PROPOSED_PLAN',duration_scope='DAY_SEGMENT')})
        assert result['summary']['coverage'][2]['status']=='PARTIAL'
        b=store.lookup('partial','合成青谷','owner')[0]
        from travel_agent.research.models import ResearchReport,ResearchRequest
        report=ResearchReport('partial',0,'display',ResearchRequest(days=5,no_self_drive=True),(b,),(),
                              'BUDGET_EXHAUSTED',{'search':0,'detail':0},1)
        text=render_private_report(report.material_view(),[b.to_dict()])
        assert '作者尚未出行的计划' in text and '不是整趟天数' in text
        assert '你大概能安排几天' not in text and '是否考虑自驾' not in text


def test_no_silent_candidate_mapping_mutation(clock):
    with Database(Path(':memory:'),clock=clock) as db:
        store,_,out=execute(db,clock,lambda spans:[choice(spans)])
        raw=json.loads(db.connection.execute('SELECT candidate_json FROM extraction_candidates').fetchone()[0])
        raw['reference_selection']['content_hash']='0'*64
        db.connection.execute('UPDATE extraction_candidates SET candidate_json=?',(json.dumps(raw),))
        with pytest.raises(ValueError,match='SNAPSHOT_MISMATCH'):
            review_candidates(store,attempt_id=out['attempt_id'],account_scope='owner',decisions={0:accept(reference_scope='AUTHOR_PROPOSED_PLAN')})


def test_length_split_does_not_drop_negation_at_boundary(clock):
    text='甲'*118+'不能'+'完成环线。'
    with Database(Path(':memory:'),clock=clock) as db:
        _,_,out=execute(db,clock,lambda spans:[choice(spans,0,(),"ROUTE",1)],body=text)
        assert out['candidate_checks'][0]['passed']
        assert out['candidate_checks'][0]['context_reason']=='CONTEXT_NEGATION_OMITTED'
        assert out['counts']['persisted_evidence']==0
