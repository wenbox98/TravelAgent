"""Authored scoped context, production projection/input/guide path, never live data."""

from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.flow_models import PlanCreate, PlanDraft
from travel_agent.planning.private_budget import IDENTIFIER, LIMITS
from travel_agent.planning.suggestions import payload_for
from travel_agent.planning.materials import references
from travel_agent.research.candidate_review import review_candidates
from test_candidate_grounding import prepare, candidate, accept
from test_planning_flow import act


@pytest.fixture
def scoped(tmp_path, clock):
    with Database(tmp_path / "scoped.sqlite3", clock=clock) as db:
        body = "东桥片区。\n甲木公园→乙桥街。\n东桥片区适合慢逛，春季可以欣赏树影；作者未亲历，雨天不推荐。"
        lines = body.splitlines()
        rows = [
            candidate(lines[i], i, topic, [dict(text=lines[0], quote=lines[0], source_block_id=0)])
            for i, topic in [(1, "ROUTE"), (2, "EXPERIENCE")]
        ]
        for r in rows:
            r["source_block_ids"].append(0)
        store, runner, _, kwargs = prepare(db, clock, rows, body=body)
        result = runner.execute(**kwargs)
        review_candidates(
            store,
            attempt_id=result["attempt_id"],
            account_scope="owner",
            decisions={
                i: accept(
                    reference_scope="GUIDE_SUGGESTION",
                    route_association=dict(
                        object_quote=lines[0], object_block_id=0, scope="SEGMENT"
                    ),
                )
                for i in (0, 1)
            },
        )
        db.connection.execute(
            "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
            (
                IDENTIFIER,
                "owner",
                "AUTHORED_FIXTURE",
                json.dumps({"workspace": sha256(str(db.path.resolve()).encode()).hexdigest()}),
                db.stamp(),
                db.stamp(),
                json.dumps(LIMITS),
                json.dumps(dict(status="PASS", destination="合成青谷", session_id=None)),
            ),
        )
        s = PlanningService(db, "owner")
        v = s.create(PlanCreate(destination="合成青谷", request="两天轻松玩"), str(uuid4()))
        v = act(
            s,
            v,
            "use_activities",
            activity_ids=[a["activity_id"] for a in v["activity_candidates"]],
        )
        draft = PlanDraft.model_validate(v["draft"])
        draft.planning_mode = "ADVISORY"
        v = act(s, v, "save", draft=draft)
        yield s, v


def context(s, v):
    _, state = s.load(v["session_id"])
    p = state["planning"]
    return p, payload_for(p, s.db, s.scope, v["session_id"])


def test_reviewed_object_survives_projection(scoped):
    s, v = scoped
    refs = references(s.db, s.scope, v["session_id"])
    assert len(refs) == 2
    assert all(r.get("route_association") for r in refs)
    assert (
        refs[0]["route_association"]["object_locator"]
        == refs[1]["route_association"]["object_locator"]
    )


def test_production_payload_and_page_keep_scoped_background(scoped):
    s, v = scoped
    p, data = context(s, v)
    assert len(data.get("scoped_context", [])) == 1
    bg = data["scoped_context"][0]
    assert bg["scope"] == "GROUP_BACKGROUND"
    assert len(bg["activity_ids"]) == 2
    assert all(r["level"] == "ROUTE_CONTEXT" for r in data["material_support"])
    assert bg["citation_id"] not in p["draft"]["activities"][0]["evidence_ids"]
    assert s.get(v["session_id"])["guide_view"]["context"]["backgrounds"]


