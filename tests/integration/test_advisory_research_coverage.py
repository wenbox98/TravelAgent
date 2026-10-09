"""Authored coverage, adaptive-query and local login regressions; no external IO."""

from dataclasses import replace
import pytest
from travel_agent.domain.models import EvidenceBundle
from travel_agent.research.advisory_coverage import (
    assess,
    CoverageEvaluator,
    CoveragePlanner,
    limits,
)
from travel_agent.research.canonical import body_blocks
from travel_agent.research.extractor import ExtractionResult
from travel_agent.research.models import Candidate, ResearchBudget, ResearchRequest
from travel_agent.research.service import ResearchService
from test_research_service import FakeReader, StubExtractor, evidence
from travel_agent.persistence.database import Database
from travel_agent.domain.models import SourcePolicy
from travel_agent.research.store import EvidenceStore


@pytest.fixture
def environment(tmp_path, clock, fixture_data):
    with Database(tmp_path / "coverage.sqlite3", clock=clock) as db:
        yield EvidenceStore(db), SourcePolicy(fixture_data("policies.json")["policies"][0])


def rows():
    texts = [
        ("ROUTE", "Day1：合成甲园→合成乙馆→合成丙湖→合成丁街", "first"),
        ("ROUTE", "Day2：合成戊山→合成己园→合成庚馆→合成辛湖", "second"),
        (
            "EXPERIENCE",
            "在合成甲园可以了解自然景观，适合比较沿湖散步与城市展馆的不同体验。",
            "first",
        ),
        ("DURATION", "作者的合成旅行计划安排七天，实际是否完成未知。", "first"),
        ("TRANSPORT", "作者拟乘坐公共交通及班车，班次和跨区衔接仍需核对。", "second"),
        ("TRADEOFF", "住宿可选择公共交通附近的片区，少搬行李，但热门时段可能较拥挤。", "second"),
        ("SEASON", "作者建议秋季出行，其他月份的条件仍未核实。", "second"),
    ]
    return [
        dict(
            topic=t,
            text=text,
            source_id=source,
            claim_id=str(i),
            locator=body_blocks(text, origin="STATE")[0].locator,
            conditions=[],
            review_status="MODEL_CONTEXT_REVIEWED",
            reference_kind="AUTHOR_PROPOSED_PLAN",
            support="SUPPORTED",
        )
        for i, (t, text, source) in enumerate(texts)
    ]


@pytest.mark.parametrize("destination,days", [("合成北区", 2), ("合成南区", 7), ("合成西区", 10)])
def test_sufficient_references_generic_days_and_places(destination, days):
    r = assess(rows(), ResearchRequest(destination=destination, days=days))
    assert r["sufficient"] and r["activity_count"] == 8
    assert r["confirmed_independent_authors"] is None
    assert "不证明" in r["meaning"]
    partial = assess(rows()[:1], ResearchRequest(destination=destination, days=days))
    assert not partial["sufficient"] and partial["gaps"]


def test_duplicate_sources_are_not_independent_coverage_and_unknown_scope_stays_unknown():
    original = rows()[:1]
    duplicate = dict(original[0], claim_id="copy", source_id="copy")
    r = assess(original + [duplicate], ResearchRequest(destination="合成北区", days=7), "CITY_ONLY")
    assert r["distinct_content_groups"] == 1 and r["unique_fact_count"] == 1
    assert not r["sufficient"]


def test_no_driving_adds_transport_gap_and_unreviewed_rows_do_not_fill_it():
    r = rows()
    next(x for x in r if x["topic"] == "TRANSPORT")["text"] = "作者全程使用自驾交通。"
    request = ResearchRequest(destination="合成北区", days=7)
    assert assess(r, request)["sufficient"]
    assert "TRANSPORT" in {
        g["key"] for g in assess(r, replace(request, no_self_drive=True))["gaps"]
    }
    r += [dict(rows()[4], claim_id="unreviewed", review_status="PENDING")]
    assert "TRANSPORT" in {
        g["key"] for g in assess(r, replace(request, no_self_drive=True))["gaps"]
    }


def test_conflicting_transport_is_retained_as_gap():
    r = rows()
    r += [
        dict(r[4], claim_id="conflict", source_id="third", text="该线路没有班车。"),
        dict(r[4], claim_id="opposed", source_id="fourth", text="该线路可以乘班车。"),
    ]
    c = assess(r, ResearchRequest(destination="合成北区", days=7))
    assert c["conflict_count"] and not c["sufficient"]
    assert "CONFLICT" in {g["key"] for g in c["gaps"]}


class ReviewedExtractor(StubExtractor):
    def extract(self, **args):
        result = super().extract(**args)
        b = result.bundle.to_dict()
        for m in b["claim_metadata"].values():
            m.update(
                context_review_status="WORK_REVIEWED",
                reference_scope="GUIDE_SUGGESTION",
                applicable_conditions=["仅自编合成攻略"],
            )
        return replace(result, bundle=EvidenceBundle(b))


