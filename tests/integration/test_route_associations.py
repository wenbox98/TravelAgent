"""Explicit authored trip objects, never geographic or proximity inference."""

from pathlib import Path
import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.candidate_review import review_candidates
from travel_agent.research.reporting import build_directions, render_private_report
from travel_agent.research.models import ResearchReport, ResearchRequest
from travel_agent.research.quality import evaluate_coverage
from test_candidate_grounding import prepare, candidate, accept

BODY = "2024年秋天的甲行程。\n我当次从青谷到镜湖。\n这趟一共四天。\n以上行程我全程自驾。\n我在镜湖散步。\nD1在青谷步行两小时。\n另一个乙行程。\n乙行程从红岭到白湾。\n乙行程一共七天。"


def association(index=0, scope="WHOLE_TRIP"):
    return {"object_quote": BODY.splitlines()[index], "object_block_id": index, "scope": scope}


def test_explicit_trip_cross_paragraph_grouping_and_segment_not_total(clock):
    rows = [candidate(BODY.splitlines()[i], i, topic) for i, topic in
            [(1,"ROUTE"),(2,"DURATION"),(3,"TRANSPORT"),(4,"EXPERIENCE"),(5,"DURATION"),(7,"ROUTE"),(8,"DURATION")]]
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kw = prepare(db, clock, rows, BODY)
        out = runner.execute(**kw)
        decisions = {i: accept(route_association=association(0 if i < 5 else 6, "SEGMENT" if i == 4 else "WHOLE_TRIP"),
                               reference_scope="AUTHOR_RECORDED_TRIP") for i in range(7)}
        reviewed = review_candidates(store, attempt_id=out["attempt_id"], account_scope="owner", decisions=decisions)
        assert reviewed["counts"]["persisted_evidence"] == 7
        evidence = store.lookup("partial", "合成青谷", "owner")
        first, second = build_directions(evidence)
        assert len(first["duration_clues"]) == 2 and len(first["limitations"]) == 1
        assert len(second["duration_clues"]) == 1 and not second["limitations"]
        assert first["duration_clues"][0]["text"] == BODY.splitlines()[2]
        assert second["duration_clues"][0]["text"] == BODY.splitlines()[8]
        assert {c.status for c in evaluate_coverage(evidence, now=clock())} == {"SUPPORTED"}
        report = ResearchReport("partial",0,kw["run_id"],ResearchRequest(days=5,no_self_drive=True),evidence,(),
                                "BUDGET_EXHAUSTED",{},1)
        text = render_private_report(report.material_view(), [b.to_dict() for b in evidence])
        assert "作者当次整趟时长" in text and "不是总天数" in text and "不能证明公共交通可行" in text
        assert "尚缺明确适用条件" in " ".join(second["unknown"])


@pytest.mark.parametrize("bad", [association(6), association() | {"object_quote":"不存在的行程"}, association() | {"scope":"ANY"}])
def test_invalid_or_orphan_associations_cannot_be_persisted(clock, bad):
    with Database(Path(":memory:"), clock=clock) as db:
        store, runner, _, kw = prepare(db, clock, [candidate(BODY.splitlines()[2],2,"DURATION")],BODY)
        out = runner.execute(**kw)
        with pytest.raises(ValueError):
            review_candidates(store,attempt_id=out["attempt_id"],account_scope="owner",decisions={0:accept(route_association=bad)})
        assert not store.lookup("partial", "合成青谷", "owner")
