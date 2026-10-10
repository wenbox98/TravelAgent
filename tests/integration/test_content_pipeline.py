"""Authored subjects and focused research; no real sources or network."""

from copy import deepcopy

import pytest

from travel_agent.planning.activity_content import content_references
from travel_agent.planning.flow_models import Activity, PlanDraft
from travel_agent.planning.guide_view import project
from travel_agent.planning.materials import activities
from travel_agent.research.models import Candidate, ResearchGap, ResearchRequest
from travel_agent.research.planning import CandidateSelector
from travel_agent.research.material_eligibility import skip_reason
from test_research_service import environment as environment_fixture
from test_daily_workbench import normal as normal_fixture

environment = environment_fixture
normal = normal_fixture


def rows():
    common = dict(
        source_id="authored",
        source_version="v1",
        conditions=["秋季"],
        reference_kind="GUIDE_SUGGESTION",
        review_status="MODEL_CONTEXT_REVIEWED",
    )
    return [
        dict(common, claim_id="route", topic="ROUTE", text="甲园→乙馆", locator="v1:chars:0-6"),
        dict(
            common,
            claim_id="play",
            topic="EXPERIENCE",
            text="📍甲园：秋季可以欣赏树影，喜欢安静的游客可慢逛。",
            locator="v1:chars:7-38",
        ),
    ]


def activity():
    return Activity(
        activity_id="authored-a",
        name="甲园",
        provenance="SOURCE_REFERENCE",
        evidence_ids=["route"],
        description="来源中的地点/体验线索；当前运营待核实",
        conditions=["秋季", "乙馆可以参观纸艺，丙湖夏季适合观鸟。"],
    )


def test_colon_subject_has_exact_name_and_content_binding():
    found = activities(rows(), "虚构海城", limit=None)
    a = next(v for v in found if v.name == "甲园")
    assert "play" in a.evidence_ids
    assert "📍" not in a.name and "：" not in a.name


@pytest.mark.parametrize(
    "change", ["version", "document", "pending", "other", "group", "arrow", "mixed"]
)
def test_direct_content_never_upgrades_other_scope_or_unreviewed(change):
    refs = rows()
    assert [r["claim_id"] for r in content_references(activity().model_dump(), refs)] == ["play"]
    if change == "version":
        refs[1]["source_version"] = "v2"
    if change == "document":
        refs[1]["locator"] = "other:chars:7-38"
    if change == "pending":
        refs[1]["review_status"] = "NEEDS_REVIEW"
    if change == "other":
        refs[1]["text"] = "乙馆：可以欣赏纸艺，也顺便提到甲园。"
    if change == "group":
        refs[1]["text"] = "这组玩法适合秋季，甲园和乙馆都在路线中。"
    if change == "arrow":
        refs[1]["text"] = "甲园➠乙馆，适合秋季慢逛。"
    if change == "mixed":
        refs[1]["text"] = "📍甲园：附近乙馆可以参观纸艺，两处的特点不同。"
    assert content_references(activity().model_dump(), refs) == []


@pytest.mark.parametrize("days,region", [(1, "虚构海城"), (5, "虚构山谷")])
def test_view_keeps_full_premises_but_not_as_other_stop_conditions(days, region):
    refs = rows()
    refs[0]["conditions"] = activity().conditions
    draft = PlanDraft(planning_mode="ADVISORY", days=days, activities=[activity()])
    state = dict(destination=region, draft=draft.model_dump())
    before = deepcopy(state)
    out = project(state, refs)
    a = out["activities"][0]
    assert a["content_references"][0]["text"] == refs[1]["text"]
    assert a["highlight"] == refs[1]["text"]
    assert a["content_references"][0]["role"] == "GUIDE_SUGGESTION"
    assert a["content_references"][0]["conditions"] == ["秋季"]
    assert a["travel_conditions"] == ["秋季"]
    assert a["conditions"] == activity().conditions
    assert out["source_contexts"][0]["conditions"] == refs[0]["conditions"]
    assert state == before