def test_normal_worker_preview_cancel_export_and_restore(scoped, monkeypatch):
    from travel_agent.planning.suggestions import run_worker
    from travel_agent.planning.advisory import validate
    from travel_agent.planning.guide_view import export
    from test_advisory_guide import proposal

    s, v = scoped
    p, data = context(s, v)
    raw = proposal(data)
    bg = data["scoped_context"][0]
    raw["proposals"][0]["context_uses"] = [
        dict(
            context_id=bg["context_id"],
            activity_ids=bg["activity_ids"],
            use="COMPARE",
            reason="偏好慢节奏时可以减少停靠，把时间留给更感兴趣的项目。",
        )
    ]
    assert validate(raw, data)["accepted_count"] == 1
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", lambda: object())
    monkeypatch.setattr(
        "travel_agent.research.bounded.BoundedBudget.check_provider", lambda *_: None
    )
    v = act(s, v, "adopt")
    original = deepcopy(v["adopted"])
    v = act(s, v, "suggest")

    class Model:
        def structured(self, task, sent, schema):
            assert sent["scoped_context"] == data["scoped_context"]
            return raw

    run_worker(s.db.path, v["job"]["job_id"], Model())
    v = act(s, s.get(v["session_id"]), "use_proposal")
    assert v["guide_view"]["context"]["uses"]
    v = act(s, v, "cancel")
    assert v["draft"] == original
    v = act(s, act(s, v, "use_proposal"), "adopt")
    output = export(s.db, s.scope, v["session_id"])
    assert "这组玩法的背景与取舍" in output["markdown"] and "作者未亲历" in output["markdown"]
    assert "雨天不推荐" in output["markdown"] and "不证明每站特色" in output["markdown"]
    assert (
        PlanningService(s.db, s.scope).get(v["session_id"])["guide_view"]["context"]
        == v["guide_view"]["context"]
    )
    import subprocess
    import sys

    code = """
import json,socket,sys
from pathlib import Path
sys.path.insert(0,'apps/api')
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.guide_view import export
def denied(*a,**k): raise AssertionError('NETWORK_DENIED')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
with Database(Path(sys.argv[1])) as db:
 v=PlanningService(db,'owner').get(sys.argv[2])
 assert v['guide_view']['context']['backgrounds'] and v['guide_view']['context']['uses']
 print(json.dumps(export(db,'owner',sys.argv[2])['markdown'],ensure_ascii=True))
"""
    child = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code, str(s.db.path), v["session_id"]],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 0, child.stderr
    assert json.loads(child.stdout) == output["markdown"]


def sample_refs():
    base = dict(
        source_id="authored-source",
        source_version="version-a",
        reference_kind="AUTHOR_PROPOSED_PLAN",
        review_status="WORK_REVIEWED",
        conditions=["春季；雨天不推荐；作者未亲历"],
        route_association=dict(
            source_id="authored-source",
            object_quote="东桥片区",
            object_locator="body-a:chars:0-4",
            scope="SEGMENT",
        ),
    )
    return [
        dict(
            deepcopy(base),
            claim_id="route-a",
            topic="ROUTE",
            text="甲巷→乙步道",
            locator="body-a:chars:5-12",
        ),
        dict(
            deepcopy(base),
            claim_id="experience-a",
            topic="EXPERIENCE",
            text="东桥片区适合比较沿途树影，喜欢慢逛可少选项目。",
            locator="body-a:chars:13-38",
        ),
    ]


def nodes():
    return [
        dict(
            activity_id="one", name="甲巷", evidence_ids=["route-a"], provenance="SOURCE_REFERENCE"
        ),
        dict(
            activity_id="two",
            name="乙步道",
            evidence_ids=["route-a"],
            provenance="SOURCE_REFERENCE",
        ),
    ]


@pytest.mark.parametrize("destination", ["合成海城", "合成山岭", "另一目的地"])
def test_group_background_never_promotes_individual_features(destination):
    from travel_agent.planning.scoped_context import derive
    from travel_agent.planning.guide_assessment import materials

    refs, acts = sample_refs(), nodes()
    for a in acts:
        a["region"] = destination
    out = derive(acts, refs)
    assert out["source_count"] == 1 and len(out["backgrounds"]) == 1
    assert out["backgrounds"][0]["scope"] == "GROUP_BACKGROUND"
    assert all(r["level"] == "ROUTE_CONTEXT" for r in materials(acts, refs))
    assert out["backgrounds"][0]["conditions"] == refs[1]["conditions"]
    assert out["backgrounds"][0]["reference_kind"] == "AUTHOR_PROPOSED_PLAN"


