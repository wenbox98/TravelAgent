"""Synthetic review regression: IDs, semantics, dependencies and independent retention."""

import json

import pytest

from travel_agent.persistence.database import Database
from travel_agent.research.context_review import build_input, check_decision, REVIEW_SCHEMA
from travel_agent.research.grounding import REVIEW_DIMENSIONS
from test_reference_selection import execute, choice

BODY = "我计划秋季自驾，还没出发。\n行程草案。\nDay1：合成青谷→合成镜湖。\n我想在湖边散步。\n景区大巴每天八点发车。"


def proposal(data, index=0, **changes):
    c = data["candidates"][index]
    return dict(
        candidate_index=c["candidate_index"],
        **({"candidate_topic": c["topic"]} if data["review_version"] != 1 else {}),
        decision="REFERENCE",
        reason_code="CONTEXT_SUPPORTED",
        dimension_checks={k: True for k in REVIEW_DIMENSIONS},
        context_span_ids=c["condition_span_ids"],
        reference_scope="AUTHOR_PROPOSED_PLAN",
        duration_scope="NONE",
        object_span_id=None,
        object_scope="SEGMENT",
        dependency_resolution="INDEPENDENT",
        explanation="仅作为作者计划参考。",
        **changes,
    )


def test_input_independent_of_work_labels_and_body_not_duplicated(tmp_path, clock):
    with Database(tmp_path / "review.sqlite3", clock=clock) as db:
        store, _, out = execute(db, clock, lambda s: [choice(s, 2, (0, 1))], BODY)
        data, context = build_input(store, out["attempt_id"], "owner", {"days": 5, "driving": "NO"})
        db.connection.execute(
            "UPDATE extraction_candidates SET context_status='ACCEPTED',context_reason='WORK_CONTEXT_VERIFIED',review_json='{}'"
        )
        assert (
            build_input(store, out["attempt_id"], "owner", {"days": 5, "driving": "NO"})[0] == data
        )
        encoded = json.dumps(data, ensure_ascii=False)
        assert "WORK" not in encoded and "xhs:" not in encoded and "content_hash" not in encoded
        assert sum(len(s["text"]) for s in data["spans"]) <= 6000
        assert encoded.count("我计划秋季自驾") == 1
        assert check_decision(proposal(data), data, context)["action"] == "ACCEPT"


@pytest.mark.parametrize("defect", ["foreign_id", "missing_condition", "role", "day", "unsafe"])
def test_model_confidence_cannot_override_program_checks(tmp_path, clock, defect):
    with Database(tmp_path / "review.sqlite3", clock=clock) as db:
        store, _, out = execute(
            db,
            clock,
            lambda s: [
                choice(
                    s,
                    4 if defect == "unsafe" else 2,
                    (0, 1),
                    "DURATION"
                    if defect == "day"
                    else "TRANSPORT"
                    if defect == "unsafe"
                    else "ROUTE",
                )
            ],
            BODY,
        )
        data, context = build_input(store, out["attempt_id"], "owner", {})
        p = proposal(data)
        if defect == "foreign_id":
            p["context_span_ids"] = ["Pforeign"]
        if defect == "missing_condition":
            p["context_span_ids"] = []
        if defect == "role":
            p["reference_scope"] = "AUTHOR_RECORDED_TRIP"
        if defect == "day":
            p["duration_scope"] = "WHOLE_TRIP"
        with pytest.raises(ValueError):
            check_decision(p, data, context)


def test_unknown_output_operations_rejected():
    from travel_agent.providers.llm import LLMError, validate_structured

    with pytest.raises(LLMError):
        validate_structured({"reviews": [], "shell": "run a command"}, REVIEW_SCHEMA)


