"""Explicit private planning grant on the existing durable ledger."""

from hashlib import sha256
import json
from typing import Any

from travel_agent.persistence.database import Database
from travel_agent.preview.projection import safe_text
from travel_agent.providers.llm import OpenAICompatibleProvider
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.retry import _config
from travel_agent.research.store import EvidenceStore

IDENTIFIER = "p05-private-live-planning"
LIMITS = {"CONNECT": 1, "SEARCH": 1, "DETAIL": 2, "MODEL": 6, "MAP_PLACE": 6, "MAP_ROUTE": 4}


class PrivatePlanningBudget(BoundedBudget):
    def __init__(self, db: Database):
        super().__init__(EvidenceStore(db), IDENTIFIER)

    def initialize(self, scope: str, destination: str, provider: OpenAICompatibleProvider) -> None:
        """Operator action only; never boot/GET/new-trip. Repeated grants are immutable."""
        destination = safe_text(destination.strip(), 80)
        config = _config(provider, 180)
        if not destination or config["host"] != "api.deepseek.com" or provider.timeout != 120:
            raise ValueError("PRIVATE_GRANT_INVALID")
        db = self.store.db
        with db.transaction() as con:
            original = con.execute(
                "SELECT config_json FROM research_continuations WHERE account_scope=? AND limits_json IS NULL ORDER BY created_at DESC LIMIT 1",
                (scope,),
            ).fetchone()
            if original is None or json.loads(original[0]) != config:
                raise ValueError("PLANNING_ORIGINAL_PROVIDER_REQUIRED")
            config["workspace"] = sha256(str(db.path.resolve()).encode()).hexdigest()
            old = con.execute(
                "SELECT * FROM research_continuations WHERE continuation_id=?", (IDENTIFIER,)
            ).fetchone()
            if old:
                if (
                    old["account_scope"] != scope
                    or json.loads(old["config_json"]) != config
                    or json.loads(old["limits_json"]) != LIMITS
                    or json.loads(old["gate_json"])["destination"] != destination
                ):
                    raise ValueError("BOUNDED_GRANT_IMMUTABLE")
                return
            gate = {
                "status": "PASS",
                "purpose": "PRIVATE_DEVELOPMENT_VALIDATION",
                "destination": destination,
                "session_id": None,
            }
            con.execute(
                "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
                (
                    IDENTIFIER,
                    scope,
                    "P05_EXPLICIT_USER_AUTHORIZATION",
                    json.dumps(config, sort_keys=True),
                    db.stamp(),
                    db.stamp(),
                    json.dumps(LIMITS, sort_keys=True),
                    json.dumps(gate, ensure_ascii=False),
                ),
            )

    def check_trip(self, scope: str, sid: str, *, bind: bool = False) -> dict[str, Any]:
        state = self.state()
        row = self.store.db.connection.execute(
            "SELECT mode,state_json FROM preview_sessions WHERE session_id=? AND account_scope=?",
            (sid, scope),
        ).fetchone()
        p = json.loads(row[1]).get("planning") if row else None
        if (
            state["finished_at"]
            or state["account_scope"] != scope
            or not p
            or row["mode"] != "CACHED_PRIVATE_PREVIEW"
            or p["demo"]
            or p["destination"] != state["gate"]["destination"]
            or state["gate"]["session_id"] not in {None, sid}
        ):
            raise ValueError("PRIVATE_TRIP_NOT_AUTHORIZED")
        if bind and state["gate"]["session_id"] is None:
            state["gate"]["session_id"] = sid
            self.store.db.connection.execute(
                "UPDATE research_continuations SET gate_json=? WHERE continuation_id=?",
                (json.dumps(state["gate"], ensure_ascii=False), IDENTIFIER),
            )
        return state

    def reserve_for_trip(self, scope: str, sid: str, kind: str, identity: str) -> None:
        with self.store.db.transaction():
            self.check_trip(scope, sid, bind=True)
            self.reserve_count(kind, identity, LIMITS)

    def summary(self) -> dict[str, Any]:
        state = self.state()
        used = {k.lower(): 0 for k in LIMITS}
        for kind, count in self.store.db.connection.execute(
            "SELECT kind,count(*) FROM continuation_operations WHERE continuation_id=? GROUP BY kind",
            (IDENTIFIER,),
        ):
            used[kind.lower()] = count
        return {
            "used": used,
            "remaining": {k.lower(): v - used[k.lower()] for k, v in LIMITS.items()},
            "closed": bool(state["finished_at"]),
            "gate": state["gate"]["status"],
        }
