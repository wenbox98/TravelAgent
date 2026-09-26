from datetime import datetime
import json

from travel_agent.domain.models import EvidenceBundle, ResearchSession, SourcePolicy, Trip
from travel_agent.domain.source_policy import has_usage_basis, scope_allowed
from travel_agent.settings import PROJECT_ROOT


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class TripRepository:
    def __init__(self, db):
        self.db = db

    def create(self, trip: Trip):
        if trip["overview"] is not None or trip["budget"] is not None:
            raise ValueError("T01 仅创建需求与选择快照，结果需后续业务仓储保存")
        with self.db.transaction() as con:
            con.execute("INSERT INTO trips VALUES(?,?,?,?,?,?,?,?)", (trip["trip_id"], trip["original_request"], trip["revision"], trip["phase"], encode(trip["intent"]), self.db.stamp(), self.db.stamp(), int(trip["is_synthetic"])))
            con.execute("INSERT INTO trip_revisions VALUES(?,?,?,?,?,?,?)", (trip["trip_id"], trip["revision"], None, encode(trip["selected_ids"]), encode(trip["locked_ids"]), None, self.db.stamp()))
        return trip

    def get(self, trip_id):
        row = self.db.connection.execute("SELECT t.*, r.selection_json, r.locked_json FROM trips t JOIN trip_revisions r ON t.trip_id=r.trip_id AND t.current_revision=r.revision WHERE t.trip_id=?", (trip_id,)).fetchone()
        if row is None:
            return None
        return Trip({"trip_id": row["trip_id"], "original_request": row["original_request"], "revision": row["current_revision"], "phase": row["phase"], "intent": json.loads(row["intent_json"]), "selected_ids": json.loads(row["selection_json"]), "locked_ids": json.loads(row["locked_json"]), "overview": None, "budget": None, "is_synthetic": bool(row["is_synthetic"])})


class OperationRepository:
    """Durable attempt states only; account budget scheduling belongs to T04."""
    TRANSITIONS = {"RESERVED": {"DISPATCHED", "CANCELED"}, "DISPATCHED": {"COMPLETED", "FAILED", "UNKNOWN_OUTCOME"}}

    def __init__(self, db):
        self.db = db

    def create_context(self, research_id, trip_id, job_id, account_scope, revision=0, generation=0):
        defaults = json.loads((PROJECT_ROOT / "config/defaults.json").read_text(encoding="utf-8"))
        session = ResearchSession({"research_session_id": research_id, "trip_id": trip_id, "account_scope": account_scope, "budget": defaults["session_hard_budget"], "spent": {"search_ops": 0, "detail_ops": 0, "vision_images": 0}, "generation": generation, "policy_version": 1, "created_at": self.db.stamp(), "closed_at": None})
        with self.db.transaction() as con:
            current = con.execute("SELECT current_revision FROM trips WHERE trip_id=?", (trip_id,)).fetchone()
            if current is None or current[0] != revision:
                raise ValueError("旅行版本不匹配")
            con.execute("INSERT INTO research_sessions(research_session_id,trip_id,account_scope,budget_json,spent_json,generation,policy_version,created_at,closed_at) VALUES(?,?,?,?,?,?,?,?,?)", (research_id, trip_id, account_scope, encode(session["budget"]), encode(session["spent"]), generation, 1, self.db.stamp(), None))
            con.execute("INSERT INTO jobs(job_id,trip_id,research_session_id,revision,generation,status,phase,safe_state_json,created_at,updated_at) VALUES(?,?,?,?,?,'QUEUED','RESEARCH_OVERVIEW','{}',?,?)", (job_id, trip_id, research_id, revision, generation, self.db.stamp(), self.db.stamp()))
        return session

    def get(self, operation_id):
        row = self.db.connection.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        return dict(row) if row else None

    def reserve(self, operation_id, operation_key, research_id, job_id, kind, fingerprint):
        with self.db.transaction() as con:
            job = con.execute("SELECT * FROM jobs WHERE job_id=? AND research_session_id=?", (job_id, research_id)).fetchone()
            if job is None or job["status"] not in {"QUEUED", "RUNNING"}:
                raise ValueError("任务不允许预留操作")
            previous = con.execute("SELECT * FROM operations WHERE operation_key=?", (operation_key,)).fetchone()
            if previous:
                if (previous["research_session_id"], previous["job_id"], previous["kind"], previous["request_fingerprint"], previous["revision"], previous["generation"]) != (research_id, job_id, kind, fingerprint, job["revision"], job["generation"]):
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return dict(previous)
            con.execute("INSERT INTO operations(operation_id,operation_key,research_session_id,job_id,revision,generation,kind,request_fingerprint,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'RESERVED',?,?)", (operation_id, operation_key, research_id, job_id, job["revision"], job["generation"], kind, fingerprint, self.db.stamp(), self.db.stamp()))
            return self.get(operation_id)

    def transition(self, operation_id, expected_status, status):
        if status not in self.TRANSITIONS.get(expected_status, set()):
            raise ValueError("非法操作状态迁移")
        with self.db.transaction() as con:
            count = con.execute("UPDATE operations SET status=?, attempts=attempts+?, updated_at=? WHERE operation_id=? AND status=?", (status, int(status == "DISPATCHED"), self.db.stamp(), operation_id, expected_status)).rowcount
            if count != 1:
                raise ValueError("操作状态已变化")
        return self.get(operation_id)


