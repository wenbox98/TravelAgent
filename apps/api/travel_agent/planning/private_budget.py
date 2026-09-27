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
CURRENT_IDENTIFIER = "p051-scope-locked-planning"
CURRENT_LIMITS = {
    "CONNECT": 1,
    "SEARCH": 1,
    "DETAIL": 2,
    "MODEL": 5,
    "MAP_PLACE": 5,
    "MAP_ROUTE": 3,
}
DISCOVERY_IDENTIFIER = "p052-cached-discovery-planning"
DISCOVERY_LIMITS = {
    "CONNECT": 0,
    "SEARCH": 0,
    "DETAIL": 0,
    "MODEL": 3,
    "MAP_PLACE": 6,
    "MAP_ROUTE": 2,
}
GRANTS = {
    IDENTIFIER: LIMITS,
    CURRENT_IDENTIFIER: CURRENT_LIMITS,
    DISCOVERY_IDENTIFIER: DISCOVERY_LIMITS,
}
REVISION_IDENTIFIER = "p06-adopted-revision"
GRANTS[REVISION_IDENTIFIER] = {
    "CONNECT": 0,
    "SEARCH": 0,
    "DETAIL": 0,
    "MODEL": 2,
    "MAP_PLACE": 0,
    "MAP_ROUTE": 0,
}


class PrivatePlanningBudget(BoundedBudget):
    def __init__(self, db: Database, identifier: str = IDENTIFIER):
        if identifier not in GRANTS:
            raise ValueError("PRIVATE_GRANT_INVALID")
        super().__init__(EvidenceStore(db), identifier)
        self.identifier, self.limits = identifier, GRANTS[identifier]

    @classmethod
    def for_trip(cls, db: Database, sid: str) -> "PrivatePlanningBudget":
        available = []
        for identifier in reversed(GRANTS):
            row = db.connection.execute(
                "SELECT gate_json FROM research_continuations WHERE continuation_id=?",
                (identifier,),
            ).fetchone()
            if row:
                available.append(identifier)
                if json.loads(row[0]).get("session_id") == sid:
                    return cls(db, identifier)
        return cls(db, available[0] if available else CURRENT_IDENTIFIER)

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
                "SELECT * FROM research_continuations WHERE continuation_id=?", (self.identifier,)
            ).fetchone()
            if old:
                if (
                    old["account_scope"] != scope
                    or json.loads(old["config_json"]) != config
                    or json.loads(old["limits_json"]) != self.limits
                    or json.loads(old["gate_json"])["destination"] != destination
                ):
                    raise ValueError("BOUNDED_GRANT_IMMUTABLE")
                return
            gate: dict[str, Any] = {
                "status": "PASS",
                "purpose": "PRIVATE_DEVELOPMENT_VALIDATION",
                "destination": destination,
                "session_id": None,
            }
            if self.identifier == DISCOVERY_IDENTIFIER:
                previous = con.execute(
                    "SELECT gate_json FROM research_continuations WHERE continuation_id=? AND account_scope=?",
                    (CURRENT_IDENTIFIER, scope),
                ).fetchone()
                prior = json.loads(previous[0]) if previous else {}
                if not prior.get("session_id") or prior.get("destination") != destination:
                    raise ValueError("DISCOVERY_PREDECESSOR_REQUIRED")
                gate.update(
                    session_id=prior["session_id"],
                    purpose="CACHED_PUBLIC_MENTIONS_AND_PLANNING",
                    content_ids=[
                        r[0]
                        for r in con.execute(
                            "SELECT DISTINCT a.content_id FROM extraction_attempts a JOIN source_contents c ON c.content_id=a.content_id WHERE a.batch_id=? AND c.account_scope=?",
                            (CURRENT_IDENTIFIER, scope),
                        )
                    ],
                )
                if not gate["content_ids"]:
                    raise ValueError("DISCOVERY_SOURCE_UNAVAILABLE")
            if self.identifier == REVISION_IDENTIFIER:
                previous = con.execute(
                    "SELECT gate_json FROM research_continuations WHERE continuation_id=? AND account_scope=?",
                    (DISCOVERY_IDENTIFIER, scope),
                ).fetchone()
                prior = json.loads(previous[0]) if previous else {}
                session = con.execute(
                    "SELECT state_json,revision FROM preview_sessions WHERE session_id=? AND account_scope=?",
                    (prior.get("session_id"), scope),
                ).fetchone()
                p = json.loads(session[0]).get("planning", {}) if session else {}
                if not p.get("adopted") or prior.get("destination") != destination:
                    raise ValueError("REVISION_PREDECESSOR_REQUIRED")
                from .revisions import base
                from travel_agent.preview.projection import fingerprint

                gate.update(
                    session_id=prior["session_id"],
                    content_ids=prior["content_ids"],
                    purpose="ADOPTED_PLAN_REVISION",
                    original_adopted_hash=fingerprint(base(p["adopted"])),
                    original_revision=session[1],
                )
            con.execute(
                "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
                (
                    self.identifier,
                    scope,
                    DISCOVERY_IDENTIFIER
                    if self.identifier == REVISION_IDENTIFIER
                    else CURRENT_IDENTIFIER
                    if self.identifier == DISCOVERY_IDENTIFIER
                    else IDENTIFIER
                    if self.identifier == CURRENT_IDENTIFIER
                    else "P05_EXPLICIT_USER_AUTHORIZATION",
                    json.dumps(config, sort_keys=True),
                    db.stamp(),
                    db.stamp(),
                    json.dumps(self.limits, sort_keys=True),
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
                (json.dumps(state["gate"], ensure_ascii=False), self.identifier),
            )
        return state

    def reserve_for_trip(self, scope: str, sid: str, kind: str, identity: str) -> None:
        with self.store.db.transaction():
            self.check_trip(scope, sid, bind=True)
            self.reserve_count(kind, identity, self.limits)

    def summary(self) -> dict[str, Any]:
        state = self.state()
        used = {k.lower(): 0 for k in self.limits}
        for kind, count in self.store.db.connection.execute(
            "SELECT kind,count(*) FROM continuation_operations WHERE continuation_id=? GROUP BY kind",
            (self.identifier,),
        ):
            used[kind.lower()] = count
        return {
            "used": used,
            "remaining": {k.lower(): v - used[k.lower()] for k, v in self.limits.items()},
            "closed": bool(state["finished_at"]),
            "gate": state["gate"]["status"],
        }
