"""Authored content through the ordinary service; no network or review bypass."""

import pytest

from travel_agent.domain.source_policy import private_policy
from travel_agent.persistence.database import Database
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.models import Candidate, DetailMaterial, ResearchBudget, ResearchRequest
from travel_agent.research.service import ResearchService
from travel_agent.research.store import EvidenceStore
from test_reference_selection import ReferenceProvider, choice
from test_daily_workbench import normal as normal_fixture

normal = normal_fixture


EXPERIENCE = (
    "纸艺空间展陈不同纸张的纹理，参观时可以比较透光和触感。\n"
    "手作体验需要耐心折叠，喜欢动手的游客可以尝试，不想动手则只欣赏成品。"
)


def test_focused_query_uses_explicit_play_purpose():
    from travel_agent.preview.worker import FocusedPlanner
    from travel_agent.research.models import ResearchGap
    request = ResearchRequest(destination="合成海城", research_question="具体玩法、体验差异和取舍")
    query = FocusedPlanner("市区 游玩").plan(request, (), (ResearchGap("EXPERIENCES", "体验不足", ("EXPERIENCE",)),), set())[0]
    assert "体验" in query.text and "路线 行程" not in query.text


def test_daily_advisory_job_carries_purpose_through_worker(normal):
    from uuid import uuid4
    from travel_agent.planning.flow_models import PlanCreate, OperationAuthorization
    from travel_agent.preview.worker import run_job
    from test_planning_flow import act
    from test_workbench_pipeline import dispatches

    service, _ = normal
    view = service.create(PlanCreate(destination="合成海城", request="先看看具体玩法和体验"), str(uuid4()))
    view = act(service, view, "authorize", authorization=OperationAuthorization(
        confirm=True, tasks=["RESEARCH", "PLANNING"], connect=1, search=1, detail=1, model=3))
    view = act(service, view, "research")

    class Reader:
        text_first = False
        def connect(self): pass
        def search(self, query):
            assert "玩法 体验" in query and "路线 行程" not in query
            return (Candidate("xhs:daily-play", "合成海城体验", "normal", True),)
        def detail(self, c, n):
            return DetailMaterial(c.source_id, c.title, EXPERIENCE, "PARTIAL_TEXT", service.db.stamp())
        def disable_text_first(self): raise AssertionError("NO_RETRY")

    class Model(ReferenceProvider):
        def structured(self, task, data, schema):
            if task == "review_evidence_context_v2":
                self.calls += 1
                return {"reviews": []}  # No model approval: never manufacture Evidence.
            return super().structured(task, data, schema)

    model = Model(lambda spans: [choice(spans, 0, (), "EXPERIENCE", kind="GUIDE_SUGGESTION")])
    extract, review = dispatches(model)
    run_job(service.db.path, view["research_job"]["job_id"], reader=Reader(), provider=model,
            extract_dispatch=extract, review_dispatch=review, product=True)
    after = service.get(view["session_id"])
    assert model.calls == 2
    assert after["research_job"]["new_evidence_count"] == 0
    assert after["operation"]["current"]["remaining"]["model"] == 1


@pytest.mark.parametrize("destination", ["合成青谷", "合成海城", "合成江镇"])
def test_ordinary_service_extracts_experience_without_route_words(tmp_path, clock, destination):
    provider, report, store = run_service(tmp_path, clock, destination, EXPERIENCE)
    assert provider.calls == 1
    assert report.operations == {"search": 1, "detail": 1}
    assert report.extraction_results[0]["locator_passed_candidates"] == 1
    assert not report.evidence  # A valid selected span is still pending context review.
    assert store.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
    store.db.connection.close()


@pytest.mark.parametrize("body", [
    "",
    "青谷、镜湖、纸艺空间、松林、沙滩、老街。" * 4,
    "#合成青谷 #展陈 #体验 #参观 #手作 #欣赏 #好玩" * 4,
    "详细的体验和全部介绍请见图片，正文仅作提醒，请翻看图片，文字没有描述具体内容。",
    "服务器升级应先进行数据备份，再检查索引，最后对事务提交做审计，避免记录重复或损坏。",
])
def test_unusable_material_does_not_consume_model(tmp_path, clock, body):
    provider, report, store = run_service(tmp_path, clock, "合成青谷", body)
    assert provider.calls == 0
    assert not report.evidence
    store.db.connection.close()


def run_service(tmp_path, clock, destination, body):
    class Reader:
        text_first = False
        def connect(self): pass
        def search(self, query):
            return (Candidate("xhs:authored-play", destination + "玩法与体验", "normal", True),)
        def detail(self, candidate, number):
            return DetailMaterial(candidate.source_id, candidate.title, body, "PARTIAL_TEXT", clock().isoformat())
        def disable_text_first(self): raise AssertionError("NO_RETRY")

    class Permit:
        def reserve(self, kind, fingerprint): pass

    db = Database(tmp_path / "material.sqlite3", clock=clock)
    store = EvidenceStore(db)
    provider = ReferenceProvider(lambda spans: [choice(spans, 0, (), "EXPERIENCE", kind="GUIDE_SUGGESTION")])
    service = ResearchService(store, Reader(), EvidenceExtractor(provider, clock=clock),
        private_policy("owner", now=clock()), continuation=Permit(), model_max_attempts=1)
    report = service.run(ResearchRequest(destination=destination, research_question="有哪些具体玩法、体验差异和取舍？"),
        research_id="authored-material", revision=0, account_scope="owner", budget=ResearchBudget(1, 1))
    return provider, report, store
