"""Revision-guarded research metadata and policy-gated existing Evidence storage."""

from datetime import datetime
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Literal, cast
from uuid import uuid4

from travel_agent.domain.models import EvidenceBundle, SourcePolicy
from travel_agent.persistence.database import Database
from travel_agent.persistence.repositories import EvidenceRepository, encode

_PRIVATE = re.compile(
    r"(?i)https?://|xsec[_-]?token|access[_-]?token|authorization|cookie\s*[:=]|"
    r"session\s*[:=]|bearer\s+|[?&]token=|SECRET_(?:COOKIE|XSEC|SESSION|AUTHORIZATION|QR)"
)
_COMPLETENESS = {"FULL_TEXT", "PARTIAL_TEXT", "SUMMARY_ONLY", "METADATA_ONLY"}
_REQUEST_TEXT = {"departure", "destination", "time_hint", "research_question", "transport"}
_REQUEST_COUNT = {"days", "budget_cny_fen", "traveler_count"}
_SUMMARY_COUNT = {
    "revision", "cache_sources", "query_count", "candidate_count", "source_count", "evidence_count",
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
    for key in ("stop_reason", "diagnostic", "claim_basis", "gaps_basis"):
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
    return output


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

    SourcePolicy expresses separate reading/inference/storage rights. UNKNOWN permits
    only an explicitly allowed, local temporary use, never durable derived storage or
    an external model. Merely possessing a browser session grants none of these rights.
    """

    def __init__(self, db: Database, *, temporary: bool = False) -> None:
        if temporary and db.path != Path(":memory:"):
            raise ValueError("临时研究只允许内存数据库")
        if db.version < 3:
            raise ValueError("研究资料库需要迁移至 v3")
        self.db = db
        self.temporary = temporary
        self.repository = EvidenceRepository(db)
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
            if self._current(run_id, revision) is None:
                return False
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
            if matches and self._allowed(policy) and latest is not None and self._allowed(latest):
                result.append(bundle)
        return tuple(result)

    def save_evidence(self, run_id: str, revision: int, bundle: EvidenceBundle,
                      policy: SourcePolicy, snapshot: dict[str, Any]) -> bool:
        retained = bundle
        with self.db.transaction() as con:
            run = self._current(run_id, revision)
            if run is None:
                return False
            source_id, scope = _identifier(bundle["source_id"]), run["account_scope"]
            if policy["policy_id"] != bundle["policy_id"] or not self._allowed(policy):
                raise PermissionError("来源策略不允许本次证据存储方式")
            if bundle["is_synthetic"] and policy["basis"] != "SYNTHETIC":
                raise PermissionError("合成证据需要合成来源策略")
            if _PRIVATE.search(encode(bundle.to_dict())):
                raise ValueError("证据含不允许的访问材料")
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
            if self._current(run_id, revision) is None:
                return False
            for gap in gaps:
                metadata = _gap(gap)
                con.execute("INSERT OR REPLACE INTO research_gaps VALUES(?,?,?)",
                            (run_id, metadata["gap_id"], encode(metadata)))
            con.execute("UPDATE research_runs SET status='FINISHED',summary_json=?,finished_at=? "
                        "WHERE run_id=?", (encode(_summary(summary)), self.db.stamp(), run_id))
        return True

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
