"""Fixed T06.5 authorization and durable permits; no browser or model dispatch here."""

from hashlib import sha256
import json
from typing import Any

from travel_agent.providers.llm import OpenAICompatibleProvider
from .retry import _config
from .store import EvidenceStore

CONTINUATION = "t065-coverage-first-plan"
LIMITS = {"CONNECT": 1, "SEARCH": 1, "DETAIL": 2, "MODEL": 2}


class ContinuationBudget:
    def __init__(self, store: EvidenceStore) -> None:
        self.store = store

    def grant(self, account_scope: str, predecessor: str, provider: OpenAICompatibleProvider) -> None:
        config = _config(provider, 180)
        if provider.timeout != 120:
            raise ValueError("CONTINUATION_REQUIRES_120_180")
        with self.store.db.transaction() as con:
            previous = con.execute("SELECT config_json FROM extraction_authorizations WHERE "
                "authorization_id='t064-response-timeout-once' AND account_scope=? AND consumed_at IS NOT NULL",
                (account_scope,)).fetchone()
            if previous is None or json.loads(previous[0]) != config:
                raise ValueError("CONTINUATION_PROVIDER_CHANGED_OR_PREDECESSOR_MISSING")
            values = (account_scope, predecessor, json.dumps(config, sort_keys=True))
            existing = con.execute("SELECT account_scope,predecessor,config_json FROM research_continuations "
                                   "WHERE continuation_id=?", (CONTINUATION,)).fetchone()
            if existing is not None and tuple(existing) != values:
                raise ValueError("CONTINUATION_IMMUTABLE")
            con.execute("INSERT OR IGNORE INTO research_continuations(continuation_id,account_scope,predecessor,config_json,created_at,started_at,finished_at) VALUES(?,?,?,?,?,NULL,NULL)",
                        (CONTINUATION, *values, self.store.db.stamp()))

    def start(self) -> None:
        with self.store.db.transaction() as con:
            if con.execute("UPDATE research_continuations SET started_at=? WHERE continuation_id=? "
                           "AND started_at IS NULL", (self.store.db.stamp(), CONTINUATION)).rowcount != 1:
                raise ValueError("CONTINUATION_ALREADY_STARTED_NO_RETRY")

    def reserve(self, kind: str, fingerprint: str) -> None:
        if kind not in LIMITS:
            raise ValueError("UNKNOWN_CONTINUATION_OPERATION")
        with self.store.db.transaction() as con:
            state = con.execute("SELECT started_at,finished_at FROM research_continuations WHERE continuation_id=?",
                                (CONTINUATION,)).fetchone()
            if state is None or not state[0] or state[1]:
                raise ValueError("CONTINUATION_NOT_ACTIVE")
            total = con.execute("SELECT count(*) FROM continuation_operations WHERE continuation_id=? AND kind=?",
                                (CONTINUATION, kind)).fetchone()[0]
            digest = sha256(fingerprint.encode()).hexdigest()
            if total >= LIMITS[kind] or con.execute("SELECT 1 FROM continuation_operations WHERE "
                "continuation_id=? AND kind=? AND fingerprint=?", (CONTINUATION, kind, digest)).fetchone():
                raise ValueError("CONTINUATION_BUDGET_OR_DUPLICATE_DENIED")
            con.execute("INSERT INTO continuation_operations VALUES(?,?,?,?)",
                        (CONTINUATION, kind, digest, self.store.db.stamp()))

    def summary(self) -> dict[str, Any]:
        used = {k.lower(): 0 for k in LIMITS}
        for row in self.store.db.connection.execute("SELECT kind,count(*) FROM continuation_operations "
                "WHERE continuation_id=? GROUP BY kind", (CONTINUATION,)):
            used[row[0].lower()] = row[1]
        return {"authorization": CONTINUATION, "used": used,
                "remaining": {k.lower(): v - used[k.lower()] for k, v in LIMITS.items()}}

    def finish(self) -> None:
        self.store.db.connection.execute("UPDATE research_continuations SET finished_at=? WHERE continuation_id=?",
                                         (self.store.db.stamp(), CONTINUATION))

    def check_worker(self, attempt: str, provider: OpenAICompatibleProvider) -> None:
        con = self.store.db.connection
        row = con.execute("SELECT a.*,c.source_id,c.account_scope FROM extraction_attempts a JOIN source_contents c "
                          "USING(content_id) WHERE attempt_id=?", (attempt,)).fetchone()
        grant = con.execute("SELECT * FROM research_continuations WHERE continuation_id=?", (CONTINUATION,)).fetchone()
        if (row is None or grant is None or row["batch_id"] != CONTINUATION or row["attempt_number"] != 1
            or row["account_scope"] != grant["account_scope"] or grant["finished_at"]
            or json.loads(grant["config_json"]) != _config(provider, 180)
            or not con.execute("SELECT 1 FROM continuation_operations WHERE continuation_id=? AND kind='MODEL' "
                "AND fingerprint=?", (CONTINUATION, sha256(row["source_id"].encode()).hexdigest())).fetchone()):
            raise ValueError("CONTINUATION_WORKER_DENIED")
