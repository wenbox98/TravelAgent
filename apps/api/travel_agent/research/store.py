"""Revision-guarded research metadata and policy-gated existing Evidence storage."""

from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Literal, cast
from uuid import uuid4

from travel_agent.domain.models import EvidenceBundle, SourcePolicy, validator
from travel_agent.domain.source_policy import is_private, scope_allowed
from travel_agent.persistence.database import Database
from travel_agent.persistence.repositories import EvidenceRepository, encode
from .content_store import SourceContentStore
from .extractor import EvidenceExtractor, ExtractionResult
from .models import DetailMaterial

_PRIVATE = re.compile(
    r"(?i)https?://|xsec[_-]?token|access[_-]?token|authorization|cookie\s*[:=]|"
    r"session\s*[:=]|bearer\s+|[?&]token=|SECRET_(?:COOKIE|XSEC|SESSION|AUTHORIZATION|QR)"
)
_COMPLETENESS = {"FULL_TEXT", "PARTIAL_TEXT", "SUMMARY_ONLY", "METADATA_ONLY"}
_REQUEST_TEXT = {"departure", "destination", "time_hint", "research_question", "transport"}
_REQUEST_COUNT = {"days", "budget_cny_fen", "traveler_count"}
_SUMMARY_COUNT = {
    "revision", "cache_sources", "query_count", "candidate_count", "source_count", "evidence_count",
    "conflict_count", "candidate_direction_count", "unsupported_claims", "grounded_claim_count",
    "published_important_claims",
}


