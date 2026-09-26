"""P03 specialization of the existing continuation ledger, not a second ledger."""

from hashlib import sha256
import json
from typing import Any
from travel_agent.research.bounded import BoundedBudget
from travel_agent.research.store import EvidenceStore

IDENTIFIER = "p03-amap-route-check"
LIMITS = {"MAP_PLACE": 8, "MAP_ROUTE": 8}


class MapBudget(BoundedBudget):
    def __init__(self, store: EvidenceStore):
        super().__init__(store, IDENTIFIER)

    def initialize(self, scope: str, session_id: str, option_id: str) -> None:
        config = {
            "workspace": sha256(str(self.store.db.path.resolve()).encode()).hexdigest(),
            "host": "restapi.amap.com",
            "session_id": session_id,
            "option_id": option_id,
        }
        with self.store.db.transaction() as con:
            old = con.execute(
                "SELECT account_scope,config_json,limits_json FROM research_continuations WHERE continuation_id=?",
                (IDENTIFIER,),
            ).fetchone()
            if old:
                if old[0] != scope or json.loads(old[1]) != config or json.loads(old[2]) != LIMITS:
                    raise ValueError("MAP_GRANT_BINDING_CHANGED")
                return
            con.execute(
                "INSERT INTO research_continuations VALUES(?,?,?,?,?,?,NULL,?,?)",
                (
                    IDENTIFIER,
                    scope,
                    "p021-current-selection",
                    json.dumps(config, sort_keys=True),
                    self.store.db.stamp(),
                    self.store.db.stamp(),
                    json.dumps(LIMITS),
                    '{"status":"PASS"}',
                ),
            )

    def check_binding(self, scope: str, session_id: str, option_id: str) -> dict[str, Any]:
        state = self.state()
        if (
            state["account_scope"] != scope
            or state["config"]["session_id"] != session_id
            or state["config"]["option_id"] != option_id
            or state["limits"] != LIMITS
            or state["finished_at"]
        ):
            raise ValueError("MAP_GRANT_BINDING_CHANGED")
        return state

    def reserve_map(
        self, kind: str, payload: str, scope: str, session_id: str, option_id: str
    ) -> None:
        with self.store.db.transaction():
            self.check_binding(scope, session_id, option_id)
            self.reserve_count(kind, payload, LIMITS)

    def summary(self) -> dict[str, Any]:
        self.state()
        used = {k.lower(): 0 for k in LIMITS}
        for r in self.store.db.connection.execute(
            "SELECT kind,count(*) FROM continuation_operations WHERE continuation_id=? GROUP BY kind",
            (IDENTIFIER,),
        ):
            used[r[0].lower()] = r[1]
        return {
            "used": used,
            "remaining": {k.lower(): v - used[k.lower()] for k, v in LIMITS.items()},
            "total_used": sum(used.values()),
            "total_limit": 16,
        }