def service(environment, reader, *, base=None, extractor=None, deadline=None):
    store, policy = environment
    s = ResearchService(
        store,
        reader,
        extractor or ReviewedExtractor(),
        policy,
        adaptive_queries=True,
        deadline_seconds=deadline,
    )
    s.evaluator = CoverageEvaluator(
        base or [], "synthetic-local", "research-coverage", "UNDECIDED", store.db.clock
    )
    s.planner = CoveragePlanner(None, has_cache=bool(base))
    return s


def run(s, *, budget=ResearchBudget(3, 6)):
    return s.run(
        ResearchRequest(destination="川西", days=7),
        research_id="research-coverage",
        revision=0,
        account_scope="synthetic-local",
        budget=budget,
    )


def test_partial_cache_and_one_note_do_not_end_seven_day_research(environment):
    reader = FakeReader(
        candidates=(Candidate("xhs:synthetic-a", "川西合成路线攻略", "normal", True),)
    )
    s = service(environment, reader, base=rows()[:1])
    report = run(s)
    assert len(reader.searches) == len(set(reader.searches)) == 3
    assert len(reader.details) == 1 and reader.connects == 1
    assert report.stop_reason == "BUDGET_EXHAUSTED" and report.gaps
    assert len(s.unique_candidates) == 1 and report.candidate_count == 3
    assert "7天 路线 玩法" not in reader.searches[0]  # Cached gaps, not a broad restart.


def test_sufficient_cache_skips_login_entirely(environment):
    reader = FakeReader()
    report = run(service(environment, reader, base=rows()))
    assert report.stop_reason == "EVIDENCE_SUFFICIENT"
    assert reader.connects == 0 and not reader.searches and not reader.details


def test_sufficient_after_one_body_stops_before_other_candidates(environment):
    class SeasonExtractor:
        def extract(self, **args):
            b = evidence(args["source_id"], topics=("TRANSPORT",)).to_dict()
            claim = b["claims"][0]
            claim.update(topic="SEASON", text=rows()[-1]["text"], locator=rows()[-1]["locator"])
            meta = b["claim_metadata"][claim["claim_id"]]
            meta.update(
                context_review_status="WORK_REVIEWED",
                reference_scope="AUTHOR_PROPOSED_PLAN",
                applicable_conditions=["仅自编合成攻略"],
                block_locators=[claim["locator"]],
            )
            return ExtractionResult(
                EvidenceBundle(b), body_blocks(args["body"]), (), "MOCK", False, 0
            )

    reader = FakeReader()
    base = [r for r in rows() if r["topic"] != "SEASON"]
    s = service(environment, reader, base=base, extractor=SeasonExtractor())
    report = run(s)
    assert report.stop_reason == "EVIDENCE_SUFFICIENT", s.evaluator.last
    assert len(reader.details) == len(reader.searches) == 1
    assert s.query_progress[0]["new_facts"] == 1


def test_body_allowance_is_shared_across_different_queries(environment):
    reader = FakeReader(
        candidates=tuple(
            Candidate(f"xhs:synthetic-{n}", f"川西合成路线{n}", "normal", True) for n in range(8)
        )
    )
    s = service(environment, reader)
    report = run(s)
    assert report.operations == {"search": 3, "detail": 6}
    assert [q["body_reads"] for q in s.query_progress] == [2, 2, 2]
    assert len(set(reader.searches)) == 3 and report.gaps


def test_deadline_keeps_partial_evidence_without_unbounded_work(environment, monkeypatch):
    times = iter([0, 2])
    monkeypatch.setattr("travel_agent.research.service.monotonic", lambda: next(times, 2))
    reader = FakeReader()
    s = service(environment, reader, base=rows()[:1], deadline=1)
    report = run(s)
    assert report.stop_reason == "BUDGET_EXHAUSTED" and report.diagnostic == "RESEARCH_DEADLINE"
    assert s.evaluator.last["activity_count"] == 4 and report.gaps
    assert reader.connects == 0


def test_defaults_reserve_each_body_extraction_review_and_one_plan():
    for days in [None, 1, 2, 3, 7, 30]:
        budget = limits(days)
        assert budget["model"] == 2 * budget["detail"] + 1
        assert budget["search"] <= 3 and budget["detail"] <= 6


def test_remaining_season_gap_accepts_substantive_body_without_route_words():
    from travel_agent.research.material_eligibility import skip_reason
    from travel_agent.research.models import ResearchGap

    request = ResearchRequest(destination="合成北区", days=7)
    gaps = (ResearchGap("SEASON", "时令参考", ("SEASON",)),)
    body = "秋季清晨气温较低，中午和傍晚温差明显，阴雨天气要另外准备保暖衣物。其他月份的情况本文没有实测，不能直接套用。"
    assert skip_reason(request, gaps, body, None) is None
    assert skip_reason(request, gaps, "这是一张图片，看图了解具体内容。", None) is not None
