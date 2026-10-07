"""Versioned knowledge reads use metadata, never raw bodies or model history."""

from datetime import datetime
import json
import re
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator
from travel_agent.preview.projection import fingerprint, safe_text
from travel_agent.domain.models import SourcePolicy
from travel_agent.domain.source_policy import scope_allowed, has_usage_basis

RULE = "knowledge-rules-1"
KINDS = {"SOURCE_REFERENCE", "PLACE_LEAD", "PLAN_PATTERN"}


def terms(value: str) -> set[str]:
    words = re.findall(r"[\w]+", value.lower(), re.UNICODE)
    return {
        t
        for w in words
        for t in ([w] if len(w) <= 2 else [w[i : i + 2] for i in range(len(w) - 1)])
    }


def binding(card: dict[str, Any]) -> dict[str, Any]:
    return {k: card[k] for k in ("card_id", "version", "card_hash")}


@contextmanager
def no_raw(db: Any) -> Iterator[None]:
    """Enforced on the actual SQL connection, also used in real planning."""

    def guard(action: int, table: str, column: str, *_: Any) -> int:
        if action == sqlite3.SQLITE_READ and (
            table in {"source_body_blocks", "extraction_candidates", "context_review_runs"}
            or (
                table == "source_contents" and column in {"raw_text", "dom_text", "normalized_text"}
            )
            or (table == "preview_jobs" and column == "request_json")
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    db.connection.set_authorizer(guard)
    try:
        yield
    finally:
        db.connection.set_authorizer(None)


class Library:
    def __init__(self, db: Any, scope: str):
        self.db, self.scope = db, scope
        try:
            db.connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(card_id UNINDEXED,version UNINDEXED,tokens)"
            )
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False

    def source(self, item: dict[str, Any], *, outbound: bool = False) -> str:
        row = self.db.connection.execute(
            "SELECT s.deleted_at,s.policy_id,c.content_hash,c.normalization_version,c.expires_at,r.state "
            "FROM sources s JOIN source_contents c USING(source_id) "
            "JOIN knowledge_raw_state r USING(content_id) "
            "WHERE s.source_id=? AND c.content_id=? AND s.account_scope=? AND c.account_scope=?",
            (item["source_id"], item["content_id"], self.scope, self.scope),
        ).fetchone()
        if (
            not row
            or row[0]
            or row[2] != item["content_hash"]
            or row[3] != item["normalization_version"]
            or row[5] == "UNEXPECTED_CHANGE"
        ):
            raise ValueError("KNOWLEDGE_SOURCE_UNAVAILABLE")
        if (
            row[5] != "USER_CLEARED"
            and row[4]
            and datetime.fromisoformat(row[4]) <= self.db.clock()
        ):
            raise ValueError("KNOWLEDGE_EXPIRED")
        if self.db.connection.execute(
            "SELECT 1 FROM knowledge_withdrawals WHERE account_scope=? AND source_id=?",
            (self.scope, item["source_id"]),
        ).fetchone():
            raise ValueError("KNOWLEDGE_SOURCE_WITHDRAWN")
        policies = self.db.connection.execute(
            "SELECT policy_json FROM source_policies WHERE policy_id=? AND (version=? OR version=(SELECT max(version) FROM source_policies WHERE policy_id=?))",
            (row[1], item["policy_version"], row[1]),
        ).fetchall()
        for policy in policies:
            p = SourcePolicy(json.loads(policy[0]))
            flags = ["allow_read", "allow_persist_metadata", "allow_persist_derived"] + (
                ["allow_inference", "allow_external_model"] if outbound else []
            )
            if (
                not has_usage_basis(p)
                or not scope_allowed(p, self.scope)
                or not all(p[k] for k in flags)
                or not p["reviewed_at"]
                or (p["expires_at"] and datetime.fromisoformat(p["expires_at"]) <= self.db.clock())
            ):
                raise ValueError("KNOWLEDGE_POLICY_DENIED")
        if not policies:
            raise ValueError("KNOWLEDGE_POLICY_DENIED")
        return str(row[5])

    def get(self, ref: dict[str, Any], *, outbound: bool = False) -> dict[str, Any]:
        r = self.db.connection.execute(
            "SELECT * FROM knowledge_cards WHERE card_id=? AND account_scope=? ORDER BY version DESC LIMIT 1",
            (ref["card_id"], self.scope),
        ).fetchone()
        if (
            not r
            or r["status"] != "ACTIVE"
            or r["version"] != ref["version"]
            or r["card_hash"] != ref["card_hash"]
        ):
            raise ValueError("KNOWLEDGE_STALE_OR_DELETED")
        c = json.loads(r["data_json"])
        if (
            fingerprint(c) != r["card_hash"]
            or not c.get("attested_at")
            or c.get("generator") != RULE
            or not c.get("sources")
        ):
            raise ValueError("KNOWLEDGE_INVALID_ATTESTATION")
        if c["kind"] == "SOURCE_REFERENCE":
            for claim_id in c["evidence_links"]:
                claim = self.db.connection.execute(
                    "SELECT text,deleted_at FROM claims WHERE claim_id=?", (claim_id,)
                ).fetchone()
                if not claim or claim[1] or claim[0] != c["text"]:
                    raise ValueError("KNOWLEDGE_SOURCE_UNAVAILABLE")
            for context in c.get("scoped_references", []):
                claim = self.db.connection.execute(
                    "SELECT text,deleted_at,source_id FROM claims WHERE claim_id=?",
                    (context["claim_id"],),
                ).fetchone()
                if (
                    not claim
                    or claim[1]
                    or claim[0] != context["text"]
                    or claim[2] not in {s["source_id"] for s in c["sources"]}
                ):
                    raise ValueError("KNOWLEDGE_SOURCE_UNAVAILABLE")
        for dependency in c.get("dependencies", []):
            self.get(dependency, outbound=outbound)
        states = [self.source(s, outbound=outbound) for s in c["sources"]]
        c.update(binding(dict(r)))
        c["raw_retention"] = sorted(
            {
                r[0]
                for source in c["sources"]
                for r in self.db.connection.execute(
                    "SELECT cleanup_policy FROM knowledge_raw_state WHERE content_id=?",
                    (source["content_id"],),
                )
            }
        )
        c["raw_availability"] = "USER_CLEARED" if "USER_CLEARED" in states else "AVAILABLE"
        c["validation_basis"] = (
            "HISTORICAL_ATTESTATION" if "USER_CLEARED" in states else "ATTESTED_WHEN_ORGANIZED"
        )
        return dict(c)

    def save(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        """Internal organizer only: the HTTP API accepts no caller-authored card."""
        if data["kind"] not in KINDS or not data["sources"] or not data.get("attested_at"):
            raise ValueError("KNOWLEDGE_INVALID_ATTESTATION")
        cid = "card-" + fingerprint([self.scope, key])[:28]
        with self.db.transaction():
            old = self.db.connection.execute(
                "SELECT * FROM knowledge_cards WHERE card_id=? ORDER BY version DESC LIMIT 1",
                (cid,),
            ).fetchone()
            if old and old["status"] != "ACTIVE":
                raise ValueError("KNOWLEDGE_STALE_OR_DELETED")
            content = dict(data, generator=RULE)
            # Rechecking identical material is not a new semantic version.
            if old:
                content["attested_at"] = json.loads(old["data_json"])["attested_at"]
                if fingerprint(content) == old["card_hash"]:
                    return self.get(binding(dict(old)))
            version = old["version"] + 1 if old else 1
            for s in content["sources"]:
                self.db.connection.execute(
                    "INSERT OR IGNORE INTO knowledge_raw_state VALUES(?,'AVAILABLE','PERSISTENT',?)",
                    (s["content_id"], self.db.stamp()),
                )
                self.source(s)
            self.db.connection.execute(
                "INSERT INTO knowledge_cards VALUES(?,?,?,?,'ACTIVE',?,?,?,?,?)",
                (
                    cid,
                    version,
                    self.scope,
                    content["kind"],
                    content["destination"],
                    int(content["test_input"]),
                    self.db.stamp(),
                    fingerprint(content),
                    json.dumps(content, ensure_ascii=False),
                ),
            )
            self.index(cid, version, content)
            return self.get(dict(card_id=cid, version=version, card_hash=fingerprint(content)))

    def index(self, cid: str, version: int, data: dict[str, Any]) -> None:
        self.db.connection.execute("DELETE FROM knowledge_terms WHERE card_id=?", (cid,))
        text = " ".join(
            [
                data["title"],
                data["destination"],
                *data["entities"],
                *data["tags"],
                *data["conditions"],
                data["text"],
            ]
        )
        self.db.connection.executemany(
            "INSERT OR IGNORE INTO knowledge_terms VALUES(?,?,?)",
            [(t, cid, version) for t in terms(text)],
        )
        if self.fts:
            self.db.connection.execute("DELETE FROM knowledge_fts WHERE card_id=?", (cid,))
            self.db.connection.execute(
                "INSERT INTO knowledge_fts VALUES(?,?,?)",
                (cid, version, " ".join(t.encode().hex() for t in sorted(terms(text)))),
            )

    def rebuild(self) -> None:
        with self.db.transaction():
            self.db.connection.execute(
                "DELETE FROM knowledge_terms WHERE card_id IN (SELECT card_id FROM knowledge_cards WHERE account_scope=?)",
                (self.scope,),
            )
            for r in self.db.connection.execute(
                "SELECT * FROM knowledge_cards k WHERE account_scope=? AND version=(SELECT max(version) FROM knowledge_cards WHERE card_id=k.card_id)",
                (self.scope,),
            ).fetchall():
                try:
                    c = self.get(binding(dict(r)))
                    self.index(r["card_id"], r["version"], c)
                except ValueError:
                    continue

    def search(
        self,
        query: str = "",
        destination: str = "",
        kind: str = "",
        include_test: bool = False,
        since: str = "",
    ) -> dict[str, Any]:
        safe_text(query, 160)
        safe_text(destination, 80)
        if kind and kind not in KINDS:
            raise ValueError("INVALID_INPUT")
        if since:
            datetime.fromisoformat(since)
        rows = self.db.connection.execute(
            "SELECT * FROM knowledge_cards k WHERE account_scope=? AND status='ACTIVE' AND (?='' OR destination=?) AND (?='' OR kind=?) AND (? OR test_input=0) AND (?='' OR created_at>=?) AND version=(SELECT max(version) FROM knowledge_cards WHERE card_id=k.card_id) ORDER BY created_at DESC,card_id LIMIT 251",
            (self.scope, destination, destination, kind, kind, int(include_test), since, since),
        ).fetchall()
        result = []
        wanted = terms(query)
        # Limit is explicit; policy filtering precedes ranking. No raw fallback.
        for r in rows[:250]:
            try:
                card = self.get(binding(dict(r)))
            except ValueError:
                continue
            found = {
                t[0]
                for t in self.db.connection.execute(
                    "SELECT term FROM knowledge_terms WHERE card_id=? AND version=?",
                    (r["card_id"], r["version"]),
                )
            }
            if self.fts and wanted:
                hit = self.db.connection.execute(
                    "SELECT bm25(knowledge_fts) FROM knowledge_fts WHERE knowledge_fts MATCH ? AND card_id=? AND version=?",
                    (
                        " AND ".join('"' + t.encode().hex() + '"' for t in sorted(wanted)),
                        r["card_id"],
                        r["version"],
                    ),
                ).fetchone()
                if not hit:
                    continue
                card["rank"] = hit[0]
            elif wanted and not wanted <= found:
                continue
            card["match_reason"] = "关键词及条件匹配" if wanted else "目的地/类型筛选"
            card["applicability"] = "UNVERIFIED_KEEP_CONDITIONS"
            result.append(card)
        result.sort(key=lambda c: (c.get("rank", 0), c["kind"], c["title"]))
        return dict(
            engine="FTS5_BIGRAM" if self.fts else "LIMITED_TERM_INDEX_FALLBACK",
            mode="LOCAL_KEYWORD_RETRIEVAL",
            vector="NOT_IMPLEMENTED",
            cards=result[:60],
            bounded=len(rows) > 250 or len(result) > 60,
            source_count=len({s["source_id"] for c in result[:60] for s in c["sources"]}),
            sufficient=False,
            gaps=["命中不等于适配；交通、季节和同名地点仍须逐项确认。"],
            conflicting_conditions=sorted({v for c in result[:60] for v in c["conditions"]}),
        )

    def remove(
        self, refs: list[dict[str, Any]], *, withdraw_sources: bool = False
    ) -> dict[str, int]:
        with self.db.transaction():
            cards = [self.get(r) for r in refs]
            ids = {c["card_id"] for c in cards}
            if withdraw_sources:
                sources = {s["source_id"] for c in cards for s in c["sources"]}
                for s in sources:
                    self.db.connection.execute(
                        "INSERT OR IGNORE INTO knowledge_withdrawals VALUES(?,?,?)",
                        (self.scope, s, self.db.stamp()),
                    )
                for r in self.db.connection.execute(
                    "SELECT card_id,data_json FROM knowledge_cards WHERE account_scope=?",
                    (self.scope,),
                ):
                    if sources & {s["source_id"] for s in json.loads(r[1])["sources"]}:
                        ids.add(r[0])
            # A card-derived pattern cannot outlive a removed supporting card.
            changed = True
            while changed:
                changed = False
                for row in self.db.connection.execute(
                    "SELECT card_id,data_json FROM knowledge_cards WHERE account_scope=? AND status='ACTIVE'",
                    (self.scope,),
                ):
                    if row[0] not in ids and any(
                        d["card_id"] in ids for d in json.loads(row[1]).get("dependencies", [])
                    ):
                        ids.add(row[0])
                        changed = True
            for cid in ids:
                self.db.connection.execute(
                    "UPDATE knowledge_cards SET status='DELETED' WHERE card_id=? AND account_scope=?",
                    (cid, self.scope),
                )
                self.db.connection.execute("DELETE FROM knowledge_terms WHERE card_id=?", (cid,))
                if self.fts:
                    self.db.connection.execute("DELETE FROM knowledge_fts WHERE card_id=?", (cid,))
            return dict(deleted=len(ids))

    def retention(self, refs: list[dict[str, Any]], policy: str) -> dict[str, Any]:
        """An explicit cleanup preference, never an automatic destructive timer."""
        if policy not in {"PERSISTENT", "READY_AFTER_ORGANIZED", "SESSION"}:
            raise ValueError("INVALID_INPUT")
        with self.db.transaction():
            cards = [self.get(r) for r in refs]
            ids = {s["content_id"] for c in cards for s in c["sources"]}
            if not ids:
                raise ValueError("INVALID_INPUT")
            for cid in ids:
                self.db.connection.execute(
                    "UPDATE knowledge_raw_state SET cleanup_policy=?,changed_at=? WHERE content_id=?",
                    (policy, self.db.stamp(), cid),
                )
            return dict(contents=len(ids), policy=policy, automatic_cleanup=False)
