"""Private bounded structured proposals, seven-day retention, local versioned replay."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4
from travel_agent.preview.projection import fingerprint
from . import revisions


def directory(db: Any) -> Path:
    return Path(db.path).parent / "planning-diagnostics"


def _path(db: Any, jid: str) -> Path:
    if not re.fullmatch(r"planning-[a-f0-9]{32}", jid):
        raise ValueError("DIAGNOSTIC_UNAVAILABLE")
    return directory(db) / (jid + ".json")


def retain(db: Any, row: Any, raw: Any, result: dict[str, Any]) -> dict[str, Any]:
    request = json.loads(row["request_json"])
    from . import advisory

    rules = advisory if request["payload"].get("protocol_version") == 4 else revisions
    replayable = raw is not None and rules.safe_shape(raw, request["payload"])
    record = dict(
        version=1,
        job_id=row["job_id"],
        account_scope=row["account_scope"],
        input_hash=fingerprint(request["payload"]),
        request_hash=fingerprint(request),
        base_revision=request.get("base_revision"),
        rule_version=rules.VERSION,
        protocol_version=request["payload"].get("protocol_version", 3),
        model_config_hash=fingerprint(
            db.connection.execute(
                "SELECT config_json FROM research_continuations WHERE continuation_id=?",
                (row["continuation_id"],),
            ).fetchone()[0]
        ),
        created_at=db.stamp(),
        expires_at=(db.clock() + timedelta(days=7)).isoformat(),
        replayable=replayable,
        proposals=raw if replayable else None,
    )
    path = _path(db, row["job_id"])
    path.parent.mkdir(exist_ok=True)
    with path.open("x", encoding="utf8") as f:
        json.dump(record, f, ensure_ascii=False)
    return dict(
        replayable=replayable,
        retention_days=7,
        expires_at=record["expires_at"],
        reason="STRUCTURE_RETAINED" if replayable else "UNSAFE_OR_UNAVAILABLE_STRUCTURE",
        adopted_affected=False,
        record_hash=fingerprint(record),
    )


def load(db: Any, scope: str, jid: str) -> tuple[dict[str, Any], dict[str, Any]]:
    row = db.connection.execute(
        "SELECT request_json,summary_json FROM preview_jobs WHERE job_id=? AND account_scope=?",
        (jid, scope),
    ).fetchone()
    path = _path(db, jid)
    if not row or not path.exists() or path.stat().st_size > 65536:
        raise ValueError("DIAGNOSTIC_UNAVAILABLE")
    record, request = json.loads(path.read_text("utf8")), json.loads(row[0])
    if (
        record["account_scope"] != scope
        or record["job_id"] != jid
        or record["request_hash"] != fingerprint(request)
        or record["input_hash"] != fingerprint(request["payload"])
        or json.loads(row[1] or "{}").get("local_diagnostic", {}).get("record_hash")
        != fingerprint(record)
    ):
        raise ValueError("DIAGNOSTIC_BINDING_CHANGED")
    if datetime.fromisoformat(record["expires_at"]) <= db.clock():
        raise ValueError("DIAGNOSTIC_EXPIRED")
    from . import advisory

    rules = advisory if record.get("protocol_version") == 4 else revisions
    if not record["replayable"] or not rules.safe_shape(record["proposals"], request["payload"]):
        raise ValueError("DIAGNOSTIC_NOT_REPLAYABLE")
    return record, request


def replay(db: Any, scope: str, jid: str, code_sha: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise ValueError("CODE_SHA_REQUIRED")
    record, request = load(db, scope, jid)
    from . import advisory

    rules = advisory if record.get("protocol_version") == 4 else revisions
    result = rules.validate(record["proposals"], request["payload"])
    output = dict(
        kind="LOCAL_REVALIDATION",
        original_job=jid,
        original_rule_version=record["rule_version"],
        rule_version=rules.VERSION,
        code_sha=code_sha,
        input_hash=record["input_hash"],
        expires_at=record["expires_at"],
        summary={k: v for k, v in result.items() if k != "proposals"},
        external_calls=0,
        adopted=False,
    )
    path = directory(db) / (jid + "-replay-" + uuid4().hex + ".json")
    with path.open("x", encoding="utf8") as f:
        json.dump(output, f, ensure_ascii=False)
    return output


def cleanup(db: Any, *, all_records: bool = False) -> int:
    root = directory(db).resolve()
    removed = 0
    if not root.exists():
        return 0
    for path in root.glob("planning-*.json"):
        if path.resolve().parent != root or path.is_symlink():
            continue
        record = json.loads(path.read_text("utf8"))
        if all_records or datetime.fromisoformat(record["expires_at"]) <= db.clock():
            path.unlink()
            removed += 1
    return removed
