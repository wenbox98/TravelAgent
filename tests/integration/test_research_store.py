"""Offline SQLite and in-memory policy boundaries; no browser or provider calls."""

from datetime import timedelta
import json
from pathlib import Path

import pytest

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.persistence.repositories import EvidenceRepository, encode
from travel_agent.research.store import EvidenceStore


def material(fixture_data, *, temporary=False):
    data = fixture_data("evidence.json")
    policy = fixture_data("policies.json")["policies"][int(temporary)]
    if temporary:
        policy.update(allow_read=True, allow_inference=True)
        data.update(policy_id=policy["policy_id"], source_type="XHS", is_synthetic=False)
    return EvidenceBundle(data), SourcePolicy(policy)


def request():
    return {"destination": "合成甲区域", "research_question": "比较路线体验", "days": None}


def register_policy(db, policy):
    db.connection.execute("INSERT INTO source_policies VALUES(?,?,?,?,?)",
                          (policy["policy_id"], policy["version"], encode(policy.to_dict()),
                           policy["reviewed_at"], policy["expires_at"]))


def test_upgrade_v2_preserves_existing_evidence_and_restart_cache(tmp_path, clock, fixture_data):
    path = tmp_path / "research.sqlite3"
    bundle, policy = material(fixture_data)
    with Database(path, clock=clock, target_version=2) as db:
        EvidenceRepository(db).save(bundle, policy, account_scope="local")
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        assert db.version == 9
        assert [item.to_dict() for item in store.lookup(
            "new-question", bundle["destination"], "local",
        )] == [bundle.to_dict()]
        run = store.begin("research", 0, request(), "local")
        assert store.save_evidence(run, 0, bundle, policy, {"body_chars": 123})
        assert store.finish(run, 0, [], {"evidence_count": 1})
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        assert [item.to_dict() for item in store.lookup("research", None, "local")] == [bundle.to_dict()]
        assert store.lookup("research", "另一地区", "local") == ()
        assert store.lookup("research", None, "other") == ()
        assert db.connection.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 9


def test_duplicate_source_reuses_without_overwrite_or_duplicate_claims(clock, fixture_data):
    bundle, policy = material(fixture_data)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        first = store.begin("research", 0, request(), "local")
        assert store.save_evidence(first, 0, bundle, policy, {})
        assert store.finish(first, 0, [], {})
        second = store.begin("research", 0, request(), "local")
        changed = bundle.to_dict()
        changed["claims"][0]["text"] = "新的正文不能默默覆盖已有证据"
        assert store.save_evidence(second, 0, EvidenceBundle(changed), policy, {})
        assert [item.to_dict() for item in store.lookup("research", None, "local")] == [bundle.to_dict()]
        for table in ("sources", "claims", "source_snapshots"):
            assert db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
        assert db.connection.execute("SELECT count(*) FROM research_run_sources").fetchone()[0] == 2
        other = store.begin("other", 0, request(), "other")
        with pytest.raises(PermissionError):
            store.save_evidence(other, 0, bundle, policy, {})
        with pytest.raises(PermissionError):
            store.begin("research", 1, request(), "other")


def test_old_revision_cannot_write_any_result_or_reserve(clock, fixture_data):
    bundle, policy = material(fixture_data)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        old = store.begin("research", 0, request(), "local")
        new = store.begin("research", 1, request() | {"days": 5}, "local")
        assert not store.is_current(old, 0)
        assert store.is_current(new, 1)
        assert not store.save_evidence(old, 0, bundle, policy, {})
        assert not store.record_query(old, 0, "旧查询")
        assert not store.reserve_operation(old, 0, "DETAIL", "note-1", 2)
        assert not store.finish(old, 0, [{"invalid": True}], {"invalid": True})
        for table in ("sources", "claims", "source_snapshots", "source_policies",
                      "research_gaps", "research_queries", "research_ops"):
            assert db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        old_row = db.connection.execute("SELECT * FROM research_runs WHERE run_id=?", (old,)).fetchone()
        assert old_row["status"] == "RUNNING" and old_row["summary_json"] is None
        with pytest.raises(ValueError):
            store.begin("research", 0, request(), "local")
        with pytest.raises(ValueError):
            store.begin("research", 1, request(), "local")


