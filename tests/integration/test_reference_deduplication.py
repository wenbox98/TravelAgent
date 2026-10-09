# ruff: noqa: F811
"""Authored aliases only; no real source text, network or working database."""

from copy import deepcopy

import pytest

from travel_agent.planning.reference_overview import project
from test_planning_conversation import conversation, send  # noqa: F401
from test_knowledge_library import normal, organize  # noqa: F401


def pair():
    original = dict(
        claim_id="claim-original",
        source_id="source-authored",
        source_version="body-v1",
        locator="body-v1:chars:0:24",
        text="景区班车停靠合成南园，末班较早，需要预留返程。",
        conditions=["自编秋季出行条件"],
        topic="TRANSPORT",
        reference_kind="GUIDE_SUGGESTION",
        review_status="MODEL_CONTEXT_REVIEWED",
        source_title="自编交通参考",
        route_association=None,
    )
    card = dict(
        original,
        claim_id="card-authored",
        knowledge_kind="SOURCE_REFERENCE",
        knowledge_binding={"card_id": "card-authored", "version": 1},
        source_version=None,
    )
    return original, card


def test_card_and_original_same_proven_locator_are_one_point_with_both_citations():
    rows = pair()
    value = project(list(rows), {"draft": {"activities": []}})
    assert len(value["points"]) == 1
    point = value["points"][0]
    assert set(point["bindings"]) == {r["claim_id"] for r in rows}
    assert len(point["entries"]) == 1
    assert set(point["entries"][0]["citation_ids"]) == set(point["bindings"])
    assert value["source_count"] == 1
    from travel_agent.research.advisory_coverage import assess
    from travel_agent.research.models import ResearchRequest

    before = assess([rows[0]], ResearchRequest(destination="自编区域", days=7))
    after = assess(list(rows), ResearchRequest(destination="自编区域", days=7))
    for key in (
        "sufficient",
        "unique_fact_count",
        "activity_count",
        "source_count",
        "distinct_content_groups",
    ):
        assert after[key] == before[key]


@pytest.mark.parametrize(
    "change",
    [
        {"conditions": ["自编冬季，末班可能变化"]},
        {"reference_kind": "AUTHOR_RECORDED_TRIP"},
        {
            "route_association": {
                "scope": "DAY_SEGMENT",
                "object_quote": "另一段路线",
                "object_locator": "different",
            }
        },
        {"source_id": "another-authored-source"},
        {"source_version": "body-v2"},
        {"locator": "body-v1:chars:25:49"},
        {"review_status": "WORK_REVIEWED"},
        {"text": "景区班车停靠合成南园，末班较晚。"},
        {"duration_scope": "DAY_SEGMENT"},
        {"knowledge_kind": None, "source_version": None},
    ],
)
def test_same_text_different_conditions_role_object_or_unproved_lineage_remains_separate(change):
    original, card = pair()
    card.update(change)
    assert len(project([original, card], {"draft": {"activities": []}})["points"]) == 2


def test_actual_organized_card_retains_proven_original_lineage_without_raw_fallback(normal):
    from travel_agent.knowledge.planning import card_references
    from travel_agent.planning.materials import references
    from travel_agent.knowledge.store import no_raw

    s, old = normal
    cards = organize(s, old)
    original = references(s.db, s.scope, old["session_id"])
    with no_raw(s.db):
        derived = card_references(cards)
    p = {"draft": old["draft"]}
    baseline = project(original, p)
    combined = project([*original, *derived], p)
    assert len(combined["points"]) == len(baseline["points"])
    assert len(combined["cards"]) == len(baseline["cards"])
    assert combined["source_count"] == baseline["source_count"]
    assert any(len(card["bindings"]) > len(card["entries"]) for card in combined["cards"])


def test_provider_serializes_one_body_and_all_citation_aliases_without_mutating_frozen_input(
    monkeypatch,
):
    import json
    from io import BytesIO
    from pydantic import SecretStr
    from travel_agent.providers.llm import OpenAICompatibleProvider

    seen = []

    class Opener:
        def open(self, request, timeout):
            seen.append(json.loads(request.data))
            response = BytesIO(
                json.dumps(
                    {"choices": [{"finish_reason": "stop", "message": {"content": '{"ok":true}'}}]}
                ).encode()
            )
            response.status = 200
            return response

    monkeypatch.setattr("travel_agent.providers.llm.build_opener", lambda *args: Opener())
    data = dict(
        references=list(pair()),
        allowed_citation_ids=[r["claim_id"] for r in pair()],
        instructions="自编规划输入",
    )
    before = deepcopy(data)
    provider = OpenAICompatibleProvider(
        "http://127.0.0.1", "authored", SecretStr("fixture"), 120, "json_object"
    )
    assert provider.structured(
        "cached_travel_question_v1",
        data,
        {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}},
    ) == {"ok": True}
    wire = json.loads(seen[0]["messages"][1]["content"])["input"]
    assert len(seen) == 1 and len(wire["references"]) == 1
    assert wire["reference_aliases"] == {"claim-original": ["card-authored"]}
    assert set(wire["allowed_citation_ids"]) == {"claim-original", "card-authored"}
    assert data == before


