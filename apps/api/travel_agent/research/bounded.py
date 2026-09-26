"""Explicit local grants over the existing durable continuation ledger. No dispatch."""

from hashlib import sha256
import json
from typing import Any

from travel_agent.providers.llm import OpenAICompatibleProvider
from .retry import _config
from .store import EvidenceStore

LIMITS = {"CONNECT": 1, "SEARCH": 1, "DETAIL": 1, "MODEL": 4}


class BoundedBudget:
    def __init__(self, store: EvidenceStore, identifier: str):
        self.store, self.identifier = store, identifier

    def grant(
        self,
        scope: str,
        predecessor: str,
        provider: OpenAICompatibleProvider,
        evaluation_attempts: list[str],
    ) -> None:
        """Operator-only entry point. Never called on boot, GET, job creation or retry."""
        if len(set(evaluation_attempts)) != 2 or provider.timeout != 120:
            raise ValueError("BOUNDED_GRANT_INVALID")
        config = _config(provider, 180)
        if config["host"] not in {"api.deepseek.com", "127.0.0.1"}:
            raise ValueError("BOUNDED_PROVIDER_DENIED")
        config["workspace"] = sha256(str(self.store.db.path.resolve()).encode()).hexdigest()
        with self.store.db.transaction() as con:
            if config["host"] == "api.deepseek.com":
                prior_config = con.execute(
                    "SELECT config_json FROM research_continuations WHERE account_scope=? "
                    "AND finished_at IS NOT NULL AND limits_json IS NULL ORDER BY created_at DESC LIMIT 1",
                    (scope,),
                ).fetchone()
                expected = config.copy()
                expected.pop("workspace")
                if prior_config is None or json.loads(prior_config[0]) != expected:
                    raise ValueError("BOUNDED_PREDECESSOR_PROVIDER_MISMATCH")
            if con.execute(
                "SELECT 1 FROM research_continuations WHERE limits_json IS NOT NULL AND continuation_id!=? "
                "AND finished_at IS NULL",
                (self.identifier,),
            ).fetchone():
                raise ValueError("BOUNDED_EXISTING_PROJECT_GRANT")
            for attempt in evaluation_attempts:
                r = con.execute(
                    "SELECT a.extraction_version,b.account_scope FROM extraction_attempts a "
                    "JOIN extraction_batches b USING(batch_id) WHERE attempt_id=?",
                    (attempt,),
                ).fetchone()
                if not r or r[0] != 3 or r[1] != scope:
                    raise ValueError("BOUNDED_EVALUATION_IDENTITY_INVALID")
            gate = {"status": "PENDING", "evaluation_attempts": evaluation_attempts}
            values = (
                scope,
                predecessor,
                json.dumps(config, sort_keys=True),
                json.dumps(LIMITS, sort_keys=True),
            )
            prior = con.execute(
                "SELECT account_scope,predecessor,config_json,limits_json FROM research_continuations "
                "WHERE continuation_id=?",
                (self.identifier,),
            ).fetchone()
            if prior:
                if tuple(prior) != values:
                    raise ValueError("BOUNDED_GRANT_IMMUTABLE")
                return
            con.execute(
                "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
                (
                    self.identifier,
                    *values[:3],
                    self.store.db.stamp(),
                    self.store.db.stamp(),
                    values[3],
                    json.dumps(gate),
                ),
            )

    def state(self) -> dict[str, Any]:
        r = self.store.db.connection.execute(
            "SELECT * FROM research_continuations WHERE continuation_id=?", (self.identifier,)
        ).fetchone()
        if not r or r["limits_json"] is None:
            raise ValueError("BOUNDED_GRANT_MISSING")
        result = dict(r)
        for k in ("config", "limits", "gate"):
            result[k] = json.loads(result.pop(k + "_json"))
        if (
            result["config"]["workspace"]
            != sha256(str(self.store.db.path.resolve()).encode()).hexdigest()
        ):
            raise ValueError("BOUNDED_WORKSPACE_MISMATCH")
        return result

    def check_provider(self, provider: OpenAICompatibleProvider) -> None:
        config = self.state()["config"].copy()
        config.pop("workspace")
        if config != _config(provider, 180):
            raise ValueError("BOUNDED_PROVIDER_CHANGED")

    def reserve(self, kind: str, fingerprint: str) -> None:
        with self.store.db.transaction() as con:
            state = self.state()
            if kind not in LIMITS or state["finished_at"] or not state["started_at"]:
                raise ValueError("BOUNDED_NOT_ACTIVE")
            if kind != "MODEL" and state["gate"]["status"] != "PASS":
                raise ValueError("EVALUATION_GATE_NOT_PASS")
            count = con.execute(
                "SELECT count(*) FROM continuation_operations WHERE continuation_id=? AND kind=?",
                (self.identifier, kind),
            ).fetchone()[0]
            digest = sha256(fingerprint.encode()).hexdigest()
            if (
                count >= state["limits"][kind]
                or con.execute(
                    "SELECT 1 FROM continuation_operations "
                    "WHERE continuation_id=? AND kind=? AND fingerprint=?",
                    (self.identifier, kind, digest),
                ).fetchone()
            ):
                raise ValueError("BOUNDED_BUDGET_OR_DUPLICATE_DENIED")
            con.execute(
                "INSERT INTO continuation_operations VALUES(?,?,?,?)",
                (self.identifier, kind, digest, self.store.db.stamp()),
            )

    def check_permit(self, kind: str, fingerprint: str) -> None:
        self.state()
        if not self.store.db.connection.execute(
            "SELECT 1 FROM continuation_operations WHERE continuation_id=? "
            "AND kind=? AND fingerprint=?",
            (self.identifier, kind, sha256(fingerprint.encode()).hexdigest()),
        ).fetchone():
            raise ValueError("BOUNDED_PERMIT_MISSING")

    def check_job_active(self, research_id: str) -> None:
        row=self.store.db.connection.execute('SELECT status,cancel_requested FROM preview_jobs WHERE continuation_id=? '
            'AND research_id=?',(self.identifier,research_id)).fetchone()
        if row is None or row[0]!='RUNNING' or row[1]:
            raise ValueError('JOB_NO_LONGER_ACTIVE')

    def summary(self) -> dict[str, Any]:
        s = self.state()
        used = {k.lower(): 0 for k in LIMITS}
        for r in self.store.db.connection.execute(
            "SELECT kind,count(*) FROM continuation_operations "
            "WHERE continuation_id=? GROUP BY kind",
            (self.identifier,),
        ):
            used[r[0].lower()] = r[1]
        return {
            "used": used,
            "remaining": {k.lower(): v - used[k.lower()] for k, v in s["limits"].items()},
            "gate": s["gate"]["status"],
            "closed": bool(s["finished_at"]),
        }

    def conclude_evaluation(self, passed: bool) -> None:
        with self.store.db.transaction() as con:
            s = self.state()
            if s["gate"]["status"] != "PENDING":
                raise ValueError("EVALUATION_ALREADY_FINAL")
            rows = con.execute(
                "SELECT attempt_id,status,results_json FROM context_review_runs WHERE continuation_id=? AND mode='EVALUATION'",
                (self.identifier,),
            ).fetchall()
            if passed and (
                set(r[0] for r in rows) != set(s["gate"]["evaluation_attempts"])
                or any(r[1] != "COMPLETED" for r in rows)
            ):
                raise ValueError("EVALUATION_INCOMPLETE")
            s["gate"]["status"] = "PASS" if passed else "PARTIAL"
            con.execute(
                "UPDATE research_continuations SET gate_json=? WHERE continuation_id=?",
                (json.dumps(s["gate"]), self.identifier),
            )
