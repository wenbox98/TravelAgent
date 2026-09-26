"""Authored T06.5 fixtures; no real destinations, source text or network."""

from copy import deepcopy

from travel_agent.domain.models import EvidenceBundle
from travel_agent.research.canonical import body_blocks
from travel_agent.research.reporting import build_directions
from test_research_planning import bundle
from travel_agent.research.models import Candidate, ResearchRequest, ResearchReport
from travel_agent.research.planning import CandidateSelector
from travel_agent.research.reporting import render_private_report


def test_query_only_sublocation_is_weak_and_irrelevant_titles_are_excluded():
    rows = (Candidate("sub", "镜湖三天行程", "normal", True),
            Candidate("irrelevant", "合成地区键盘维修", "normal", True),
            Candidate("ambiguous", "镜湖随拍", "normal", True),
            Candidate("video", "镜湖行程", "video", True),
            Candidate("seen", "青谷路线", "normal", True))
    choices = CandidateSelector().select(rows, ResearchRequest(destination="合成青谷"), (), {"seen"},
                                         query_context="合成青谷 路线 行程 天数")
    assert [c.candidate.source_id for c in choices] == ["sub"]
    assert "弱相关" in next(c.reason for c in choices if c.candidate.source_id == "sub")
    assert "地点归属未证实" in next(c.reason for c in choices if c.candidate.source_id == "sub")


def test_private_report_preserves_conditions_and_known_preferences(fixture_data):
    data = bundle(fixture_data).to_dict()
    conditions = ["2024年秋天我自驾", "如果有时间才去", "我实际没有进入景点"]
    for meta in data["claim_metadata"].values():
        meta["applicable_conditions"] = conditions
    evidence = (EvidenceBundle(data),)
    report = ResearchReport("synthetic", 0, "run", ResearchRequest(days=5, no_self_drive=True), evidence,
                            (), "BUDGET_EXHAUSTED", {"search":0,"detail":0}, 1)
    text = render_private_report(report.material_view(), [data])
    assert all(text.count(c) >= 4 for c in conditions)
    assert "5天、不自驾" in text and "交通方式仍未知" not in text
    assert "是否考虑自驾？" not in text and "大概能安排几天？" not in text
    assert "不能证明公共交通可行" in text


def test_cross_source_names_remain_separate(fixture_data):
    first = bundle(fixture_data)
    second = deepcopy(first.to_dict())
    second["source_id"] = "synthetic-independent"
    for claim in second["claims"]:
        claim["source_id"] = second["source_id"]
    directions = build_directions((first, EvidenceBundle(second)))
    assert len(directions) == 2
    assert all(len(d["source_ids"]) == 1 for d in directions)


def test_separate_explicit_trip_paragraphs_need_reviewed_association(fixture_data):
    data = bundle(fixture_data).to_dict()
    for claim in data["claims"]:
        claim["text"] = claim["text"].split("：", 1)[1]
    blocks = body_blocks("\n".join(c["text"] for c in data["claims"]), origin="STATE", normalized=True)
    for claim, block in zip(data["claims"], blocks, strict=True):
        claim["locator"] = block.locator
        data["claim_metadata"][claim["claim_id"]]["block_locators"] = [block.locator]
    # Baseline reproducer: without an audited association, 'same note' is insufficient.
    direction, = build_directions((EvidenceBundle(data),))
    assert not direction["duration_clues"] and not direction["limitations"]