@pytest.mark.parametrize(
    "change",
    ["other_object", "other_source", "other_version", "unreviewed", "no_object", "substring"],
)
def test_false_links_are_not_created(change):
    from travel_agent.planning.scoped_context import derive

    refs, acts = sample_refs(), nodes()
    if change == "other_object":
        refs[1]["route_association"]["object_locator"] = "body-a:chars:100-104"
    if change == "other_source":
        refs[1]["source_id"] = refs[1]["route_association"]["source_id"] = "another-source"
    if change == "other_version":
        refs[1]["source_version"] = "version-b"
    if change == "unreviewed":
        refs[1]["review_status"] = "PENDING"
    if change == "no_object":
        refs[1]["route_association"] = None
    if change == "substring":
        acts = [dict(acts[0], name="巷")]
    assert not derive(acts, refs)["backgrounds"]
    if change in {"other_object", "no_object"}:
        assert derive(acts, refs)["supplements"]


def test_explicit_direct_experience_without_route_words():
    from travel_agent.planning.scoped_context import derive

    refs = sample_refs()
    refs[1]["route_association"] = None
    refs[1]["text"] = "甲巷适合看树影，喜欢安静氛围可以留更宽松的停留。"
    (row,) = derive(nodes(), refs)["backgrounds"]
    assert row["scope"] == "DIRECT_PLACE" and row["activity_ids"] == ["one"]


def test_context_target_tampering_rejects_only_bad_proposal(scoped):
    from travel_agent.planning.advisory import validate
    from test_advisory_guide import proposal

    s, v = scoped
    _, data = context(s, v)
    good = proposal(data)["proposals"][0]
    bg = data["scoped_context"][0]
    good["context_uses"] = [
        dict(
            context_id=bg["context_id"],
            activity_ids=bg["activity_ids"],
            use="SELECT",
            reason="建议按兴趣少选项目。",
        )
    ]
    for change in (
        dict(context_id="invented"),
        dict(activity_ids=["invented"]),
        dict(reason="每一站都有相同特色"),
    ):
        bad = deepcopy(good)
        bad["context_uses"][0].update(change)
        result = validate(dict(protocol_version=4, proposals=[bad, good]), data)
        assert result["accepted_count"] == result["rejected_count"] == 1


def test_proven_context_alias_is_accepted_and_audited_without_reply_rewrite(scoped):
    from travel_agent.planning.advisory import validate
    from test_advisory_guide import proposal

    s, v = scoped
    _, data = context(s, v)
    bg = data["scoped_context"][0]
    original = next(r for r in data["references"] if r["claim_id"] == bg["citation_id"])
    alias = dict(original, claim_id="verified-card-alias", knowledge_kind="SOURCE_REFERENCE")
    data["references"].append(alias)
    data["allowed_citation_ids"].append(alias["claim_id"])
    raw = proposal(data)
    p = raw["proposals"][0]
    p["citation_ids"] = [
        alias["claim_id"] if i == original["claim_id"] else i for i in p["citation_ids"]
    ]
    p["context_uses"] = [
        dict(
            context_id=bg["context_id"],
            activity_ids=bg["activity_ids"],
            use="COMPARE",
            reason="建议按兴趣少选项目。",
        )
    ]
    before = deepcopy(raw)
    result = validate(raw, data)
    assert result["accepted_count"] == 1
    audit = result["proposals"][0]["normalizations"]
    assert any(a["rule"] == "PROVEN_CONTEXT_CITATION_ALIAS" for a in audit)
    assert raw == before
    for changed in (
        dict(source_id="other"),
        dict(locator="other"),
        dict(conditions=["冬季"]),
        dict(reference_kind="AUTHOR_PROPOSED_PLAN"),
    ):
        bad = deepcopy(data)
        bad["references"][-1].update(changed)
        assert validate(raw, bad)["accepted_count"] == 0


