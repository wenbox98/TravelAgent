"""Production knowledge lifecycle, authored fixtures only; network denied by suite."""

from copy import deepcopy
from datetime import timedelta
import json
import sqlite3
import subprocess
import sys
from uuid import uuid4
import pytest
from travel_agent.persistence.database import Database
from travel_agent.planning.flow import PlanningService
from travel_agent.knowledge.store import Library, binding, no_raw
from travel_agent.knowledge.organize import prepare, commit
from travel_agent.knowledge.cleanup import preview, clear
from travel_agent.knowledge.planning import attach, payload
from travel_agent.planning.flow_models import PlanCreate
from travel_agent.planning.suggestions import run_worker
from test_daily_workbench import normal as normal_fixture, permit
from test_place_discovery import discovery as discovery_fixture
from test_planning_flow import act

normal = normal_fixture
discovery = discovery_fixture


def organize(s, old, pattern=False):
    pre = prepare(s.db, s.scope, old["session_id"], pattern)
    return commit(s.db, s.scope, old["session_id"], pre["preview_hash"], pattern)["cards"]


def new(s, cards, **values):
    v = s.create(
        PlanCreate(
            destination="合成青谷",
            knowledge_first=True,
            request="一天，公共交通和步行，10点开始首项",
            planning_mode="DETAILED",
            **values,
        ),
        str(uuid4()),
    )
    return attach(s.db, s.scope, v["session_id"], [binding(c) for c in cards], v["revision"], True)


def test_roles_conditions_idempotence_versions_source_count(normal):
    s, old = normal
    cards = organize(s, old)
    assert len(cards) == 8 and all(c["review_scope"] == "AUTHOR_PROPOSED_PLAN" for c in cards)
    assert all("我计划秋季自驾，还未出发。" in c["conditions"] for c in cards)
    again = organize(s, old)
    assert [binding(c) for c in cards] == [binding(c) for c in again]
    lib = Library(s.db, s.scope)
    assert lib.search(destination="合成青谷")["source_count"] == 1
    pattern = organize(s, old, True)
    assert (
        pattern[0]["kind"] == "PLAN_PATTERN"
        and pattern[0]["review_method"] == "USER_ADOPTED_NOT_TRAVELED"
    )
    data = {
        k: v
        for k, v in cards[0].items()
        if k
        not in {
            "card_id",
            "version",
            "card_hash",
            "raw_availability",
            "raw_retention",
            "validation_basis",
        }
    }
    data["unknowns"].append("规则版本增加的明确未知项")
    newer = lib.save("evidence:" + data["evidence_links"][0], data)
    assert newer["version"] == 2
    with pytest.raises(ValueError, match="STALE"):
        lib.get(binding(cards[0]))


@pytest.mark.parametrize(
    "query,expected",
    [
        ("青谷", 8),
        ("合成地点", 7),
        ("秋季 自驾", 8),
        ("苏州", 0),
        ("' OR 1=1 --", 0),
        ("成都", 0),
        ("秋季，自驾", 8),
    ],
)
def test_keyword_quality(normal, query, expected):
    s, old = normal
    organize(s, old)
    out = Library(s.db, s.scope).search(query)
    assert len(out["cards"]) == expected and not out["sufficient"]
    assert out["mode"] == "LOCAL_KEYWORD_RETRIEVAL" and out["vector"] == "NOT_IMPLEMENTED"
    assert Library(s.db, s.scope).search(destination="苏州")["cards"] == []


def test_scope_policy_test_filter_and_index_repair(normal):
    s, old = normal
    cards = organize(s, old)
    lib = Library(s.db, s.scope)
    assert Library(s.db, "other").search()["cards"] == []
    assert lib.search(since="2999-01-01")["cards"] == []
    s.db.connection.execute("DELETE FROM knowledge_terms")
    s.db.connection.execute("DELETE FROM knowledge_fts")
    assert lib.search("青谷")["cards"] == []
    lib.rebuild()
    assert len(lib.search("青谷")["cards"]) == 8
    row = s.db.connection.execute("SELECT policy_json FROM source_policies LIMIT 1").fetchone()
    p = json.loads(row[0])
    p["allow_persist_derived"] = False
    s.db.connection.execute("UPDATE source_policies SET policy_json=?", (json.dumps(p),))
    assert lib.search()["cards"] == []
    with pytest.raises(ValueError, match="POLICY"):
        lib.get(binding(cards[0]))