def test_alias_hint_cannot_merge_same_words_from_different_sources():
    from travel_agent.research.reference_identity import model_payload

    original, card = pair()
    card["source_id"] = "unrelated-authored-source"
    data = dict(
        references=[original, card], reference_aliases={original["claim_id"]: [card["claim_id"]]}
    )
    wire = model_payload(data)
    assert len(wire["references"]) == 2 and "reference_aliases" not in wire


def test_legacy_alias_selection_exclusion_restore_and_planning_question_inputs_stay_consistent(
    conversation, monkeypatch
):
    from travel_agent.planning import reference_overview, questions
    from travel_agent.planning.conversation import freeze_context
    from travel_agent.planning.suggestions import payload_for
    from travel_agent.research.reference_identity import model_payload
    from travel_agent.persistence.database import Database
    from travel_agent.planning.flow import PlanningService

    s, v, model, reader = conversation
    _, state = s.plans.load(v["session_id"])
    rows = reference_overview.references(s.db, "owner", v["session_id"], state["planning"])
    target = next(r for r in rows if r["topic"] == "EXPERIENCE")
    alias = dict(
        target,
        claim_id="card-authored-transport",
        knowledge_kind="SOURCE_REFERENCE",
        knowledge_binding={"card_id": "card-authored-transport", "version": 1},
    )
    usage = deepcopy(v["operation"]["cumulative_used"])
    calls = deepcopy((model.calls, reader.calls))
    # Create the old one-citation selection through the normal action, then expose
    # its now-present original. No direct synthetic approval or database rewrite.
    monkeypatch.setattr(reference_overview, "references", lambda *args: [alias])
    old_point = s.plans.get(v["session_id"])["reference_overview"]["projected"]["points"][0]
    v = send(s, v, "select_point", option_id=old_point["option_id"])
    monkeypatch.setattr(reference_overview, "references", lambda *args: [*rows, alias])
    v = s.plans.get(v["session_id"])
    point = next(
        p
        for p in v["reference_overview"]["projected"]["points"]
        if alias["claim_id"] in p["bindings"]
    )
    assert v["reference_overview"]["selected_points"] == [point["option_id"]]
    v = send(s, v, "clear_point", option_id=point["option_id"])
    assert not v["reference_overview"]["selected_points"]
    v = send(s, v, "select_point", option_id=point["option_id"])
    _, state = s.plans.load(v["session_id"])
    p = deepcopy(state["planning"])
    freeze_context(s.db, "owner", v["session_id"], p)
    planning = payload_for(p, s.db, "owner", v["session_id"])
    assert planning["conversation"]["selected_points"][0]["citation_ids"] == [target["claim_id"]]
    answer = questions.payload(s.db, "owner", v["session_id"], p, "这条交通参考有哪些限制？")
    wire = model_payload(answer)
    assert wire["reference_aliases"][target["claim_id"]] == [alias["claim_id"]]
    assert sum(r["text"] == target["text"] for r in wire["references"]) == 1
    v = send(s, v, "exclude_point", option_id=point["option_id"])
    _, state = s.plans.load(v["session_id"])
    excluded = questions.payload(s.db, "owner", v["session_id"], state["planning"], "比较其他资料")
    assert not {target["claim_id"], alias["claim_id"]} & {
        r["citation_id"] for r in excluded["references"]
    }
    v = send(s, v, "restore_point", option_id=point["option_id"])
    assert not v["reference_overview"]["excluded_points"]
    assert v["operation"]["cumulative_used"] == usage and (model.calls, reader.calls) == calls
    with Database(s.db.path) as db:
        restored = PlanningService(db, "owner").get(v["session_id"])
        assert (
            restored["reference_overview"]["projected"]["points"]
            == v["reference_overview"]["projected"]["points"]
        )