def test_removal_keeps_history_and_drops_unrelated_context(scoped):
    from travel_agent.planning.scoped_context import view

    s, v = scoped
    v = act(s, v, "adopt")
    original = deepcopy(v["adopted"])
    refs = references(s.db, s.scope, v["session_id"])
    assert not view([], refs, [])["backgrounds"]
    v = act(s, v, "preview_combination", activity_ids=[v["draft"]["activities"][0]["activity_id"]])
    assert len(v["guide_view"]["context"]["backgrounds"][0]["activity_ids"]) == 1
    assert v["adopted"] == original


def test_policy_and_other_account_cannot_send_background(scoped):
    s, v = scoped
    with pytest.raises(ValueError, match="SESSION_UNAVAILABLE"):
        PlanningService(s.db, "another").get(v["session_id"])
    s.db.connection.execute(
        "UPDATE source_policies SET policy_json=json_set(policy_json,'$.allow_external_model',json('false'))"
    )
    with pytest.raises(ValueError, match="REFERENCE_UNAVAILABLE"):
        context(s, v)


def test_knowledge_uses_preserved_relation_without_raw_reads(scoped):
    from travel_agent.knowledge.organize import prepare as organize, commit
    from travel_agent.knowledge.planning import attach, payload
    from travel_agent.knowledge.store import binding, no_raw
    from travel_agent.knowledge.cleanup import preview, clear

    s, v = scoped
    pre = organize(s.db, s.scope, v["session_id"])
    cards = commit(s.db, s.scope, v["session_id"], pre["preview_hash"])["cards"]
    route = next(c for c in cards if "ROUTE" in c["tags"])
    normal = PlanningService(s.db, s.scope, daily_workbench=True)
    new = normal.create(PlanCreate(destination="合成青谷", knowledge_first=True), str(uuid4()))
    new = attach(s.db, s.scope, new["session_id"], [binding(route)], new["revision"], True)
    _, st = normal.load(new["session_id"])
    before = payload(s.db, s.scope, st["planning"])
    assert len(before["scoped_context"]) == 1
    impact = preview(s.db, s.scope, [binding(route)])
    clear(s.db, s.scope, [binding(route)], impact["preview_hash"])
    with no_raw(s.db):
        assert payload(s.db, s.scope, st["planning"])["scoped_context"] == before["scoped_context"]
    assert s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0] == ""


def daily_reuse(s, v):
    old = act(s, v, "adopt")
    normal = PlanningService(s.db, s.scope, daily_workbench=True)
    new = normal.create(PlanCreate(destination="合成青谷", request="两天，先给玩法"), str(uuid4()))
    option = next(x for x in new["reuse_options"] if x["session_id"] == old["session_id"])
    new = act(
        normal,
        new,
        "reuse_activities",
        reuse_key=option["key"],
        activity_ids=[a["activity_id"] for a in option["activities"]],
    )
    return normal, new


def model_config(monkeypatch):
    from travel_agent.providers.llm import OpenAICompatibleProvider
    from pydantic import SecretStr

    provider = OpenAICompatibleProvider(
        "https://api.deepseek.com", "authored", SecretStr("fixture"), 120, "json_object"
    )
    monkeypatch.setattr("travel_agent.preview.worker.configured_provider", lambda: provider)
    monkeypatch.setattr("travel_agent.planning.suggestions.configured_provider", lambda: provider)
    monkeypatch.setattr(
        "travel_agent.research.bounded.BoundedBudget.check_provider", lambda *_: None
    )


def test_new_page_permission_binds_context_and_closed_old_permit_is_not_reused(scoped, monkeypatch):
    from test_daily_workbench import permit
    from travel_agent.planning.workbench import DailyBudget

    model_config(monkeypatch)
    s, v = daily_reuse(*scoped)
    _, data = context(s, v)
    assert len(data["scoped_context"]) == 1
    v = permit(s, v, 1)
    _, p = s.load(v["session_id"])
    budget = DailyBudget(s.db, p["planning"]["operation_grant"])
    budget.check_payload(data)
    bad = deepcopy(data)
    bad["scoped_context"][0]["context_id"] = "not-authorized"
    with pytest.raises(ValueError, match="MATERIAL_CHANGED"):
        budget.check_payload(bad)
    act(s, v, "revoke_authorization")
    with pytest.raises(ValueError):
        budget.check_payload(data)