def test_queries_and_attempts_are_durable_unique_and_bounded(tmp_path, clock):
    path = tmp_path / "attempts.sqlite3"
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        run = store.begin("research", 0, request(), "local")
        assert store.record_query(run, 0, " 合成甲区域   交通 ")
        assert not store.record_query(run, 0, "合成甲区域 交通")
        assert not store.reserve_operation(run, 0, "SEARCH", "query-0", 0)
        assert store.reserve_operation(run, 0, "SEARCH", "query-1", 1)
        assert not store.reserve_operation(run, 0, "SEARCH", "query-2", 1)
        assert store.reserve_operation(run, 0, "DETAIL", "source-1", 2)
        assert not store.reserve_operation(run, 0, "DETAIL", "source-1", 2)
        assert store.reserve_operation(run, 0, "DETAIL", "source-1:fallback", 2)
        assert not store.reserve_operation(run, 0, "DETAIL", "source-2", 2)
        assert store.operations(run) == {"search": 1, "detail": 2}
        assert store.finish(run, 0, [], {})
        assert not store.reserve_operation(run, 0, "SEARCH", "query-3", 3)
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        assert store.operations(run) == {"search": 1, "detail": 2}
        assert store.queries("research") == {"合成甲区域 交通"}
        second = store.begin("research", 1, request() | {"days": 5}, "local")
        assert not store.reserve_operation(second, 1, "DETAIL", "source-1", 2)
        assert not store.reserve_operation(second, 1, "SEARCH", "query-1", 1)
        assert store.operations(second) == {"search": 0, "detail": 0}


def test_temporary_unknown_evidence_is_ram_only_and_summary_is_metadata(clock, fixture_data):
    bundle, policy = material(fixture_data, temporary=True)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=True)
        run = store.begin("research", 0, request(), "local")
        assert store.save_evidence(run, 0, bundle, policy, {
            "body_chars": 123, "image_count": 2, "identity_match": True,
            "extraction_mode": "LOCAL_EXTRACTIVE", "body": "FORBIDDEN_RAW_BODY",
            "url": "https://example.invalid/?xsec_token=SECRET_XSEC_VALUE",
        })
        assert store.lookup("research", None, "local") == (bundle,)
        assert store.lookup("research", None, "other") == ()
        assert store.finish(run, 0, [{"gap_id": "TRANSPORT", "description": "交通依据不足",
                                      "topics": ["TRANSPORT"], "status": "UNKNOWN"}], {
            "stop_reason": "BUDGET_EXHAUSTED", "operations": {"search": 0, "detail": 0},
            "evidence_count": 1, "materials": bundle.to_dict(), "body": "FORBIDDEN_RAW_BODY",
        })
        sql_dump = "\n".join(db.connection.iterdump())
        for private in (bundle["claims"][0]["text"], bundle["source_title"],
                        "FORBIDDEN_RAW_BODY", "SECRET_XSEC_VALUE", "https://"):
            assert private not in sql_dump
        assert db.connection.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0
        assert db.connection.execute("SELECT count(*) FROM research_gaps").fetchone()[0] == 1
        assert EvidenceStore(db, temporary=True).lookup("research", None, "local") == ()


def test_temporary_requires_memory_and_unknown_does_not_grant_storage(tmp_path, clock, fixture_data):
    bundle, policy = material(fixture_data, temporary=True)
    with Database(tmp_path / "not-temporary.sqlite3", clock=clock) as db:
        with pytest.raises(ValueError):
            EvidenceStore(db, temporary=True)
        store = EvidenceStore(db)
        run = store.begin("research", 0, request(), "local")
        with pytest.raises(PermissionError):
            store.save_evidence(run, 0, bundle, policy, {})
        assert db.connection.execute("SELECT count(*) FROM source_policies").fetchone()[0] == 0