@pytest.mark.parametrize(
    "invitation",
    [
        "打算去玩的姐妹赶紧收藏。",
        "给准备来玩的朋友整理参考。",
        "想自驾去的游客可以先比较。",
        "我整理了攻略，给打算去玩的朋友参考。",
        "给计划山区旅行的小伙伴推荐组合玩法。",
    ],
)
def test_reader_invitation_is_not_authors_own_future_plan(tmp_path, clock, invitation):
    body = "下面整理了一篇三天游玩攻略。\n" + invitation + "\nDay1：合成松海→合成青湾。"
    with Database(tmp_path / "reader.sqlite3", clock=clock) as db:
        store, _, out = execute(db, clock, lambda s: [choice(s, 2, (0, 1))], body)
        data, ctx = build_input(store, out["attempt_id"], "owner", {})
        p = proposal(data)
        p.update(reference_scope="GUIDE_SUGGESTION", explanation="作者整理建议，未声称亲历。")
        assert check_decision(p, data, ctx)["action"] == "ACCEPT"


@pytest.mark.parametrize(
    "preamble",
    [
        "我打算秋季出发，还没出发。",
        "我计划去玩，给想去玩的朋友参考。",
        "计划明年出发。",
        "想去玩的朋友收藏，我计划明年再去。",
        "给计划去玩的小伙伴参考，我自己还没出发。",
    ],
)
def test_reader_words_cannot_erase_a_real_or_uncertain_author_plan(tmp_path, clock, preamble):
    body = preamble + "\n行程草案。\nDay1：合成松海→合成青湾。"
    with Database(tmp_path / "author.sqlite3", clock=clock) as db:
        store, _, out = execute(db, clock, lambda s: [choice(s, 2, (0, 1))], body)
        data, ctx = build_input(store, out["attempt_id"], "owner", {})
        p = proposal(data)
        p["reference_scope"] = "GUIDE_SUGGESTION"
        with pytest.raises(ValueError, match="ROLE_MISMATCH"):
            check_decision(p, data, ctx)


@pytest.mark.parametrize(
    "text,kind,topic,duration,allowed",
    [
        ("我计划明年走合成青谷环线。", "AUTHOR_PROPOSED_PLAN", "ROUTE", "NONE", True),
        ("听说这条路线很好走。", "AUTHOR_RECORDED_TRIP", "ROUTE", "NONE", False),
        ("我没有去过这个地方。", "AUTHOR_RECORDED_TRIP", "EXPERIENCE", "NONE", False),
        ("去年自驾去过，今年计划改骑车。", "AUTHOR_RECORDED_TRIP", "TRANSPORT", "NONE", False),
        ("请问雨天能不能走？", "GUIDE_SUGGESTION", "TRANSPORT", "NONE", False),
        ("Day4：合成镜湖散步。", "AUTHOR_PROPOSED_PLAN", "DURATION", "WHOLE_TRIP", False),
        ("Day4：合成镜湖散步。", "AUTHOR_PROPOSED_PLAN", "DURATION", "DAY_SEGMENT", False),
        ("计划在镜湖停留两小时。", "AUTHOR_PROPOSED_PLAN", "DURATION", "DAY_SEGMENT", True),
        ("这条路线绝对不会高反。", "GUIDE_SUGGESTION", "OTHER", "NONE", False),
        ("门票目前一百元。", "GUIDE_SUGGESTION", "PRICE", "NONE", False),
        ("乘坐观光车即可到达。", "GUIDE_SUGGESTION", "TRANSPORT", "NONE", False),
    ],
)
def test_semantic_hazards_cannot_be_promoted(tmp_path, clock, text, kind, topic, duration, allowed):
    body = "我计划秋季自驾，还没出发。\n行程草案。\n" + text
    with Database(tmp_path / "hazards.sqlite3", clock=clock) as db:
        store, _, out = execute(db, clock, lambda spans: [choice(spans, 2, (0, 1), topic)], body)
        data, context = build_input(store, out["attempt_id"], "owner", {})
        p = proposal(data)
        p.update(reference_scope=kind, duration_scope=duration)
        if allowed:
            assert check_decision(p, data, context)["action"] == "ACCEPT"
        else:
            with pytest.raises(ValueError):
                check_decision(p, data, context)