def test_discovery_is_mention_not_evidence_and_test_flag(discovery):
    s, v = discovery
    v = act(s, v, "discover_places")
    before = s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    cards = organize(s, v)
    leads = [c for c in cards if c["kind"] == "PLACE_LEAD"]
    assert leads and all(
        c["review_method"] == "MENTION_LOCATED_ONLY"
        and c["spatial_status"] == "UNKNOWN"
        and not c["evidence_links"]
        for c in leads
    )
    assert s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == before
    _, state = s.load(v["session_id"])
    state["planning"]["validation_trip"] = True
    s.db.connection.execute(
        "UPDATE preview_sessions SET state_json=? WHERE session_id=?",
        (json.dumps(state), v["session_id"]),
    )
    cards = organize(s, v)
    assert Library(s.db, s.scope).search()["cards"] == []
    assert Library(s.db, s.scope).search(include_test=True)["cards"]


def test_cleanup_cross_process_and_no_raw_model_input(normal, monkeypatch):
    s, old = normal
    cards = organize(s, old)
    ref = binding(cards[0])
    original = s.db.connection.execute(
        "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
    ).fetchone()[0]
    before = s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0]
    impact = preview(s.db, s.scope, [ref])
    result = clear(s.db, s.scope, [ref], impact["preview_hash"])
    assert result["cleared"] == 1
    assert s.db.connection.execute("SELECT count(*) FROM source_body_blocks").fetchone()[0] == 0
    assert s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == before
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (old["session_id"],)
        ).fetchone()[0]
        == original
    )
    with no_raw(s.db):
        assert Library(s.db, s.scope).get(ref)["validation_basis"] == "HISTORICAL_ATTESTATION"
    code = """
import sys,socket,sqlite3,json
from pathlib import Path
sys.path.insert(0,str(Path('apps/api').resolve()))
def denied(*a,**k):raise AssertionError('FORBIDDEN_FALLBACK')
socket.socket.connect=denied;socket.getaddrinfo=denied
from travel_agent.research.content_store import SourceContentStore
SourceContentStore.load=denied
from travel_agent.persistence.database import Database
from travel_agent.knowledge.store import Library,no_raw,binding
from travel_agent.knowledge.planning import attach,payload
from travel_agent.planning.flow import PlanningService
from travel_agent.planning.flow_models import PlanCreate,PlanAction
allowed=Path(sys.argv[1]).resolve()
def audit(event,args):
 if event=='sqlite3.connect' and Path(args[0]).resolve()!=allowed:denied()
sys.addaudithook(audit)
with Database(allowed) as db:
 c=Library(db,'owner').search('青谷')['cards'][0]
 s=PlanningService(db,'owner',daily_workbench=True)
 v=s.create(PlanCreate(destination='合成青谷',knowledge_first=True),'recovery-create-1')
 v=attach(db,'owner',v['session_id'],[binding(c)],v['revision'],False)
 _,state=s.load(v['session_id']);data=payload(db,'owner',state['planning'])
 assert data['knowledge_mode'] and data['references'] and not data['known_map_values']
 v=s.mutate(v['session_id'],PlanAction(action='adopt',expected_revision=v['revision']),'recovery-adopt-1')
 assert v['adopted']['activities']
 Library(db,'owner').remove([binding(c)])
 assert s.get(v['session_id'])['adopted']==v['adopted']
 try:payload(db,'owner',s.load(v['session_id'])[1]['planning'])
 except ValueError:pass
 else:raise AssertionError('DELETED_KNOWLEDGE_SENT')
 print('RECOVERED_NO_RAW_NO_NETWORK_NO_OTHER_DB')
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", code, str(s.db.path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", ["text", "hash", "missing", "blocks"])
def test_unexpected_raw_damage_not_attestation(normal, change):
    s, old = normal
    cards = organize(s, old)
    c = cards[0]
    cid = c["sources"][0]["content_id"]
    if change == "text":
        s.db.connection.execute(
            "UPDATE source_contents SET normalized_text='broken' WHERE content_id=?", (cid,)
        )
    if change == "hash":
        s.db.connection.execute(
            "UPDATE source_contents SET content_hash=? WHERE content_id=?", ("f" * 64, cid)
        )
    if change == "missing":
        s.db.connection.execute("DELETE FROM source_contents WHERE content_id=?", (cid,))
    if change == "blocks":
        s.db.connection.execute("DELETE FROM source_body_blocks WHERE content_id=?", (cid,))
    with pytest.raises(ValueError):
        Library(s.db, s.scope).get(binding(c))


def test_cleanup_rollback_and_knowledge_delete_separate(normal, monkeypatch):
    s, old = normal
    cards = organize(s, old)
    ref = binding(cards[0])
    impact = preview(s.db, s.scope, [ref])
    before = s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0]
    s.db.connection.execute(
        "CREATE TRIGGER fail_clean BEFORE DELETE ON source_body_blocks BEGIN SELECT RAISE(ABORT,'interrupted'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        clear(s.db, s.scope, [ref], impact["preview_hash"])
    assert s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0] == before
    assert Library(s.db, s.scope).get(ref)["raw_availability"] == "AVAILABLE"
    Library(s.db, s.scope).remove([ref])
    assert Library(s.db, s.scope).search()["source_count"] == 1
    assert s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0] == before
    assert not s.db.connection.execute(
        "SELECT 1 FROM knowledge_terms WHERE card_id=?", (ref["card_id"],)
    ).fetchone()


def test_binding_adopt_and_call_time_revocation(normal):
    s, old = normal
    cards = organize(s, old)
    v = new(s, cards[:1])
    v = permit(s, v, 1)
    _, state = s.load(v["session_id"])
    data = payload(s.db, s.scope, state["planning"])
    assert not any(a["evidence_ids"] for a in data["activities"])
    assert data["knowledge_bindings"] == [binding(cards[0])]

    class Model:
        calls = 0

        def structured(self, *args):
            self.calls += 1
            Library(s.db, s.scope).remove([binding(cards[0])])
            return dict(protocol_version=2, proposals=[])

    model = Model()
    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], model)
    assert model.calls == 1 and s.get(v["session_id"])["job"]["status"] == "FAILED"
    with pytest.raises(ValueError):
        act(s, s.get(v["session_id"]), "adopt")
    assert s.get(old["session_id"])["adopted"] == old["adopted"]


def test_no_attestation_no_card_and_source_withdrawal(normal):
    s, old = normal
    cards = organize(s, old)
    organize(s, old, True)
    raw = deepcopy(cards[0])
    raw["attested_at"] = None
    with pytest.raises(ValueError):
        Library(s.db, s.scope).save("forged", raw)
    Library(s.db, s.scope).remove([binding(cards[0])], withdraw_sources=True)
    assert Library(s.db, s.scope).search()["cards"] == []
    assert s.db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 8


def test_expired_and_policy_expires(normal):
    s, old = normal
    cards = organize(s, old)
    row = s.db.connection.execute("SELECT policy_json FROM source_policies LIMIT 1").fetchone()
    p = json.loads(row[0])
    p["expires_at"] = (s.db.clock() - timedelta(days=1)).isoformat()
    s.db.connection.execute("UPDATE source_policies SET policy_json=?", (json.dumps(p),))
    assert not Library(s.db, s.scope).search()["cards"]
    with pytest.raises(ValueError):
        new(s, cards[:1])


def test_raw_only_sentinel_and_full_copy_scrub(tmp_path, clock):
    from test_candidate_grounding import prepare as fixture_prepare, candidate, accept
    from travel_agent.research.candidate_review import review_candidates
    from test_planning_flow import create

    secret = "AUTHORED_RAW_ONLY_SENTINEL_NO_KNOWLEDGE"
    body = "我计划秋季自驾，还未出发。\n甲路线草案。\nDay1：纸舟路→云台街。\n" + secret
    rows = [
        candidate(
            body.splitlines()[2],
            2,
            "ROUTE",
            [dict(text=body.splitlines()[0], quote=body.splitlines()[0], source_block_id=0)],
        )
    ]
    rows[0]["source_block_ids"].append(0)
    with Database(tmp_path / "sentinel.sqlite3", clock=clock) as db:
        store, runner, _, kw = fixture_prepare(db, clock, rows, body)
        out = runner.execute(**kw)
        review_candidates(
            store,
            attempt_id=out["attempt_id"],
            account_scope="owner",
            decisions={
                0: accept(
                    reference_scope="AUTHOR_PROPOSED_PLAN",
                    route_association=dict(
                        object_quote="甲路线草案。", object_block_id=1, scope="SEGMENT"
                    ),
                )
            },
        )
        s = PlanningService(db, "owner")
        v = create(s, "合成青谷")
        cards = organize(s, v)
        assert cards and secret not in json.dumps(cards)
        # Deliberate historical input copy under an existing task identity.
        db.connection.execute(
            "UPDATE extraction_attempts SET diagnostic_json=?",
            (
                json.dumps(
                    dict(content_id=kw["content_id"], body_blocks=[dict(text=body)], full_text=body)
                ),
            ),
        )
        refs = [binding(cards[0])]
        imp = preview(db, "owner", refs)
        clear(db, "owner", refs, imp["preview_hash"])
        for table in [
            "source_contents",
            "source_body_blocks",
            "extraction_attempts",
            "knowledge_cards",
            "knowledge_terms",
            "knowledge_fts",
        ]:
            assert secret not in json.dumps(
                [tuple(r) for r in db.connection.execute("SELECT * FROM " + table)]
            )
        assert not Library(db, "owner").search(secret)["cards"]
        assert Library(db, "owner").search("纸舟路")["cards"]


def test_quality_corpus_regions_conflicts_and_source_withdrawal(normal):
    s, old = normal
    card = organize(s, old)[0]
    lib = Library(s.db, s.scope)
    clean = {
        k: v
        for k, v in card.items()
        if k
        not in {
            "card_id",
            "version",
            "card_hash",
            "raw_availability",
            "raw_retention",
            "validation_basis",
        }
    }
    # Authored retrieval corpus, using existing synthetic source/attestation chain.
    for i, (region, condition) in enumerate(
        [("苏州", "春节公共交通"), ("成都", "国庆自驾"), ("苏州", "国庆自驾")]
    ):
        data = deepcopy(clean)
        data.update(
            kind="PLACE_LEAD",
            evidence_links=[],
            review_method="MENTION_LOCATED_ONLY",
            review_scope="NAME_ONLY",
            destination=region,
            title="同名云台街",
            text="同名云台街",
            conditions=[condition],
            entities=["云台街"],
        )
        lib.save("authored-quality-" + str(i), data)
    results = lib.search("云台街", destination="苏州")
    assert len(results["cards"]) == 2 and results["source_count"] == 1
    assert (
        results["conflicting_conditions"] == ["国庆自驾", "春节公共交通"]
        and not results["sufficient"]
    )
    assert len(lib.search("春节 公共交通", destination="苏州")["cards"]) == 1
    assert not lib.search("春节", destination="成都")["cards"]
    assert not lib.search("云台街", destination="未知目的地")["cards"]
    lib.remove([binding(card)], withdraw_sources=True)
    assert not lib.search("云台街")["cards"]


def test_index_fallback_and_valid_worker_then_revocation(normal):
    s, old = normal
    cards = organize(s, old)
    lib = Library(s.db, s.scope)
    lib.fts = False
    out = lib.search("青谷")
    assert out["engine"] == "LIMITED_TERM_INDEX_FALLBACK" and out["cards"]
    v = permit(s, new(s, cards[:1]), 1)

    class Planner:
        def structured(self, task, data, schema):
            from travel_agent.planning.arrangements import validate_arrangements

            response = dict(
                protocol_version=2,
                proposals=[
                    dict(
                        title="暂定安排",
                        reason="可修改的停留建议",
                        activities=[
                            dict(
                                activity_id=a["activity_id"],
                                day=1,
                                stay_min=30,
                                stay_max=60,
                                rest_minutes=10,
                            )
                            for a in data["activities"]
                        ],
                        citation_ids=data["allowed_citation_ids"],
                        assumptions=["停留为建议"],
                        unknowns=["交通待核实"],
                        impacts=["节奏可以调整"],
                    )
                ],
            )
            assert validate_arrangements(response, data)["accepted_count"] == 1
            lib.remove([binding(cards[0])])
            return response

    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], Planner())
    actual = s.get(v["session_id"])
    assert actual["job"]["status"] == "FAILED" and not actual["job"]["proposals"]
    assert actual["adopted"] is None


def test_initial_preview_cancel_reuse_without_new_call(normal):
    s, old = normal
    cards = organize(s, old)
    v = permit(s, new(s, cards[:1]), 1)

    class Planner:
        calls = 0

        def structured(self, task, data, schema):
            self.calls += 1
            return dict(
                protocol_version=2,
                proposals=[
                    dict(
                        title="暂定安排",
                        reason="可修改停留",
                        activities=[
                            dict(
                                activity_id=a["activity_id"],
                                day=1,
                                stay_min=30,
                                stay_max=60,
                                rest_minutes=10,
                            )
                            for a in data["activities"]
                        ],
                        citation_ids=data["allowed_citation_ids"],
                        assumptions=["停留是建议"],
                        unknowns=["交通未核实"],
                        impacts=["可调整节奏"],
                    )
                ],
            )

    planner = Planner()
    v = act(s, v, "suggest")
    run_worker(s.db.path, v["job"]["job_id"], planner)
    v = s.get(v["session_id"])
    original = deepcopy(v["draft"])
    assert v["adopted"] is None
    v = act(s, v, "use_proposal")
    assert v["proposal_preview_active"] and v["adopted"] is None
    v = act(s, v, "cancel")
    assert v["draft"] == original and v["job"]["can_preview"]
    v = act(s, act(s, v, "use_proposal"), "adopt")
    assert v["adopted"]["activities"][0]["stay_min"] == 30
    assert planner.calls == 1 and v["operation"]["cumulative_used"]["model"] == 1
    pattern = organize(s, v, True)[0]
    Library(s.db, s.scope).remove([binding(cards[0])])
    with pytest.raises(ValueError):
        Library(s.db, s.scope).get(binding(pattern))


def test_retention_is_explicit_and_never_deletes_or_resets(normal):
    s, old = normal
    cards = organize(s, old)
    lib = Library(s.db, s.scope)
    before = s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0]
    for policy in ["READY_AFTER_ORGANIZED", "SESSION", "PERSISTENT"]:
        assert lib.retention([binding(cards[0])], policy)["automatic_cleanup"] is False
        assert lib.get(binding(cards[0]))["raw_retention"] == [policy]
        assert (
            s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0] == before
        )
    assert s.db.connection.execute("SELECT count(*) FROM research_continuations").fetchone()[0] == 0


def test_cleanup_account_scope_and_raw_expiry_keep_attestation(normal):
    from travel_agent.research.content_store import SourceContentStore

    s, old = normal
    cards = organize(s, old)
    ref = binding(cards[0])
    other = PlanningService(s.db, "other", daily_workbench=True)
    v = other.create(
        PlanCreate(destination="合成青谷", knowledge_first=True), "other-account-library"
    )
    row, state = other.load(v["session_id"])
    raw = s.db.connection.execute("SELECT raw_text FROM source_contents").fetchone()[0]
    state["unrelated_private_text"] = raw
    serialized = json.dumps(state)
    s.db.connection.execute(
        "UPDATE preview_sessions SET state_json=? WHERE session_id=?", (serialized, v["session_id"])
    )
    impact = preview(s.db, s.scope, [ref])
    clear(s.db, s.scope, [ref], impact["preview_hash"])
    assert (
        s.db.connection.execute(
            "SELECT state_json FROM preview_sessions WHERE session_id=?", (v["session_id"],)
        ).fetchone()[0]
        == serialized
    )
    s.db.connection.execute(
        "UPDATE source_contents SET expires_at=?", ((s.db.clock() - timedelta(days=1)).isoformat(),)
    )
    assert SourceContentStore(s.db).purge_expired(s.scope) == 0
    assert Library(s.db, s.scope).get(ref)["validation_basis"] == "HISTORICAL_ATTESTATION"