def test_temporary_result_is_not_reusable_after_outer_sql_rollback(clock, fixture_data):
    bundle, policy = material(fixture_data, temporary=True)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=True)
        run = store.begin("research", 0, request(), "local")
        with pytest.raises(RuntimeError), db.transaction():
            assert store.save_evidence(run, 0, bundle, policy, {})
            raise RuntimeError("rollback")
        assert store.lookup("research", bundle["destination"], "local") == ()
        assert store.save_evidence(run, 0, bundle, policy, {})
        assert store.lookup("research", None, "local") == (bundle,)


@pytest.mark.parametrize("temporary", [False, True])
def test_cache_rechecks_latest_policy_and_rejects_policy_downgrade(clock, fixture_data, temporary):
    bundle, policy = material(fixture_data, temporary=temporary)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=temporary)
        run = store.begin("research", 0, request(), "local")
        store.save_evidence(run, 0, bundle, policy, {})
        revoked = SourcePolicy(policy.to_dict() | {"version": 2, "allow_read": False})
        register_policy(db, revoked)
        assert store.lookup("research", None, "local") == ()
        with pytest.raises(PermissionError):
            store.save_evidence(run, 0, bundle, policy, {})


@pytest.mark.parametrize("temporary", [False, True])
def test_register_policy_revokes_cached_rights_before_lookup(clock, fixture_data, temporary):
    bundle, policy = material(fixture_data, temporary=temporary)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=temporary)
        run = store.begin("research", 0, request(), "local")
        store.save_evidence(run, 0, bundle, policy, {})
        assert store.finish(run, 0, [], {})
        current = store.begin("research", 0, request(), "local")
        revoked = SourcePolicy(policy.to_dict() | {"version": 2, "allow_read": False})
        assert store.register_policy(current, 0, revoked)
        assert store.lookup("research", None, "local") == ()
        with pytest.raises(PermissionError):
            store.register_policy(current, 0, policy)
        with pytest.raises(ValueError):
            store.register_policy(current, 0, SourcePolicy(revoked.to_dict() | {"allow_read": True}))
        assert store.lookup("research", None, "local") == ()
        assert db.connection.execute("SELECT max(version) FROM source_policies").fetchone()[0] == 2


def test_register_policy_stale_result_cannot_replace_current_rights(clock, fixture_data):
    _, policy = material(fixture_data)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        old = store.begin("research", 0, request(), "local")
        current = store.begin("research", 1, request() | {"days": 5}, "local")
        assert not store.register_policy(old, 0, policy)
        assert db.connection.execute("SELECT count(*) FROM source_policies").fetchone()[0] == 0
        assert store.register_policy(current, 1, policy)
        revoked = SourcePolicy(policy.to_dict() | {"version": 2, "allow_read": False})
        assert not store.register_policy(old, 0, revoked)
        assert db.connection.execute("SELECT max(version) FROM source_policies").fetchone()[0] == 1


@pytest.mark.parametrize("temporary", [False, True])
def test_cache_expiry_and_same_version_mutation_fail_closed(clock, fixture_data, temporary):
    bundle, policy = material(fixture_data, temporary=temporary)
    policy = SourcePolicy(policy.to_dict() | {"expires_at": (clock() + timedelta(hours=1)).isoformat()})
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=temporary)
        run = store.begin("research", 0, request(), "local")
        store.save_evidence(run, 0, bundle, policy, {})
        with pytest.raises(ValueError):
            store.save_evidence(run, 0, bundle,
                                SourcePolicy(policy.to_dict() | {"basis_note": "改变必须升版"}), {})
        db.clock = lambda: clock() + timedelta(hours=2)
        assert store.lookup("research", None, "local") == ()