def _text(value: Any, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or _PRIVATE.search(value):
        raise ValueError("研究元信息含不允许的值")
    return value


def _identifier(value: Any) -> str:
    safe = _text(value, 180)
    if re.fullmatch(r"[A-Za-z0-9:_-]+", safe) is None:
        raise ValueError("研究标识无效")
    return safe


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("研究计数须为非负整数")
    return value


def _boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError("研究标志须为布尔值")
    return value


def _request(data: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key in _REQUEST_TEXT | _REQUEST_COUNT | {"no_self_drive"}:
        if key not in data:
            continue
        value = data[key]
        output[key] = (None if value is None else _text(value) if key in _REQUEST_TEXT
                       else _count(value) if key in _REQUEST_COUNT else _boolean(value))
    return output


def _gap(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "gap_id": _identifier(data["gap_id"]), "description": _text(data["description"]),
        "topics": [_identifier(value) for value in data.get("topics", [])],
        "status": _identifier(data.get("status", "UNKNOWN")),
    }


def _summary(data: dict[str, Any]) -> dict[str, Any]:
    # Explicitly omit report materials/claims/body and the separately stored gaps.
    output: dict[str, Any] = {key: _count(data[key]) for key in _SUMMARY_COUNT if key in data}
    if "unsupported_published_claims" in data:
        output["unsupported_published_claims"] = None if data["unsupported_published_claims"] is None else _count(data["unsupported_published_claims"])
    if "extraction_results" in data:
        if not isinstance(data["extraction_results"], list) or len(data["extraction_results"]) > 12:
            raise ValueError("INVALID_EXTRACTION_RESULTS")
        for result in data["extraction_results"]:
            validator("GroundingCounts").validate(result)
        output["extraction_results"] = data["extraction_results"]
    if "extraction_diagnostics" in data:
        diagnostics = data["extraction_diagnostics"]
        if not isinstance(diagnostics, list) or len(diagnostics) > 12:
            raise ValueError("INVALID_DIAGNOSTICS")
        for diagnostic in diagnostics:
            validator("LLMDiagnostic").validate(diagnostic)
        output["extraction_diagnostics"] = diagnostics
    for key in ("stop_reason", "diagnostic", "claim_basis", "gaps_basis",
                "grounding_review_status", "conflict_review_status"):
        if key in data:
            output[key] = None if data[key] is None else _identifier(data[key])
    for key in ("obsolete", "is_final_itinerary", "travel_time_unknown"):
        if key in data:
            output[key] = _boolean(data[key])
    for key in ("topics", "completeness", "extraction_modes"):
        if key in data:
            output[key] = [_identifier(value) for value in data[key]]
    if "operations" in data:
        output["operations"] = {kind: _count(data["operations"].get(kind, 0))
                                for kind in ("search", "detail")}
    if "coverage" in data:
        output["coverage"] = []
        for row in data["coverage"]:
            status = _identifier(row["status"])
            if status not in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"}:
                raise ValueError("覆盖状态无效")
            output["coverage"].append({
                "question_id": _identifier(row["question_id"]), "status": status,
                "claim_count": _count(row.get("claim_count", len(row.get("claim_ids", [])))),
                "source_count": _count(row.get("source_count", len(row.get("source_ids", [])))),
                "reason": _text(row["reason"], 240),
            })
    if "source_independence" in data:
        values = data["source_independence"]
        output["source_independence"] = {
            key: _count(values[key])
            for key in ("distinct_sources", "group_count", "confirmed_independent_sources")
        } | {"status": _identifier(values["status"])}
    if "freshness" in data:
        output["freshness"] = _count_tree(data["freshness"])
    if "locator_coverage" in data:
        value = data["locator_coverage"]
        if value is not None and (type(value) not in {int, float} or not 0 <= value <= 1):
            raise ValueError("定位覆盖率须为 0 到 1 或未知")
        output["locator_coverage"] = value
    return output


def _count_tree(data: Any, depth: int = 0) -> dict[str, Any]:
    if not isinstance(data, dict) or depth > 2:
        raise ValueError("研究分类计数无效")
    return {_identifier(key): _count_tree(value, depth + 1) if isinstance(value, dict)
            else _count(value) for key, value in data.items()}


def _snapshot(data: dict[str, Any], bundle: EvidenceBundle) -> dict[str, Any]:
    output: dict[str, Any] = {
        "completeness": bundle["completeness"], "fetched_at": bundle["fetched_at"],
        "published_at": bundle["source_published_at"], "evidence_count": len(bundle["claims"]),
    }
    for key in ("body_chars", "image_count"):
        if key in data:
            output[key] = _count(data[key])
    if "identity_match" in data:
        if not _boolean(data["identity_match"]):
            raise ValueError("来源身份不匹配，不能保存证据")
        output["identity_match"] = True
    if "extraction_mode" in data:
        output["extraction_mode"] = _identifier(data["extraction_mode"])
    if output["completeness"] not in _COMPLETENESS:
        raise ValueError("正文完整度无效")
    return output


class EvidenceStore:
    """Temporary evidence never reaches SQL; its metadata database must also be in RAM.

    Private local research is an explicit scope-bound usage mode, not an assertion
    of author/platform permission. Legacy UNKNOWN policies remain temporary-only.
    """

    def __init__(self, db: Database, *, temporary: bool = False) -> None:
        if temporary and db.path != Path(":memory:"):
            raise ValueError("临时研究只允许内存数据库")
        if db.version < 4:
            raise ValueError("研究资料库需要迁移至 v4")
        self.db = db
        self.temporary = temporary
        self.repository = EvidenceRepository(db)
        self.contents = SourceContentStore(db)
        self._temporary: dict[tuple[str, str], tuple[EvidenceBundle, SourcePolicy, str]] = {}

    def begin(self, research_id: str, revision: int, request: dict[str, Any],
              account_scope: str) -> str:
        research_id, account_scope = _identifier(research_id), _identifier(account_scope)
        _count(revision)
        payload = encode(_request(request))
        with self.db.transaction() as con:
            row = con.execute("SELECT * FROM research_questions WHERE research_id=?",
                              (research_id,)).fetchone()
            if row is not None:
                if row["account_scope"] != account_scope:
                    raise PermissionError("研究不能跨账号范围复用")
                if revision < row["current_revision"]:
                    raise ValueError("研究版本已过期")
                if (revision == row["current_revision"]
                    and json.loads(payload) != json.loads(row["request_json"])):
                    raise ValueError("研究问题变化必须递增版本")
                con.execute("UPDATE research_questions SET current_revision=?, request_json=?, "
                            "updated_at=? WHERE research_id=?",
                            (revision, payload, self.db.stamp(), research_id))
            else:
                con.execute("INSERT INTO research_questions VALUES(?,?,?,?,?,?)",
                            (research_id, account_scope, revision, payload,
                             self.db.stamp(), self.db.stamp()))
            run_id = "run-" + uuid4().hex
            con.execute("INSERT INTO research_runs VALUES(?,?,?,?,'RUNNING',NULL,?,NULL)",
                        (run_id, research_id, revision, payload, self.db.stamp()))
            values = json.loads(payload)
            for name in ("days", "no_self_drive", "budget_cny_fen", "transport",
                         "traveler_count", "time_hint"):
                value = values.get(name)
                if value is not None and not (name == "no_self_drive" and value is False):
                    con.execute("INSERT OR IGNORE INTO research_constraints VALUES(?,?,?,?,'USER')",
                                (research_id, revision, name, encode(value)))
        return run_id

    def _current(self, run_id: str, revision: int) -> sqlite3.Row | None:
        return cast(sqlite3.Row | None, self.db.connection.execute(
            "SELECT r.*,q.account_scope FROM research_runs r JOIN research_questions q "
            "ON r.research_id=q.research_id WHERE r.run_id=? AND r.revision=? "
            "AND q.current_revision=r.revision AND r.status='RUNNING'", (run_id, revision),
        ).fetchone())

    def is_current(self, run_id: str, revision: int) -> bool:
        return self._current(run_id, revision) is not None

    def _allowed(self, policy: SourcePolicy) -> bool:
        if not self.temporary:
            return bool(self.repository.permitted(policy))
        now = self.db.clock()
        reviewed, expires = policy["reviewed_at"], policy["expires_at"]
        return bool(
            policy["allow_read"] and policy["allow_inference"]
            and (policy["basis"] != "UNKNOWN" or not policy["allow_external_model"])
            and (reviewed is None and policy["basis"] == "UNKNOWN"
                 or reviewed is not None and datetime.fromisoformat(reviewed) <= now)
            and (expires is None or datetime.fromisoformat(expires) > now)
        )

    def _latest_policy(self, policy_id: str) -> SourcePolicy | None:
        row = self.db.connection.execute(
            "SELECT policy_json FROM source_policies WHERE policy_id=? ORDER BY version DESC LIMIT 1",
            (policy_id,),
        ).fetchone()
        return SourcePolicy(json.loads(row[0])) if row is not None else None

    def _remember_policy(self, policy: SourcePolicy) -> None:
        previous = self._latest_policy(policy["policy_id"])
        if previous is not None:
            if previous["version"] > policy["version"]:
                raise PermissionError("来源策略版本已过期")
            if previous["version"] == policy["version"] and previous.to_dict() != policy.to_dict():
                raise ValueError("来源策略变化必须递增版本")
        self.db.connection.execute("INSERT OR IGNORE INTO source_policies VALUES(?,?,?,?,?)",
                                   (policy["policy_id"], policy["version"], encode(policy.to_dict()),
                                    policy["reviewed_at"], policy["expires_at"]))

    def register_policy(self, run_id: str, revision: int, policy: SourcePolicy) -> bool:
        """Apply current governance before lookup, including explicit rights revocation.

        Recording our own policy decision is independent of permission to retain the
        source material. A denied policy must still invalidate previously cached data.
        """
        with self.db.transaction():
            run = self._current(run_id, revision)
            if run is None:
                return False
            if not scope_allowed(policy, run["account_scope"]):
                raise PermissionError("私人研究策略不能跨账号范围使用")
            self._remember_policy(policy)
        return True

    def _has_snapshot(self, snapshot_id: str, scope: str, source_id: str) -> bool:
        return self.db.connection.execute(
            "SELECT 1 FROM source_snapshots WHERE snapshot_id=? AND account_scope=? AND source_id=?",
            (snapshot_id, scope, source_id),
        ).fetchone() is not None

    def lookup(self, research_id: str, destination: str | None,
               account_scope: str) -> tuple[EvidenceBundle, ...]:
        question = self.db.connection.execute(
            "SELECT account_scope FROM research_questions WHERE research_id=?", (research_id,),
        ).fetchone()
        if question is not None and question[0] != account_scope:
            return ()
        linked = {row[0] for row in self.db.connection.execute(
            "SELECT s.source_id FROM source_snapshots s JOIN research_run_sources rs "
            "ON s.snapshot_id=rs.snapshot_id JOIN research_runs r ON r.run_id=rs.run_id "
            "WHERE r.research_id=? AND s.account_scope=?", (research_id, account_scope),
        )}
        candidates: list[tuple[EvidenceBundle, SourcePolicy]]
        if self.temporary:
            candidates = [
                (bundle, policy) for (scope, source_id), (bundle, policy, snapshot_id)
                in self._temporary.items()
                if scope == account_scope and self._has_snapshot(snapshot_id, scope, source_id)
            ]
        else:
            candidates = []
            for row in self.db.connection.execute(
                "SELECT source_id FROM sources WHERE account_scope=? AND deleted_at IS NULL",
                (account_scope,),
            ):
                bundle = self.repository.get(row[0], account_scope)
                if bundle is not None:
                    policy = self._latest_policy(bundle["policy_id"])
                    if policy is not None:
                        candidates.append((bundle, policy))
        result: list[EvidenceBundle] = []
        for bundle, policy in candidates:
            matches = (bundle["destination"] == destination if destination is not None
                       else bundle["source_id"] in linked)
            latest = self._latest_policy(bundle["policy_id"])
            if (matches and self._allowed(policy) and scope_allowed(policy, account_scope)
                and latest is not None and self._allowed(latest)
                and scope_allowed(latest, account_scope)):
                if is_private(latest) and latest["allow_persist_raw"]:
                    if not self.contents.load(bundle["source_id"], account_scope):
                        continue
                if bundle["claims"]:
                    result.append(bundle)
        return tuple(result)

    def save_source(self, run_id: str, revision: int, material: DetailMaterial,
                    policy: SourcePolicy, destination: str | None) -> str:
        """Commit a detail and empty source metadata BEFORE any model invocation."""
        empty = EvidenceExtractor(clock=self.db.clock).extract(
            source_id=material.source_id, source_title=material.title, body=material.body,
            dom_body=material.dom_body, completeness=material.completeness,
            fetched_at=material.fetched_at, source_published_at=material.published_at,
            source_type=material.source_type, image_count=material.image_count,
            policy=policy, destination=destination, allow_fallback=False)
        with self.db.transaction():
            if not self.save_evidence(run_id, revision, empty.bundle, policy,
                                      {"identity_match": material.identity_match}):
                raise ValueError("STALE_REVISION")
            identifier = self.contents.put(run_id, revision, material, empty, policy)
            if identifier is None:
                raise ValueError("SOURCE_CONTENT_NOT_SAVED")
        return identifier

    def save_detail(self, run_id: str, revision: int, material: DetailMaterial,
                    extracted: ExtractionResult, policy: SourcePolicy,
                    snapshot: dict[str, Any]) -> bool:
        """Evidence and private body commit together or neither is retained."""
        with self.db.transaction():
            saved = self.save_evidence(run_id, revision, extracted.bundle, policy, snapshot)
            if saved and is_private(policy):
                self.contents.put(run_id, revision, material, extracted, policy)
            return saved

    def save_evidence(self, run_id: str, revision: int, bundle: EvidenceBundle,
                      policy: SourcePolicy, snapshot: dict[str, Any], *, merge_reviewed: bool = False) -> bool:
        retained = bundle
        with self.db.transaction() as con:
            run = self._current(run_id, revision)
            if run is None:
                return False
            source_id, scope = _identifier(bundle["source_id"]), run["account_scope"]
            if (policy["policy_id"] != bundle["policy_id"] or not self._allowed(policy)
                or not scope_allowed(policy, scope)):
                raise PermissionError("来源策略不允许本次证据存储方式")
            if bundle["is_synthetic"] and policy["basis"] != "SYNTHETIC":
                raise PermissionError("合成证据需要合成来源策略")
            if _PRIVATE.search(encode(bundle.to_dict())):
                raise ValueError("证据含不允许的访问材料")
            if any(not claim.get("locator") for claim in bundle["claims"]):
                raise ValueError("无正文定位的结论不能作为正常证据保存")
            existing = con.execute(
                "SELECT account_scope FROM sources WHERE source_id=? UNION "
                "SELECT account_scope FROM source_snapshots WHERE source_id=?", (source_id, source_id),
            ).fetchall()
            if any(row[0] != scope for row in existing):
                raise PermissionError("来源不能隐式跨账号范围覆盖")
            self._remember_policy(policy)
            if self.temporary:
                cached = self._temporary.get((scope, source_id))
                if cached is not None and self._has_snapshot(cached[2], scope, source_id):
                    retained = cached[0]
            else:
                stored = con.execute("SELECT policy_id FROM sources WHERE source_id=?",
                                     (source_id,)).fetchone()
                if stored is None:
                    self.repository.save(bundle, policy, account_scope=scope)
                else:
                    stored_bundle = self.repository.get(source_id, scope)
                    if stored_bundle is None or stored[0] != policy["policy_id"]:
                        raise PermissionError("已有来源不能按不同或失效策略覆盖")
                    if merge_reviewed:
                        merged = {c["claim_id"]: c for c in stored_bundle["claims"]}
                        assessments = dict(stored_bundle.get("claim_metadata", {}))
                        for claim in bundle["claims"]:
                            if claim["claim_id"] in merged and merged[claim["claim_id"]] != claim:
                                raise ValueError("REVIEW_EVIDENCE_CONFLICT")
                            merged[claim["claim_id"]] = claim
                            assessments.setdefault(claim["claim_id"], bundle["claim_metadata"][claim["claim_id"]])
                        bundle = EvidenceBundle(bundle.to_dict() | {"claims": list(merged.values()), "claim_metadata": assessments})
                        retained = bundle
                    if (not stored_bundle["claims"] or merge_reviewed) and bundle["claims"]:
                        # Complete a source-only record, never overwrite accepted evidence.
                        con.execute("UPDATE sources SET title=?,completeness=?,fetched_at=?,published_at=?,"
                                    "travel_occurred_at=?,destination=?,applicable_conditions_json=?,"
                                    "missing_fields_json=?,claim_metadata_json=? WHERE source_id=?",
                                    (bundle["source_title"], bundle["completeness"], bundle["fetched_at"],
                                     bundle["source_published_at"], bundle["travel_occurred_at"], bundle["destination"],
                                     encode(bundle["applicable_conditions"]), encode(bundle["missing_fields"]),
                                     encode(bundle.get("claim_metadata", {})), source_id))
                        for claim in bundle["claims"]:
                            con.execute("INSERT OR IGNORE INTO claims(claim_id,source_id,topic,text,kind,locator,support,"
                                        "valid_from,valid_until,confidence) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                        tuple(claim[k] for k in ("claim_id", "source_id", "topic", "text", "kind",
                                              "locator", "support", "valid_from", "valid_until", "confidence")))
                    else:
                        retained = stored_bundle
            if retained["policy_id"] != policy["policy_id"]:
                raise PermissionError("已有来源不能改换来源策略")
            metadata = _snapshot(snapshot, retained)
            con.execute("INSERT OR IGNORE INTO source_snapshots VALUES(?,?,?,?,?,?,?)",
                        ("snapshot-" + uuid4().hex, source_id, scope, policy["policy_id"],
                         policy["version"], encode(metadata), self.db.stamp()))
            snapshot_id = con.execute(
                "SELECT snapshot_id FROM source_snapshots WHERE source_id=? AND account_scope=?",
                (source_id, scope),
            ).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO research_run_sources VALUES(?,?)", (run_id, snapshot_id))
            if self.temporary:
                self._temporary[(scope, source_id)] = (retained, policy, snapshot_id)
        return True

    def finish(self, run_id: str, revision: int, gaps: list[dict[str, Any]],
               summary: dict[str, Any]) -> bool:
        with self.db.transaction() as con:
            run = self._current(run_id, revision)
            if run is None:
                return False
            for gap in gaps:
                metadata = _gap(gap)
                con.execute("INSERT OR REPLACE INTO research_gaps VALUES(?,?,?)",
                            (run_id, metadata["gap_id"], encode(metadata)))
            safe = encode(_summary(summary))
            request = json.loads(run["request_json"])
            evidence = self.lookup(run["research_id"], request.get("destination"), run["account_scope"])
            source_ids = sorted({_identifier(bundle["source_id"]) for bundle in evidence})
            claim_ids = sorted({_identifier(claim["claim_id"])
                                for bundle in evidence for claim in bundle["claims"]})
            con.execute("INSERT INTO research_reports VALUES(?,?,?,?,?)",
                        (run_id, safe, encode(source_ids), encode(claim_ids), self.db.stamp()))
            con.execute("UPDATE research_runs SET status='FINISHED',summary_json=?,finished_at=? "
                        "WHERE run_id=?", (safe, self.db.stamp(), run_id))
        return True

    def load_report(self, research_id: str, account_scope: str) -> dict[str, Any] | None:
        """Return local metadata and handles; reconstruct text/quality from current Evidence.

        Revoked, expired or deleted sources invalidate this stored view. Historical
        coverage is not a new freshness judgment; callers must rebuild before display.
        """
        row = self.db.connection.execute(
            "SELECT p.*,r.research_id,r.revision,r.request_json FROM research_reports p "
            "JOIN research_runs r ON p.run_id=r.run_id JOIN research_questions q "
            "ON q.research_id=r.research_id WHERE q.research_id=? AND q.account_scope=? "
            "AND q.current_revision=r.revision AND r.status='FINISHED' "
            "ORDER BY r.rowid DESC LIMIT 1", (research_id, account_scope),
        ).fetchone()
        if row is None:
            return None
        request = json.loads(row["request_json"])
        evidence = self.lookup(research_id, request.get("destination"), account_scope)
        sources = {bundle["source_id"] for bundle in evidence}
        claims = {claim["claim_id"] for bundle in evidence for claim in bundle["claims"]}
        source_ids, claim_ids = json.loads(row["source_handles_json"]), json.loads(row["claim_handles_json"])
        summary = json.loads(row["metadata_json"])
        if (not set(source_ids) <= sources or not set(claim_ids) <= claims
            or summary.get("source_count", len(source_ids)) != len(source_ids)
            or summary.get("evidence_count", len(claim_ids)) != len(claim_ids)):
            return None
        constraints = [{"name": item["name"], "value": json.loads(item["value_json"]),
                        "provenance": item["provenance"]} for item in self.db.connection.execute(
            "SELECT * FROM research_constraints WHERE research_id=? AND revision=? ORDER BY name",
            (research_id, row["revision"]),
        )]
        gaps = [json.loads(item[0]) for item in self.db.connection.execute(
            "SELECT metadata_json FROM research_gaps WHERE run_id=? ORDER BY gap_id", (row["run_id"],),
        )]
        return {"run_id": row["run_id"], "research_id": research_id, "revision": row["revision"],
                "request": request, "constraints": constraints, "gaps": gaps, "summary": summary,
                "source_ids": source_ids, "claim_ids": claim_ids, "rebuild_required": True}

    def clear_research_cache(self, account_scope: str) -> dict[str, int]:
        """Delete this scope's research cache atomically; no authentication dependencies.

        Source policies are shared governance configuration and are retained. Deletion
        is logical SQLite deletion, not a claim about backups or physical SSD erasure.
        """
        scope = _identifier(account_scope)
        with self.db.transaction() as con:
            count_queries = {
                "questions": "SELECT count(*) FROM research_questions WHERE account_scope=?",
                "runs": "SELECT count(*) FROM research_runs WHERE research_id IN "
                        "(SELECT research_id FROM research_questions WHERE account_scope=?)",
                "sources": "SELECT count(*) FROM sources WHERE account_scope=?",
                "claims": "SELECT count(*) FROM claims WHERE source_id IN "
                          "(SELECT source_id FROM sources WHERE account_scope=?)",
                "snapshots": "SELECT count(*) FROM source_snapshots WHERE account_scope=?",
            }
            if self.db.version >= 5:
                count_queries.update({
                    "source_contents": "SELECT count(*) FROM source_contents WHERE account_scope=?",
                    "body_blocks": "SELECT count(*) FROM source_body_blocks WHERE content_id IN "
                                   "(SELECT content_id FROM source_contents WHERE account_scope=?)",
                })
            counts = {name: int(con.execute(query, (scope,)).fetchone()[0])
                      for name, query in count_queries.items()}
            # sources -> claims/chunks/lineage; chunks' existing trigger deletes FTS rows.
            con.execute("DELETE FROM research_questions WHERE account_scope=?", (scope,))
            con.execute("DELETE FROM source_snapshots WHERE account_scope=?", (scope,))
            con.execute("DELETE FROM sources WHERE account_scope=?", (scope,))
        self._temporary = {key: value for key, value in self._temporary.items() if key[0] != scope}
        return counts

    def queries(self, research_id: str) -> set[str]:
        return {row[0] for row in self.db.connection.execute(
            "SELECT query FROM research_queries WHERE research_id=?", (research_id,),
        )}

    def record_query(self, run_id: str, revision: int, query: str) -> bool:
        with self.db.transaction() as con:
            run = self._current(run_id, revision)
            if run is None:
                return False
            normalized = " ".join(_text(query, 300).split())
            if not normalized:
                raise ValueError("查询不能为空")
            return bool(con.execute("INSERT OR IGNORE INTO research_queries VALUES(?,?,?)",
                                    (run["research_id"], normalized, run_id)).rowcount == 1)

    def reserve_operation(self, run_id: str, revision: int, kind: Literal["SEARCH", "DETAIL"],
                          fingerprint: str, limit: int) -> bool:
        with self.db.transaction() as con:
            run = self._current(run_id, revision)
            if run is None:
                return False
            if kind not in {"SEARCH", "DETAIL"}:
                raise ValueError("研究操作类型无效")
            _count(limit)
            fingerprint = _identifier(fingerprint)
            count = con.execute("SELECT count(*) FROM research_ops WHERE run_id=? AND kind=?",
                                (run_id, kind)).fetchone()[0]
            if count >= limit:
                return False
            return bool(con.execute("INSERT OR IGNORE INTO research_ops VALUES(?,?,?,?,?,?)",
                                    (run["research_id"], run_id, revision, kind, fingerprint,
                                     self.db.stamp())).rowcount == 1)

    def operations(self, run_id: str) -> dict[str, int]:
        result = {"search": 0, "detail": 0}
        for row in self.db.connection.execute(
            "SELECT kind,count(*) FROM research_ops WHERE run_id=? GROUP BY kind", (run_id,),
        ):
            result[row[0].lower()] = row[1]
        return result