def test_production_mentions_and_mixed_input_keep_independent_context(scoped, monkeypatch):
    from travel_agent.planning.discovery import as_activity

    s, v = daily_reuse(*scoped)
    # Bind this authored cache as current-trip research, just as the research worker does.
    _, state = s.load(v["session_id"])
    state["planning"]["reuse_materials"] = [
        dict(r)
        for r in s.db.connection.execute(
            "SELECT content_id,source_id,content_hash FROM source_contents"
        )
    ]
    state["planning"]["discovery"] = None
    s.db.connection.execute(
        "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
        (json.dumps(state), v["session_id"]),
    )
    from travel_agent.planning.discovery import contents, identify

    cached = contents(s.db, s.scope, v["session_id"], state["planning"])
    assert cached, state["planning"]["reuse_materials"]
    assert identify(cached[0], "合成青谷", "UNDECIDED"), cached[0]["raw_text"]
    v = act(s, v, "discover_places")
    # Synthetic map-confirmation state only; production checked() still verifies cached locators.
    _, st = s.load(v["session_id"])
    p = st["planning"]
    assert p["discovery"]["leads"]
    for lead in p["discovery"]["leads"]:
        lead["identity_status"] = "CHECKED"
        lead["spatial_status"] = "UNKNOWN"
    s.db.connection.execute(
        "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
        (json.dumps(st), v["session_id"]),
    )
    for mixed in (False, True):
        trial = deepcopy(p)
        mention = as_activity(p["discovery"]["leads"][0]).model_dump()
        trial["draft"]["activities"] = [mention] + ([p["draft"]["activities"][1]] if mixed else [])
        data = payload_for(trial, s.db, s.scope, v["session_id"])
        assert data["scoped_context"]
        assert data["activities"][0]["provenance"] == "SOURCE_MENTION"
        assert data["material_support"][0]["level"] == "NAME_ONLY"
        from travel_agent.planning.guide_assessment import references as guide_refs
        from travel_agent.planning.guide_view import project

        assert project(trial, guide_refs(s.db, s.scope, v["session_id"], trial))["context"][
            "backgrounds"
        ]


@pytest.mark.parametrize("change", ["withdraw", "selection", "close"])
def test_late_result_does_not_adopt_stale_context(scoped, monkeypatch, change):
    from test_daily_workbench import permit
    from test_advisory_guide import proposal
    from travel_agent.planning.suggestions import run_worker

    model_config(monkeypatch)
    s, v = daily_reuse(*scoped)
    from datetime import datetime, timezone

    s.db.clock = lambda: datetime.now(timezone.utc)
    v = act(s, permit(s, v, 1), "adopt")
    original = deepcopy(v["adopted"])
    v = act(s, v, "suggest")

    class Model:
        calls = 0

        def structured(self, task, data, schema):
            self.calls += 1
            if change == "withdraw":
                s.db.connection.execute(
                    "UPDATE claims SET deleted_at=? WHERE topic='EXPERIENCE'", (s.db.stamp(),)
                )
            elif change == "selection":
                act(
                    s,
                    s.get(v["session_id"]),
                    "preview_combination",
                    activity_ids=[original["activities"][0]["activity_id"]],
                )
            else:
                act(s, s.get(v["session_id"]), "revoke_authorization")
            return proposal(data)

    model = Model()
    run_worker(s.db.path, v["job"]["job_id"], model)
    current = s.get(v["session_id"])
    assert model.calls == 1
    assert current["adopted"] == original
    assert not current["job"]["proposals"]
    with pytest.raises(ValueError, match="STALE_PROPOSAL"):
        act(s, current, "use_proposal")


