"""Versioned private detail text. Never accepts search results or browser state."""

from dataclasses import asdict
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from travel_agent.domain.models import EvidenceBundle, SourcePolicy, validator
from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT, is_private, scope_allowed
from travel_agent.persistence.database import Database

from .canonical import canonicalize
from .extractor import ExtractionResult, policy_allows_model
from .models import DetailMaterial


def content_hash(raw_text: str, dom_text: str | None) -> str:
    return sha256(json.dumps([raw_text, dom_text], ensure_ascii=False).encode()).hexdigest()


def validate_content(data: dict[str, Any]) -> None:
    validator("SourceContent").validate(data)
    # Validate both raw representations before considering the chosen normalized body.
    for field in ("raw_text", "dom_text", "normalized_text"):
        text = data[field] or ""
        if len(text) > 1_000_000 or SENSITIVE_RESEARCH_TEXT.search(text):
            raise ValueError("SOURCE_CONTENT_SENSITIVE_OR_OVERSIZED")
    canonical = canonicalize(data["raw_text"], data["dom_text"],
                             completeness=data["content_completeness"])
    if (data["content_hash"] != content_hash(data["raw_text"], data["dom_text"])
        or data["normalized_text"] != canonical.text
        or data["body_origin"] != canonical.origin
        or data["canonical_relation"] != canonical.relation
        or data["truncation_risk"] != canonical.truncation_risk
        or data["body_blocks"] != [asdict(block) for block in canonical.blocks]):
        raise ValueError("SOURCE_CONTENT_LINEAGE_INVALID")


class SourceContentStore:
    def __init__(self, db: Database):
        self.db = db

    def _allowed(self, policy: SourcePolicy, scope: str) -> bool:
        return bool(is_private(policy) and scope_allowed(policy, scope)
                    and policy["allow_persist_raw"] and policy["allow_persist_metadata"]
                    and policy["allow_persist_derived"]
                    and policy_allows_model(policy, external=False, now=self.db.clock()))

    def put(self, run_id: str, revision: int, material: DetailMaterial,
            extraction: ExtractionResult, policy: SourcePolicy) -> str | None:
        if not is_private(policy) or policy.get("source_content_retention") == "EPHEMERAL":
            return None
        if self.db.version < 5:
            raise ValueError("SOURCE_CONTENT_REQUIRES_V5")
        with self.db.transaction() as con:
            run = con.execute(
                "SELECT q.account_scope FROM research_runs r JOIN research_questions q "
                "ON q.research_id=r.research_id WHERE r.run_id=? AND r.revision=? "
                "AND q.current_revision=r.revision AND r.status='RUNNING'", (run_id, revision),
            ).fetchone()
            if run is None:
                return None
            scope = run[0]
            if not self._allowed(policy, scope):
                raise PermissionError("SOURCE_CONTENT_POLICY_DENIED")
            attempt = con.execute(
                "SELECT 1 FROM research_ops WHERE run_id=? AND kind='DETAIL' "
                "AND fingerprint IN (?,?)", (run_id, material.source_id, material.source_id + ":fallback"),
            ).fetchone()
            source = con.execute("SELECT account_scope,policy_id FROM sources WHERE source_id=? "
                                 "AND deleted_at IS NULL", (material.source_id,)).fetchone()
            canonical = extraction.canonical
            if (not attempt or not material.identity_match or source is None
                or source[0] != scope or source[1] != policy["policy_id"]
                or extraction.bundle["source_id"] != material.source_id
                or extraction.bundle["policy_id"] != policy["policy_id"]
                or canonical is None or not canonical.blocks
                or canonical.completeness not in {"FULL_TEXT", "PARTIAL_TEXT"}):
                raise ValueError("SOURCE_CONTENT_REQUIRES_RESEARCHED_DETAIL")
            retention = policy["source_content_retention"]
            retrieved = datetime.fromisoformat(material.fetched_at)
            expires = (retrieved + timedelta(days=int(retention.split("_")[0]))).isoformat() \
                if retention in {"7_DAYS", "30_DAYS"} else None
            data = {
                "content_id": "content-" + uuid4().hex, "source_id": material.source_id,
                "account_scope": scope, "policy_id": policy["policy_id"], "policy_version": policy["version"],
                "content_hash": content_hash(material.body, material.dom_body),
                "raw_text": material.body, "dom_text": material.dom_body,
                "normalized_text": canonical.text, "normalization_version": 1,
                "content_completeness": canonical.completeness, "retrieved_at": material.fetched_at,
                "last_retrieved_at": material.fetched_at, "published_at": material.published_at,
                "body_origin": canonical.origin, "canonical_relation": canonical.relation,
                "truncation_risk": canonical.truncation_risk, "image_count": material.image_count,
                "image_status": "IMAGE_NOT_ANALYZED", "retention": retention, "expires_at": expires,
                "body_blocks": [asdict(block) for block in canonical.blocks],
            }
            validate_content(data)
            previous = con.execute(
                "SELECT content_id,last_retrieved_at FROM source_contents WHERE source_id=? "
                "AND account_scope=? AND content_hash=?", (material.source_id, scope, data["content_hash"]),
            ).fetchone()
            if previous is not None:
                identifier = str(previous[0])
                if retrieved > datetime.fromisoformat(previous[1]):
                    con.execute("UPDATE source_contents SET last_retrieved_at=? WHERE content_id=?",
                                (material.fetched_at, identifier))
            else:
                identifier = str(data["content_id"])
                values = {key: value for key, value in data.items() if key != "body_blocks"}
                con.execute("INSERT INTO source_contents (" + ",".join(values) + ") VALUES ("
                            + ",".join("?" for _ in values) + ")", tuple(values.values()))
                for block in canonical.blocks:
                    con.execute("INSERT INTO source_body_blocks VALUES(?,?,?,?,?,?,?,?)",
                                (identifier, block.block_index, block.text, block.start, block.end,
                                 block.locator, block.origin, int(block.truncation_risk)))
            con.execute("INSERT OR IGNORE INTO research_run_contents VALUES(?,?)", (run_id, identifier))
            return identifier

    def purge_expired(self, account_scope: str) -> int:
        if self.db.version < 5:
            return 0
        with self.db.transaction() as con:
            expired = [row[0] for row in con.execute(
                "SELECT content_id,expires_at FROM source_contents WHERE account_scope=? "
                "AND expires_at IS NOT NULL", (account_scope,),
            ) if datetime.fromisoformat(row[1]) <= self.db.clock()]
            con.executemany("DELETE FROM source_contents WHERE content_id=?", [(key,) for key in expired])
        return len(expired)

    def load(self, source_id: str, account_scope: str, *, purge: bool = True) -> tuple[dict[str, Any], ...]:
        if self.db.version < 5:
            return ()
        if purge:
            self.purge_expired(account_scope)
        result = []
        for row in self.db.connection.execute(
            "SELECT c.* FROM source_contents c JOIN sources s ON s.source_id=c.source_id "
            "WHERE c.source_id=? AND c.account_scope=? AND s.account_scope=? "
            "AND s.deleted_at IS NULL ORDER BY c.rowid", (source_id, account_scope, account_scope),
        ):
            if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= self.db.clock():
                continue
            policies = self.db.connection.execute(
                "SELECT policy_json FROM source_policies WHERE policy_id=? AND (version=? OR version="
                "(SELECT max(version) FROM source_policies WHERE policy_id=?))",
                (row["policy_id"], row["policy_version"], row["policy_id"]),
            ).fetchall()
            if not policies or not all(self._allowed(SourcePolicy(json.loads(p[0])), account_scope)
                                       for p in policies):
                continue
            data = dict(row)
            data["truncation_risk"] = bool(data["truncation_risk"])
            data["body_blocks"] = [
                {"block_index": b["block_index"], "text": b["normalized_text"],
                 "start": b["start_offset"], "end": b["end_offset"], "locator": b["locator"],
                 "origin": b["origin"], "truncation_risk": bool(b["truncation_risk"])}
                for b in self.db.connection.execute(
                    "SELECT * FROM source_body_blocks WHERE content_id=? ORDER BY block_index",
                    (data["content_id"],),
                )
            ]
            validate_content(data)
            result.append(data)
        return tuple(result)