@pytest.mark.parametrize("flag,value", [("allow_read", False), ("allow_inference", False),
                                        ("allow_external_model", True)])
def test_unknown_temporary_policy_requires_explicit_local_permissions(clock, fixture_data, flag, value):
    bundle, policy = material(fixture_data, temporary=True)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=True)
        run = store.begin("research", 0, request(), "local")
        with pytest.raises(PermissionError):
            store.save_evidence(run, 0, bundle, SourcePolicy(policy.to_dict() | {flag: value}), {})


def test_sensitive_metadata_rejected_and_failed_finish_rolls_back(clock):
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db)
        with pytest.raises(ValueError, match="研究元信息"):
            store.begin("research", 0, request() | {"research_question": "Cookie: SECRET_COOKIE"}, "local")
        run = store.begin("research", 0, request(), "local")
        with pytest.raises(ValueError):
            store.record_query(run, 0, "https://example.invalid/?xsec_token=hidden")
        with pytest.raises(ValueError):
            store.finish(run, 0, [{"gap_id": "TIME", "description": "需要时间信息"}],
                         {"diagnostic": "SECRET_AUTHORIZATION"})
        assert store.is_current(run, 0)
        assert db.connection.execute("SELECT count(*) FROM research_gaps").fetchone()[0] == 0
        assert store.finish(run, 0, [], {"evidence_count": 0})
        summary = db.connection.execute("SELECT summary_json FROM research_runs").fetchone()[0]
        assert json.loads(summary) == {"evidence_count": 0}


def quality_material(fixture_data):
    bundle, policy = material(fixture_data)
    data = bundle.to_dict()
    locator = "note-body:v2:STATE:" + "a" * 64 + f":chars:0-{len(data['claims'][0]['text'])}"
    data["claims"][0].update(locator=locator, confidence=0.6)
    data["claim_metadata"] = {data["claims"][0]["claim_id"]: {
        "source_block_ids": [0], "body_origin": "STATE", "extraction_method": "MOCK",
        "extraction_basis": "合成正文直接引用", "confidence_level": "MEDIUM",
        "applicable_conditions": [], "canonical_relation": "EQUAL",
        "truncation_risk": False, "block_locators": [locator],
    }}
    return EvidenceBundle(data), policy


def test_v4_metadata_constraints_and_report_restore(tmp_path, clock, fixture_data):
    bundle, policy = quality_material(fixture_data)
    path = tmp_path / "quality.sqlite3"
    with Database(path, clock=clock, target_version=3):
        pass
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        run = store.begin("quality", 1, request() | {"days": 5, "no_self_drive": True}, "local")
        store.save_evidence(run, 1, bundle, policy, {"body_chars": 17})
        assert store.finish(run, 1, [{"gap_id": "DAYS_FIT", "description": "五天适配性未核实"}], {
            "source_count": 1, "evidence_count": 1, "body": "SECRET_RAW_BODY_NOT_FOR_REPORT",
            "coverage": [{"question_id": "Q1_ROUTES", "status": "SUPPORTED", "claim_count": 1,
                          "source_count": 1, "reason": "DIRECT_GROUNDED_REFERENCE"}],
            "locator_coverage": 1.0, "freshness": {"STABLE_EXPERIENCE": 1},
        })
    with Database(path, clock=clock) as db:
        store = EvidenceStore(db)
        assert store.lookup("quality", None, "local")[0].to_dict() == bundle.to_dict()
        restored = store.load_report("quality", "local")
        assert restored["rebuild_required"] is True
        assert restored["claim_ids"] == [bundle["claims"][0]["claim_id"]]
        assert restored["source_ids"] == [bundle["source_id"]]
        assert restored["summary"]["coverage"][0]["status"] == "SUPPORTED"
        assert {item["name"]: item["value"] for item in restored["constraints"]} == {
            "days": 5, "no_self_drive": True,
        }
        assert store.load_report("quality", "other") is None
        assert "SECRET_RAW_BODY_NOT_FOR_REPORT" not in "\n".join(db.connection.iterdump())
        current = store.begin("quality", 1, request() | {"days": 5, "no_self_drive": True}, "local")
        store.register_policy(current, 1, SourcePolicy(policy.to_dict() | {
            "version": 2, "allow_read": False,
        }))
        assert store.load_report("quality", "local") is None