@pytest.mark.parametrize("destination", ["虚构海城", "虚构山谷"])
def test_lodging_focused_list_does_not_spend_body_on_general_route(destination):
    gaps = (ResearchGap("LODGING", "住宿片区待补", ("TRADEOFF",)),)
    candidates = (
        Candidate("route", destination + "三天行程攻略", "normal", True),
        Candidate("stay", destination + "住哪与酒店片区取舍", "normal", True),
    )
    selected = CandidateSelector().select(
        candidates,
        ResearchRequest(destination=destination),
        gaps,
        set(),
        query_context=destination + "住宿",
        focus_gap_ids=("LODGING",),
    )
    assert [c.candidate.source_id for c in selected] == ["stay"]


def test_lodging_focused_eligibility_does_not_accept_unrelated_route():
    gaps = (ResearchGap("LODGING", "住宿片区待补", ("TRADEOFF",)),)
    request = ResearchRequest(destination="虚构海城", research_question="三天路线玩法和住宿")
    route = (
        "第一天先去甲园散步，再去乙馆参观，按兴趣慢慢游玩。第二天在丙街看展陈，第三天自由安排返回。"
    )
    assert skip_reason(request, gaps, route, None) == "INSUFFICIENT_TEXT_FOR_EXTRACTION"
    body = (
        "建议把旅馆选在虚构东站附近，方便第二天出发；喜欢慢逛则考虑虚构西街，少换住宿可减少打包。"
    )
    assert skip_reason(request, gaps, body, None) is None


def test_play_focus_retains_narrative_without_advice_words_or_route():
    body = "我在虚构北馆参观建筑模型和民俗展陈。\n我在虚构南园散步和观察湿地鸟类，后来在园里的长椅休息了一阵。"
    gaps = (ResearchGap("PLAY", "玩法待补", ("EXPERIENCE",)),)
    assert skip_reason(ResearchRequest(destination="虚构海城"), gaps, body, None) is None


def test_unavailable_source_does_not_hide_original_conditions():
    draft = PlanDraft(planning_mode="ADVISORY", activities=[activity()])
    out = project(dict(draft=draft.model_dump()))
    assert out["unlinked_source_conditions"] == activity().conditions
    assert not out["activities"][0]["content_references"]


@pytest.mark.parametrize("adaptive", [False, True])
def test_service_passes_query_focus_to_extraction_and_stops_when_resolved(environment, adaptive):
    from travel_agent.research.models import SearchQuery, ResearchBudget
    from travel_agent.research.service import ResearchService
    from test_research_service import FakeReader, StubExtractor, REQUEST

    store, policy = environment
    recorded = []

    class Extractor(StubExtractor):
        def extract(self, **args):
            recorded.append(args["research_gaps"])
            return super().extract(**args)

    reader = FakeReader(
        candidates=tuple(
            Candidate("xhs:synthetic-" + tag, "川西住宿片区" + tag, "normal", True)
            for tag in ("a", "b")
        )
    )
    service = ResearchService(
        store, reader, Extractor(), policy, adaptive_candidate_selection=adaptive
    )
    lodge = ResearchGap("LODGING", "住宿待补", ("TRADEOFF",))
    route = ResearchGap("ROUTES", "路线待补", ("ROUTE",))

    class Evaluator:
        def gaps(self, request, evidence):
            return (route,) if evidence else (lodge, route)

    class Planner:
        def normalize(self, text):
            return text

        def plan(self, *args):
            return (SearchQuery("川西住宿片区", ("LODGING",), "住宿定向"),)

    service.evaluator, service.planner = Evaluator(), Planner()
    service.run(
        REQUEST,
        research_id="focus-test",
        revision=0,
        account_scope="synthetic-local",
        budget=ResearchBudget(1, 2),
    )
    assert recorded and all(ids == ("LODGING",) for ids in recorded)
    assert len(reader.details) == 1


def test_direct_play_remains_mandatory_and_bad_sibling_is_isolated(normal):
    from travel_agent.planning import advisory
    from test_advisory_output_contract import bound_input
    from test_advisory_guide import proposal

    service, _ = normal
    data = bound_input(service)
    data["allowed_citation_ids"].append("authored-play")
    data["activities"][0]["content_citation_ids"] = ["authored-play"]
    good = proposal(data)
    bad = deepcopy(good["proposals"][0])
    bad["citation_ids"].remove("authored-play")
    result = advisory.validate(
        dict(protocol_version=4, proposals=[bad, good["proposals"][0]]), data
    )
    assert result["accepted_count"] == 1 and result["rejected_count"] == 1