def audit_grounding(bundle: EvidenceBundle, contents: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Recheck persisted exact quotes and conditions against their versioned blocks."""
    checked = unsupported = 0
    for claim in bundle["claims"]:
        meta = bundle.get("claim_metadata", {}).get(claim["claim_id"], {})
        supported = False
        for content in contents:
            if content["source_id"] != bundle["source_id"]:
                continue
            blocks = {b["block_index"]: b for b in content["body_blocks"]}
            try:
                prefix, span = claim["locator"].rsplit(":chars:", 1)
                low, high = map(int, span.split("-"))
                cited = [blocks[i] for i in meta["source_block_ids"]]
                supported = bool(
                    claim["kind"] == "AUTHOR_OPINION" and cited
                    and content["normalized_text"][low:high] == claim["text"]
                    and any(b["start"] <= low < high <= b["end"]
                            and b["locator"].rsplit(":chars:", 1)[0] == prefix for b in cited)
                    and meta["block_locators"] == [b["locator"] for b in cited]
                    and all(any(condition in b["text"] for b in cited)
                            for condition in meta["applicable_conditions"])
                )
                ref = meta.get("reference_selection")
                if supported and ref:
                    from .references import catalog
                    view = canonicalize(content["raw_text"], content["dom_text"], completeness=content["content_completeness"])
                    directory = catalog(view, content["source_id"], content["content_id"], content["content_hash"])
                    selected = [ref["statement"], *ref["conditions"]]
                    supported = bool(
                        all(ref[k] == v for k, v in directory["binding"].items())
                        and ref["manifest_hash"] == directory["manifest_hash"]
                        and all(directory["spans"].get(s["span_id"]) == s for s in selected)
                        and ref["statement"]["locator"] == claim["locator"]
                        and {s["block_index"] for s in selected} == set(meta["source_block_ids"])
                        and set(meta["applicable_conditions"]) == {
                            view.text[s["start"]:s["end"]] for s in ref["conditions"]})
            except (KeyError, ValueError, TypeError):
                supported = False
            if supported:
                break
        checked += 1
        unsupported += int(not supported)
    return {"checked": checked, "unsupported": unsupported,
            "locator_coverage": (checked - unsupported) / checked if checked else None}
