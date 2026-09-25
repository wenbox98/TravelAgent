import sqlite3
import pytest
from travel_agent.persistence.database import Database
from travel_agent.persistence.repositories import TripRepository, OperationRepository, EvidenceRepository
from travel_agent.domain.models import Trip, EvidenceBundle, SourcePolicy


def trip_data(fixture_data):
    return {"trip_id": "trip-test", "revision": 0, "phase": "INTAKE", "original_request": "国庆从成都去川西玩", "intent": fixture_data("trip-intent.json"), "selected_ids": [], "locked_ids": [], "overview": None, "budget": None, "is_synthetic": True}


def test_migration_restart_and_upgrade(tmp_path, clock, fixture_data):
    path = tmp_path / "test.sqlite3"
    with Database(path, clock=clock, target_version=1) as db:
        TripRepository(db).create(Trip(trip_data(fixture_data)))
    with Database(path, clock=clock) as db:
        assert db.version == 6
        assert TripRepository(db).get("trip-test")["intent"]["transport"] is None
    with Database(path, clock=clock) as db:
        assert db.connection.execute("SELECT count(*) FROM trips").fetchone()[0] == 1
        assert db.connection.execute("SELECT count(*) FROM schema_version").fetchone()[0] == 6


def test_foreign_key_and_transaction_rollback(tmp_path, clock, fixture_data):
    with Database(tmp_path / "test.sqlite3", clock=clock) as db:
        with pytest.raises(sqlite3.IntegrityError), db.transaction():
            TripRepository(db).create(Trip(trip_data(fixture_data)))
            db.connection.execute("INSERT INTO claims(claim_id,source_id,topic,text,kind,locator,support) VALUES('bad','missing','ROUTE','synthetic','AUTHOR_OPINION','text:1','UNKNOWN')")
        assert db.connection.execute("SELECT count(*) FROM trips").fetchone()[0] == 0


def test_policy_blocks_storage_and_deletion_cascades(tmp_path, clock, fixture_data):
    with Database(tmp_path / "test.sqlite3", clock=clock) as db:
        repo = EvidenceRepository(db)
        evidence = EvidenceBundle(fixture_data("evidence.json"))
        policy = SourcePolicy(fixture_data("policies.json")["policies"][0])
        repo.save(evidence, policy, account_scope="synthetic-local")
        assert repo.get(evidence["source_id"], "synthetic-local").to_dict() == evidence.to_dict()
        assert repo.get(evidence["source_id"], "other-account") is None
        with pytest.raises(PermissionError):
            repo.save(evidence, SourcePolicy(fixture_data("policies.json")["policies"][1]), account_scope="synthetic-local")
        repo.delete(evidence["source_id"], "synthetic-local")
        assert db.connection.execute("SELECT count(*) FROM claims").fetchone()[0] == 0


def test_operation_idempotency_and_terminal_state(tmp_path, clock, fixture_data):
    with Database(tmp_path / "test.sqlite3", clock=clock) as db:
        TripRepository(db).create(Trip(trip_data(fixture_data)))
        repo = OperationRepository(db)
        repo.create_context("research-test", "trip-test", "job-test", "synthetic-local")
        first = repo.reserve("operation-test", "unique-key", "research-test", "job-test", "DETAIL", "fingerprint")
        assert repo.reserve("another-id", "unique-key", "research-test", "job-test", "DETAIL", "fingerprint")["operation_id"] == first["operation_id"]
        with pytest.raises(ValueError):
            repo.reserve("another-id", "unique-key", "research-test", "job-test", "DETAIL", "different")
        repo.transition("operation-test", "RESERVED", "DISPATCHED")
        repo.transition("operation-test", "DISPATCHED", "FAILED")
        assert repo.get("operation-test")["attempts"] == 1
        assert repo.get("operation-test")["http_count"] is None
        with pytest.raises(ValueError):
            repo.transition("operation-test", "FAILED", "DISPATCHED")


def test_failed_upgrade_rolls_back_schema_and_preserves_data(tmp_path, clock):
    path = tmp_path / "bad-v1.sqlite3"
    with Database(path, clock=clock, target_version=1) as db:
        db.connection.execute("INSERT INTO source_policies VALUES('synthetic',1,'{}',NULL,NULL)")
        db.connection.execute("INSERT INTO sources(source_id,provider,account_scope,completeness,policy_id,policy_version,fetched_at,is_synthetic) VALUES('legacy','synthetic','local','INVALID','synthetic',1,'2026-09-22',1)")
    with pytest.raises(ValueError):
        Database(path, clock=clock)
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT max(version) FROM schema_version").fetchone()[0] == 1
        assert con.execute("SELECT completeness FROM sources").fetchone()[0] == "INVALID"
        assert "confidence" not in {r[1] for r in con.execute("PRAGMA table_info(claims)")}


def test_unknown_database_and_downgrade_rejected(tmp_path, clock):
    path = tmp_path / "unknown.sqlite3"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE user_data(value TEXT)")
    with pytest.raises(ValueError):
        Database(path, clock=clock)
    path = tmp_path / "current.sqlite3"
    with Database(path, clock=clock):
        pass
    with pytest.raises(ValueError):
        Database(path, clock=clock, target_version=1)


def test_expired_policy_prevents_reuse(tmp_path, clock, fixture_data):
    from datetime import timedelta
    path = tmp_path / "expired.sqlite3"
    policy = fixture_data("policies.json")["policies"][0]
    policy["expires_at"] = (clock() + timedelta(hours=1)).isoformat()
    with Database(path, clock=clock) as db:
        EvidenceRepository(db).save(EvidenceBundle(fixture_data("evidence.json")), SourcePolicy(policy), account_scope="local")
    with Database(path, clock=lambda: clock() + timedelta(hours=2)) as db:
        assert EvidenceRepository(db).get("source-synthetic-a", "local") is None
