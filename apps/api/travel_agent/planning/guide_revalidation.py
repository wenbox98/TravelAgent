"""Explicit local v4 revalidation; immutable original jobs and normal preview/adopt."""

from copy import deepcopy
from typing import Any
from uuid import uuid4
from travel_agent.preview.projection import fingerprint
from .flow_models import PlanDraft
from . import advisory
from .revision_diagnostics import load


def inputs(
    db: Any, scope: str, sid: str, p: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from .suggestions import payload_for

    record, request = load(db, scope, p["job_id"])
    if request["payload"].get("protocol_version") != 4:
        raise ValueError("GUIDE_MODE_REQUIRED")
    current = payload_for(p, db, scope, sid)
    original = request["payload"]
    # Only the new deterministic lodging context is added. All source, intent and other input stays equal.
    comparable = {k: v for k, v in current.items() if k in original}
    if (
        not (set(current) - set(original)) <= {"lodging_context"}
        or comparable != original
        or PlanDraft.model_validate(request["draft"]) != PlanDraft.model_validate(p["draft"])
    ):
        raise ValueError("STALE_PROPOSAL")
    return record, request, current


def create(db: Any, scope: str, sid: str, p: dict[str, Any]) -> None:
    record, request, current = inputs(db, scope, sid, p)
    # Validate original input and raw reply; new scope is a deterministic interpretation of it.
    original_result = advisory.validate(record["proposals"], request["payload"])
    result = advisory.validate(record["proposals"], current)
    if original_result["accepted_count"] != result["accepted_count"]:
        raise ValueError("STALE_PROPOSAL")
    derived = dict(
        revalidation_id="guide-review-" + uuid4().hex,
        kind="LOCAL_REVALIDATION",
        source_job=p["job_id"],
        source_record_hash=fingerprint(record),
        original_rule=record["rule_version"],
        rule_version=advisory.VERSION,
        original_input_hash=record["input_hash"],
        input_hash=fingerprint(current),
        created_at=db.stamp(),
        expires_at=record["expires_at"],
        summary=result,
    )
    p.setdefault("guide_revalidations", []).append(derived)
    p["guide_revalidation_id"] = derived["revalidation_id"]


def current_record(p: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            r
            for r in p.get("guide_revalidations", [])
            if r["revalidation_id"] == p.get("guide_revalidation_id")
        ),
        None,
    )


def checked(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    chosen = current_record(p)
    if (
        not chosen
        or chosen["source_job"] != p["job_id"]
        or chosen["rule_version"] != advisory.VERSION
    ):
        raise ValueError("STALE_PROPOSAL")
    record, request, data = inputs(db, scope, sid, p)
    if chosen["source_record_hash"] != fingerprint(record) or chosen["input_hash"] != fingerprint(
        data
    ):
        raise ValueError("STALE_PROPOSAL")
    result = advisory.validate(record["proposals"], data)
    if result != chosen["summary"]:
        raise ValueError("STALE_PROPOSAL")
    return chosen


def view(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any] | None:
    value = current_record(p)
    if not value:
        return None
    result = deepcopy(value)
    try:
        checked(db, scope, sid, p)
        result["can_preview"] = bool(result["summary"]["accepted_count"])
    except ValueError:
        result["can_preview"] = False
    return result


def preview(db: Any, scope: str, sid: str, p: dict[str, Any], revision: int, index: int) -> None:
    chosen = checked(db, scope, sid, p)
    if index >= len(chosen["summary"]["proposals"]):
        raise ValueError("OPTION_UNAVAILABLE")
    before = deepcopy(p["draft"])
    p["draft"] = advisory.apply(p, chosen["summary"]["proposals"][index])
    p["local_guide_preview"] = dict(
        draft=before,
        record_id=chosen["revalidation_id"],
        index=index,
        preview_revision=revision + 1,
        draft_hash=fingerprint(p["draft"]),
    )


def check_adoption(db: Any, scope: str, sid: str, p: dict[str, Any], revision: int) -> None:
    marker = p.get("local_guide_preview")
    if not marker:
        return
    if marker["preview_revision"] != revision or marker["draft_hash"] != fingerprint(p["draft"]):
        raise ValueError("STALE_PROPOSAL")
    base = deepcopy(p)
    base["draft"] = marker["draft"]
    chosen = checked(db, scope, sid, base)
    if chosen["revalidation_id"] != marker["record_id"]:
        raise ValueError("STALE_PROPOSAL")
    p["last_guide_revalidation_adoption"] = dict(
        kind="LOCAL_REVALIDATION", record_id=marker["record_id"], index=marker["index"]
    )
    p.pop("local_guide_preview", None)