def test_repeated_background_text_cannot_bypass_source_limit():
    from travel_agent.planning.scoped_context import attach_context

    data = dict(activities=nodes(), references=sample_refs())
    with pytest.raises(ValueError, match="CONTEXT_INPUT_LIMIT"):
        attach_context(data, {"authored-source": 5990})


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("不能推断每站特色与当前人流。建议只取少数项目。", False),
        ("不据此证明各站氛围或行政归属", False),
        ("不能推断每站特色，但各站都有独特氛围", True),
        ("不推断实际人流，每一站都有同样特色", True),
        ("我不知道，但这些项目属于同一片区", True),
        ("各处都有人少的优势", True),
        ("不必每一站停留，可减少项目", False),
        ("不把整段背景当成每站特色", False),
        ("不把整段背景当成每站特色，但各站都有独特氛围", True),
    ],
)
def test_context_scope_distinguishes_disclaimer_from_assertion(text, blocked):
    from travel_agent.planning.scoped_context import scope_assertion

    assert scope_assertion(text) == blocked


def test_negative_scope_reason_passes_complete_proposal_validation(scoped):
    from travel_agent.planning.advisory import validate
    from test_advisory_guide import proposal

    s, v = scoped
    _, data = context(s, v)
    raw = proposal(data)
    bg = data["scoped_context"][0]
    raw["proposals"][0]["context_uses"] = [
        dict(
            context_id=bg["context_id"],
            activity_ids=bg["activity_ids"],
            use="SELECT",
            reason="可以减少停靠，不能推断每站特色与当前人流。",
        )
    ]
    assert validate(raw, data)["accepted_count"] == 1


def test_legacy_card_missing_relation_does_not_guess_membership():
    from travel_agent.knowledge.planning import card_references
    from travel_agent.planning.scoped_context import derive

    card = dict(
        card_id="legacy",
        version=1,
        card_hash="hash",
        kind="SOURCE_REFERENCE",
        text="甲巷→乙步道",
        conditions=[],
        review_scope="GUIDE_SUGGESTION",
        review_method="WORK_REVIEWED",
        tags=["ROUTE"],
        evidence_links=["route-a"],
    )
    refs = card_references([card])
    assert not derive([dict(nodes()[0], evidence_ids=["legacy"])], refs)["backgrounds"]


def test_card_version_update_during_model_call_rejects_old_context(scoped, monkeypatch):
    from datetime import datetime, timezone
    from travel_agent.knowledge.organize import prepare as organize, commit
    from travel_agent.knowledge.planning import attach
    from travel_agent.knowledge.store import Library, binding
    from travel_agent.planning.suggestions import run_worker
    from test_daily_workbench import permit
    from test_advisory_guide import proposal

    model_config(monkeypatch)
    s, v = scoped
    s.db.clock = lambda: datetime.now(timezone.utc)
    pre = organize(s.db, s.scope, v["session_id"])
    card = next(
        c
        for c in commit(s.db, s.scope, v["session_id"], pre["preview_hash"])["cards"]
        if "ROUTE" in c["tags"]
    )
    normal = PlanningService(s.db, s.scope, daily_workbench=True)
    v = normal.create(
        PlanCreate(destination="合成青谷", request="两天", knowledge_first=True), str(uuid4())
    )
    v = attach(s.db, s.scope, v["session_id"], [binding(card)], v["revision"], True)
    v = act(normal, permit(normal, v, 1), "adopt")
    original = deepcopy(v["adopted"])
    v = act(normal, v, "suggest")

    class Model:
        calls = 0

        def structured(self, task, data, schema):
            self.calls += 1
            assert data["scoped_context"]
            saved = json.loads(
                s.db.connection.execute(
                    "SELECT data_json FROM knowledge_cards WHERE card_id=?", (card["card_id"],)
                ).fetchone()[0]
            )
            saved["unknowns"].append("新版本注明额外未知项")
            Library(s.db, s.scope).save("evidence:" + saved["evidence_links"][0], saved)
            return proposal(data)

    model = Model()
    run_worker(s.db.path, v["job"]["job_id"], model)
    current = normal.get(v["session_id"])
    assert model.calls == 1 and current["job"]["status"] == "FAILED"
    assert current["adopted"] == original
    assert not current["guide_view"]["context"]["backgrounds"]
    with pytest.raises(ValueError):
        act(normal, current, "use_proposal")