class EvidenceRepository:
    """T01 structured round-trip; no raw text cache, vector index or research engine."""
    def __init__(self, db):
        self.db = db

    def permitted(self, policy):
        now = self.db.clock()
        return (has_usage_basis(policy) and policy["allow_read"] and policy["allow_persist_metadata"] and policy["allow_persist_derived"]
                and policy["reviewed_at"] is not None and datetime.fromisoformat(policy["reviewed_at"]) <= now
                and (policy["expires_at"] is None or datetime.fromisoformat(policy["expires_at"]) > now))

    def model_review_valid(self, assessment, source_id, scope, *, require_candidate=True):
        if assessment.get('context_review_status') == 'LOCAL_REVALIDATION':
            return self.local_review_valid(assessment, source_id, scope)
        if assessment.get('context_review_status') != 'MODEL_CONTEXT_REVIEWED':
            return True
        if self.db.version < 12:
            return False
        row = self.db.connection.execute("SELECT r.results_json,c.context_status,c.claim_id,c.candidate_json FROM context_review_runs r "
            "JOIN extraction_candidates c ON c.attempt_id=r.attempt_id JOIN extraction_attempts a ON a.attempt_id=r.attempt_id "
            "JOIN source_contents s ON s.content_id=a.content_id WHERE r.review_id=? AND r.attempt_id=? AND r.account_scope=? "
            "AND s.source_id=? AND s.account_scope=? AND r.status='COMPLETED' AND r.mode='RUNTIME' AND c.candidate_index=?",
            (assessment.get('context_review_id'),assessment.get('audit_attempt_id'),scope,source_id,scope,assessment.get('audit_candidate_index'))).fetchone()
        if row is None or (require_candidate and row['context_status']!='ACCEPTED'):
            return False
        approved = next((r['program'] for r in json.loads(row['results_json']) if r['candidate_index']==assessment.get('audit_candidate_index')),None)
        ref = assessment.get('reference_selection',{})
        original = json.loads(row['candidate_json']).get('reference_selection',{})
        return bool(approved and approved['action']=='ACCEPT' and ref.get('statement')==original.get('statement')
            and assessment.get('reference_scope')==approved.get('reference_scope')
            and {s['span_id'] for s in ref.get('conditions',[])}==set(approved.get('context_span_ids',[])))

    def local_review_valid(self, assessment, source_id, scope):
        if self.db.version < 13:
            return False
        from travel_agent.research.review_replay import verify_record
        from travel_agent.research.store import EvidenceStore
        try:
            row = verify_record(EvidenceStore(self.db), assessment.get('local_revalidation_id'), scope)
        except (ValueError, PermissionError):
            return False
        # EVALUATION can only exercise the persistence validator inside its rolled-back transaction.
        if row['mode'] != 'RUNTIME' and row['status'] != 'VALIDATING':
            return False
        bound = json.loads(row['binding_json'])
        index = assessment.get('audit_candidate_index')
        approved = next((i['program'] for i in json.loads(row['results_json']) if i['candidate_index'] == index), None)
        mapping = self.db.connection.execute('SELECT claim_id FROM revalidation_claims WHERE revalidation_id=? AND candidate_index=?', (row['revalidation_id'], index)).fetchone()
        original = self.db.connection.execute('SELECT candidate_json FROM extraction_candidates WHERE attempt_id=? AND candidate_index=?', (bound['attempt_id'], index)).fetchone()
        ref = assessment.get('reference_selection', {})
        return bool(mapping and original and approved and approved['action'] == 'ACCEPT'
            and bound['source_id'] == source_id and bound['account_scope'] == scope
            and bound['attempt_id'] == assessment.get('audit_attempt_id')
            and row['review_id'] == assessment.get('context_review_id')
            and ref.get('statement') == json.loads(original[0])['reference_selection']['statement']
            and assessment.get('reference_scope') == approved.get('reference_scope')
            and assessment.get('duration_scope') == approved.get('duration_scope')
            and {s['span_id'] for s in ref.get('conditions', [])} == set(approved.get('context_span_ids', [])))

    def require_model_review(self, evidence, scope):
        for assessment in evidence.get('claim_metadata',{}).values():
            if not self.model_review_valid(assessment,evidence['source_id'],scope,require_candidate=False):
                raise ValueError('MODEL_REVIEW_LINEAGE_REQUIRED')

    def save(self, evidence: EvidenceBundle, policy: SourcePolicy, *, account_scope):
        self.require_model_review(evidence,account_scope)
        if (not self.permitted(policy) or policy["policy_id"] != evidence["policy_id"]
            or not scope_allowed(policy, account_scope)):
            raise PermissionError("来源策略不允许保存证据")
        if evidence["is_synthetic"] and policy["basis"] != "SYNTHETIC":
            raise PermissionError("合成证据需要合成来源策略")
        claim_metadata = evidence.to_dict().get("claim_metadata")
        if claim_metadata is not None and self.db.version < 4:
            raise ValueError("证据质量元信息需要数据库 v4")
        with self.db.transaction() as con:
            existing = con.execute("SELECT account_scope FROM sources WHERE source_id=?", (evidence["source_id"],)).fetchone()
            if existing:
                raise ValueError("来源已存在，禁止隐式跨账号覆盖或替换")
            previous = con.execute("SELECT policy_json FROM source_policies WHERE policy_id=? AND version=?", (policy["policy_id"], policy["version"])).fetchone()
            if previous and json.loads(previous[0]) != policy.to_dict():
                raise ValueError("策略变化必须递增版本")
            con.execute("INSERT OR IGNORE INTO source_policies VALUES(?,?,?,?,?)", (policy["policy_id"], policy["version"], encode(policy.to_dict()), policy["reviewed_at"], policy["expires_at"]))
            con.execute("INSERT INTO sources(source_id,provider,account_scope,title,completeness,policy_id,policy_version,fetched_at,published_at,travel_occurred_at,is_synthetic,source_type,destination,applicable_conditions_json,missing_fields_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (evidence["source_id"], evidence["source_type"], account_scope, evidence["source_title"], evidence["completeness"], policy["policy_id"], policy["version"], evidence["fetched_at"], evidence["source_published_at"], evidence["travel_occurred_at"], int(evidence["is_synthetic"]), evidence["source_type"], evidence["destination"], encode(evidence["applicable_conditions"]), encode(evidence["missing_fields"])))
            if claim_metadata is not None:
                con.execute("UPDATE sources SET claim_metadata_json=? WHERE source_id=?",
                            (encode(claim_metadata), evidence["source_id"]))
            for claim in evidence["claims"]:
                con.execute("INSERT INTO claims(claim_id,source_id,topic,text,kind,locator,support,valid_from,valid_until,confidence) VALUES(?,?,?,?,?,?,?,?,?,?)", tuple(claim[k] for k in ("claim_id", "source_id", "topic", "text", "kind", "locator", "support", "valid_from", "valid_until", "confidence")))

    def get(self, source_id, account_scope):
        row = self.db.connection.execute("SELECT s.*,p.policy_json FROM sources s JOIN source_policies p ON s.policy_id=p.policy_id AND s.policy_version=p.version WHERE s.source_id=? AND s.account_scope=? AND s.deleted_at IS NULL", (source_id, account_scope)).fetchone()
        if row is None:
            return None
        policy = SourcePolicy(json.loads(row["policy_json"]))
        if not self.permitted(policy) or not scope_allowed(policy, account_scope):
            return None
        claims = []
        for claim in self.db.connection.execute("SELECT * FROM claims WHERE source_id=? AND deleted_at IS NULL ORDER BY rowid", (source_id,)):
            metadata = json.loads(row['claim_metadata_json'] or '{}') if 'claim_metadata_json' in row.keys() else {}
            if not self.model_review_valid(metadata.get(claim['claim_id'],{}),source_id,account_scope):
                continue
            claims.append({k: claim[k] for k in ("claim_id", "source_id", "topic", "text", "kind", "locator", "support", "valid_from", "valid_until", "confidence")})
        data = {"source_id": source_id, "source_type": row["source_type"], "source_title": row["title"], "destination": row["destination"], "applicable_conditions": json.loads(row["applicable_conditions_json"]), "missing_fields": json.loads(row["missing_fields_json"]), "completeness": row["completeness"], "fetched_at": row["fetched_at"], "source_published_at": row["published_at"], "travel_occurred_at": row["travel_occurred_at"], "policy_id": row["policy_id"], "claims": claims, "is_synthetic": bool(row["is_synthetic"])}
        if "claim_metadata_json" in row.keys() and row["claim_metadata_json"] is not None:
            active = {claim["claim_id"] for claim in claims}
            data["claim_metadata"] = {key: value for key, value in json.loads(row["claim_metadata_json"]).items() if key in active}
        return EvidenceBundle(data)

    def delete(self, source_id, account_scope):
        with self.db.transaction() as con:
            con.execute("DELETE FROM sources WHERE source_id=? AND account_scope=?", (source_id, account_scope))
