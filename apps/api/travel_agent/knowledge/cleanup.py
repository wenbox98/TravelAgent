"""Explicit logical cleanup: keep identities/reviews/ledgers, never delete sources."""

import json
from typing import Any
from travel_agent.preview.projection import fingerprint
from travel_agent.research.content_store import SourceContentStore
from .store import Library, binding


def preview(db: Any, scope: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    cards = [Library(db, scope).get(r) for r in refs]
    sources = {s["content_id"]: s for c in cards for s in c["sources"]}
    items = []
    for cid, s in sources.items():
        raw = next(
            (
                c
                for c in SourceContentStore(db).load(s["source_id"], scope, purge=False)
                if c["content_id"] == cid
            ),
            None,
        )
        if raw is None:
            raise ValueError("KNOWLEDGE_RAW_UNAVAILABLE")
        items.append(
            dict(
                content_id=cid,
                content_hash=raw["content_hash"],
                characters=len(raw["normalized_text"]),
                cards=[
                    binding(c) for c in cards if any(x["content_id"] == cid for x in c["sources"])
                ],
            )
        )
    return dict(
        items=items,
        preview_hash=fingerprint(items),
        meaning="仅此应用库内载荷逻辑清理；保留来源身份、有限派生条目、审核及账本。备份和其他库保留，不作为恢复兜底。",
    )


def clear(db: Any, scope: str, refs: list[dict[str, Any]], expected: str) -> dict[str, Any]:
    with db.transaction():
        v = preview(db, scope, refs)
        if expected != v["preview_hash"] or not v["items"]:
            raise ValueError("KNOWLEDGE_PREVIEW_CHANGED")
        if db.connection.execute(
            "SELECT 1 FROM preview_jobs WHERE account_scope=? AND status IN ('QUEUED','RUNNING','WAITING_LOGIN')",
            (scope,),
        ).fetchone():
            raise ValueError("KNOWLEDGE_JOB_RUNNING")
        ids = {s["content_id"] for s in v["items"]}
        raw: list[str] = []
        source_ids = set()
        for cid in ids:
            r = db.connection.execute(
                "SELECT source_id,raw_text,dom_text,normalized_text FROM source_contents WHERE content_id=?",
                (cid,),
            ).fetchone()
            source_ids.add(r[0])
            raw.extend(t for t in r[1:] if t and len(t) > 40)
            db.connection.execute(
                "UPDATE knowledge_raw_state SET state='USER_CLEARED',changed_at=? WHERE content_id=?",
                (db.stamp(), cid),
            )
            db.connection.execute(
                "UPDATE source_contents SET raw_text='',dom_text=NULL,normalized_text='' WHERE content_id=?",
                (cid,),
            )
            db.connection.execute("DELETE FROM source_body_blocks WHERE content_id=?", (cid,))
        for source_id in source_ids:
            db.connection.execute("DELETE FROM chunks WHERE source_id=?", (source_id,))
        # Known full-context copies in discovery snapshots or envelopes, not derived claims.
        marker = "RAW_CLEARED_REPLAY_UNAVAILABLE"
        removed = 0

        def scrub(value: Any, relevant: bool = False) -> Any:
            nonlocal removed
            if isinstance(value, dict):
                relevant = (
                    relevant
                    or value.get("content_id") in ids
                    or value.get("source_id") in source_ids
                )
                out = {}
                for k, x in value.items():
                    if relevant and k in {
                        "parent_blocks",
                        "body_blocks",
                        "span_catalog",
                        "raw_text",
                        "dom_text",
                        "normalized_text",
                        "full_text",
                    }:
                        out[k] = [] if isinstance(x, list) else marker
                        removed += 1
                    else:
                        out[k] = scrub(x, relevant)
                return out
            if isinstance(value, list):
                return [scrub(x, relevant) for x in value]
            if isinstance(value, str) and any(t in value for t in raw):
                removed += 1
                return marker
            return value

        for table in (
            "preview_sessions",
            "preview_jobs",
            "extraction_candidates",
            "context_review_runs",
            "review_revalidations",
            "extraction_attempts",
        ):
            all_columns = {
                r[1] for r in db.connection.execute('PRAGMA table_info("' + table + '")')
            }
            columns = [column for column in all_columns if column.endswith("_json")]
            if "account_scope" in all_columns:
                where, params = "account_scope=?", (scope,)
            else:
                # Candidate/revalidation tables have no direct account column.
                where = (
                    "attempt_id IN (SELECT attempt_id FROM extraction_attempts a JOIN source_contents c USING(content_id) WHERE c.account_scope=?)"
                    if "attempt_id" in all_columns
                    else "original_review_id IN (SELECT review_id FROM context_review_runs WHERE account_scope=?)"
                )
                params = (scope,)
            for col in columns:
                for row in db.connection.execute(
                    'SELECT rowid,"' + col + '" FROM "' + table + '" WHERE ' + where, params
                ).fetchall():
                    if not row[1]:
                        continue
                    value = json.loads(row[1])
                    out = scrub(value)
                    if out != value:
                        db.connection.execute(
                            'UPDATE "' + table + '" SET "' + col + '"=? WHERE rowid=?',
                            (json.dumps(out, ensure_ascii=False), row[0]),
                        )
        return dict(
            cleared=len(ids), redacted_copies=removed, logical_only=True, backups_retained=True
        )