def test_clear_cache_is_scoped_atomic_and_does_not_touch_profile(tmp_path, clock, fixture_data):
    bundle, policy = quality_material(fixture_data)
    profile = tmp_path / "separate-browser-profile" / "sentinel"
    profile.parent.mkdir()
    profile.write_text("profile-must-remain", encoding="utf-8")
    with Database(tmp_path / "clear.sqlite3", clock=clock) as db:
        store = EvidenceStore(db)
        old_run = None
        for scope in ("local", "other"):
            data = bundle.to_dict()
            old_claim = data["claims"][0]["claim_id"]
            source_id, claim_id = "source-" + scope, "claim-" + scope
            data["source_id"] = source_id
            data["claims"][0].update(source_id=source_id, claim_id=claim_id)
            data["claim_metadata"] = {claim_id: data["claim_metadata"][old_claim]}
            run = store.begin("research-" + scope, 0, request() | {"days": 5}, scope)
            if scope == "local":
                old_run = run
            store.save_evidence(run, 0, EvidenceBundle(data), policy, {})
            store.record_query(run, 0, "合成交通")
            store.reserve_operation(run, 0, "SEARCH", "query-1", 1)
            store.finish(run, 0, [{"gap_id": "DAYS_FIT", "description": "五天适配性未核实"}], {})
            db.connection.execute(
                "INSERT INTO chunks(chunk_id,source_id,text,pretokenized_text,metadata_json,content_hash) "
                "VALUES(?,?,?,?,'{}','synthetic')", ("chunk-" + scope, source_id, "测试文本", "测试文本"),
            )
            db.connection.execute("INSERT INTO chunks_fts VALUES(?,?)", ("chunk-" + scope, "测试文本"))
            db.connection.execute("INSERT INTO lineage VALUES(?, 'research_report', ?)", (source_id, run))
        db.connection.execute("CREATE TRIGGER reject_clear BEFORE DELETE ON sources "
                              "WHEN OLD.account_scope='local' BEGIN SELECT RAISE(ABORT,'blocked'); END")
        with pytest.raises(Exception, match="blocked"):
            store.clear_research_cache("local")
        assert store.load_report("research-local", "local") is not None
        assert db.connection.execute("SELECT count(*) FROM research_constraints").fetchone()[0] == 2
        db.connection.execute("DROP TRIGGER reject_clear")
        counts = store.clear_research_cache("local")
        assert counts["sources"] == counts["questions"] == 1
        assert store.load_report("research-local", "local") is None
        assert store.lookup("research-local", None, "local") == ()
        assert not store.finish(old_run, 0, [], {})
        assert store.load_report("research-other", "other") is not None
        for table in ("research_questions", "research_runs", "research_constraints", "research_reports",
                      "research_gaps", "research_queries", "research_ops", "source_snapshots",
                      "research_run_sources", "sources", "claims", "chunks", "chunks_fts", "lineage"):
            assert db.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
        assert db.connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert profile.read_text(encoding="utf-8") == "profile-must-remain"


def test_clear_temporary_cache_invalidates_old_results(clock, fixture_data):
    bundle, policy = material(fixture_data, temporary=True)
    with Database(Path(":memory:"), clock=clock) as db:
        store = EvidenceStore(db, temporary=True)
        old = store.begin("research", 0, request(), "local")
        store.save_evidence(old, 0, bundle, policy, {})
        store.clear_research_cache("local")
        assert store.lookup("research", bundle["destination"], "local") == ()
        assert not store.save_evidence(old, 0, bundle, policy, {})
