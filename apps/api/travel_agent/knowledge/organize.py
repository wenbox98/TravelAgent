"""Rule-based organization with original grounding checks before attestation."""

from copy import deepcopy
import json
import re
from typing import Any
from travel_agent.preview.projection import project, fingerprint, safe_text
from travel_agent.preview.service import PreviewService
from travel_agent.research.content_store import SourceContentStore
from travel_agent.planning.discovery import checked
from travel_agent.planning.flow import PlanningService
from .store import Library


def metadata(db: Any, scope: str, content: dict[str, Any]) -> dict[str, Any]:
    r = db.connection.execute(
        "SELECT title,published_at,fetched_at,travel_occurred_at FROM sources WHERE source_id=? AND account_scope=?",
        (content["source_id"], scope),
    ).fetchone()
    if not r:
        raise ValueError("KNOWLEDGE_SOURCE_UNAVAILABLE")
    sid = content["source_id"]
    return dict(
        source_id=sid,
        content_id=content["content_id"],
        content_hash=content["content_hash"],
        normalization_version=content["normalization_version"],
        policy_id=content["policy_id"],
        policy_version=content["policy_version"],
        title=safe_text(r[0] or "未提供标题"),
        published_at=r[1],
        retrieved_at=r[2],
        travel_time=r[3],
        url="https://www.xiaohongshu.com/explore/" + sid[4:]
        if re.fullmatch(r"xhs:[a-f0-9]{24}", sid)
        else None,
        completeness=content["content_completeness"],
    )


def base(
    db: Any, p: dict[str, Any], kind: str, title: str, sources: list[dict[str, Any]]
) -> dict[str, Any]:
    return dict(
        kind=kind,
        title=safe_text(title),
        entities=[],
        tags=[],
        text="",
        conditions=[],
        unknowns=["当前开放、交通、季节适用性及可行性未核实"],
        destination=p["destination"],
        destination_origin="REQUEST_FILTER_NOT_LOCATION_PROOF",
        spatial_status="UNKNOWN",
        test_input=bool(p.get("validation_trip") or p.get("demo")),
        sources=sources,
        attested_at=db.stamp(),
        review_method="UNKNOWN",
        review_scope="UNKNOWN",
        locators=[],
        evidence_links=[],
        freshness="HISTORICAL_REFERENCE",
        activities=[],
    )


def options(db: Any, scope: str) -> list[dict[str, Any]]:
    result = []
    for r in db.connection.execute(
        "SELECT session_id,state_json FROM preview_sessions WHERE account_scope=? ORDER BY rowid DESC",
        (scope,),
    ):
        p = json.loads(r[1]).get("planning", {})
        if (
            p
            and not p.get("demo")
            and (p.get("research_ids") or p.get("discovery") or p.get("adopted"))
        ):
            result.append(
                dict(
                    session_id=r[0],
                    destination=p["destination"],
                    validation_trip=p.get("validation_trip", False),
                    adopted=bool(p.get("adopted")),
                )
            )
    return result


def prepare(
    db: Any, scope: str, sid: str, pattern: bool = False, research_id: str | None = None
) -> dict[str, Any]:
    _, state = PlanningService(db, scope).load(sid)
    p = state["planning"]
    if research_id is not None:
        p = dict(p, research_ids=[research_id], knowledge_mode=False)
    if p.get("demo"):
        raise ValueError("KNOWLEDGE_SYNTHETIC_NOT_SOURCE")
    cards: list[dict[str, Any]] = []
    skipped = []
    service = PreviewService(db, scope, "CACHED_PRIVATE_PREVIEW")
    if not p.get("knowledge_mode"):
        for rid in p.get("research_ids", []):
            try:
                _, bundles = service._cache(rid)
                output = project(bundles, scope=scope, research_id=rid, now=db.clock())
                refs = {e["claim_id"]: e for opt in output["options"] for e in opt["evidence"]}
                refs.update({e["claim_id"]: e for e in output["other_clues"]})
                for e in refs.values():
                    contents = SourceContentStore(db).load(e["source_id"], scope, purge=False)
                    matches = [
                        c
                        for c in contents
                        if all(
                            any(loc == b["locator"] for b in c["body_blocks"])
                            for loc in e["block_locators"]
                        )
                    ]
                    if len(matches) != 1:
                        skipped.append("AMBIGUOUS_CONTENT_BINDING")
                        continue
                    c = base(
                        db, p, "SOURCE_REFERENCE", e["text"], [metadata(db, scope, matches[0])]
                    )
                    c.update(
                        text=e["text"],
                        conditions=e["conditions"],
                        tags=[e["topic"], e["reference_kind"]],
                        review_method=e["review_status"],
                        review_scope=e["reference_kind"],
                        locators=[e["locator"], *e["block_locators"], *e["span_ids"]],
                        evidence_links=[e["claim_id"]],
                    )
                    from travel_agent.planning.materials import activities

                    inferred = activities([e], p["destination"])
                    c["entities"] = [a.name for a in inferred]
                    c["activities"] = [dict(name=a.name, conditions=a.conditions) for a in inferred]
                    c["key"] = "evidence:" + e["claim_id"]
                    cards.append(c)
            except ValueError:
                skipped.append("ORIGINAL_GROUNDING_UNAVAILABLE")
    try:
        leads = checked(db, scope, sid, p) if p.get("discovery") else {}
    except ValueError:
        leads = {}
        skipped.append("MENTION_LOCATOR_UNAVAILABLE")
    adopted = (p.get("adopted") or {}).get("activities", [])
    selected = {i for a in adopted for i in a.get("discovery_ids", [])}
    for lead in leads.values():
        if lead["quarantined"] or (selected and lead["lead_id"] not in selected):
            continue
        try:
            raw = next(
                c
                for c in SourceContentStore(db).load(lead["source_id"], scope, purge=False)
                if c["content_id"] == lead["content_id"]
            )
        except StopIteration:
            skipped.append("MENTION_LOCATOR_UNAVAILABLE")
            continue
        c = base(db, p, "PLACE_LEAD", lead["public_name"], [metadata(db, scope, raw)])
        c.update(
            key="mention:"
            + fingerprint([lead["content_id"], lead["start"], lead["end"], lead["public_name"]]),
            entities=[lead["public_name"]],
            text=lead["public_name"],
            tags=["公共名称提及"],
            conditions=["仅名称提及，不证明作者亲历、推荐、市区归属或当前开放。"],
            review_method="MENTION_LOCATED_ONLY",
            review_scope="NAME_ONLY",
            locators=[lead["locator"]],
            spatial_status=lead["spatial_status"],
            historical_identity="PREVIOUSLY_CHECKED_NOT_CURRENT"
            if lead["identity_status"] == "CHECKED"
            else "UNKNOWN",
        )
        cards.append(c)
    if pattern:
        if not adopted:
            raise ValueError("KNOWLEDGE_ADOPT_FIRST")
        # Only adopted activities whose original mention or card chain is still valid.
        used = []
        dependencies = []
        sources = {}
        locators = []
        for a in adopted:
            if a.get("knowledge_refs"):
                supports = [Library(db, scope).get(r) for r in a["knowledge_refs"]]
                dependencies.extend(a["knowledge_refs"])
            else:
                supports = [c for c in cards if a["name"] in c["entities"]]
            if not supports:
                raise ValueError("KNOWLEDGE_PATTERN_LINEAGE_UNAVAILABLE")
            for c in supports:
                for s in c["sources"]:
                    sources[s["content_id"]] = s
                locators.extend(c["locators"])
            used.append(
                {
                    k: deepcopy(a.get(k))
                    for k in (
                        "name",
                        "day",
                        "stay_min",
                        "stay_max",
                        "rest_minutes",
                        "locked_start",
                        "timing_origin",
                        "conditions",
                        "provenance",
                        "spatial_status",
                    )
                }
            )
        c = base(
            db, p, "PLAN_PATTERN", " → ".join(a["name"] for a in adopted), list(sources.values())
        )
        c.update(
            key="pattern:" + sid + ":" + str(p.get("adopted_version", 0)),
            entities=[a["name"] for a in adopted],
            text="曾采用的安排，未证明实际经历或长期偏好",
            tags=["已采用节奏"],
            conditions=list(dict.fromkeys(v for a in adopted for v in a["conditions"])),
            review_method="USER_ADOPTED_NOT_TRAVELED",
            review_scope="ARRANGEMENT_ONLY",
            activities=used,
            locators=locators,
            adoption_version=p.get("adopted_version", 0),
            dependencies=dependencies,
        )
        cards = [c]
    # No condition is shortened. Oversized entries need organization, not truncation.
    good = []
    for c in cards:
        if len(json.dumps(c, ensure_ascii=False)) > 10000 or len(c["conditions"]) > 30:
            skipped.append("NEEDS_ORGANIZE")
            continue
        for v in [c["text"], *c["conditions"], *c["entities"]]:
            safe_text(v, 1500)
        good.append(c)
    stable = [{k: v for k, v in c.items() if k != "attested_at"} for c in good]
    return dict(cards=good, skipped=skipped, preview_hash=fingerprint(stable))


def commit(db: Any, scope: str, sid: str, expected: str, pattern: bool = False) -> dict[str, Any]:
    with db.transaction():
        view = prepare(db, scope, sid, pattern)
        if view["preview_hash"] != expected:
            raise ValueError("KNOWLEDGE_PREVIEW_CHANGED")
        library = Library(db, scope)
        saved = []
        for raw in view["cards"]:
            c = dict(raw)
            key = c.pop("key")
            saved.append(library.save(key, c))
        return dict(cards=saved, skipped=view["skipped"])


def after_research(db: Any, scope: str, sid: str, research_id: str) -> int:
    """Local post-processing of successfully reviewed research; never updates a trip."""
    with db.transaction():
        view = prepare(db, scope, sid, research_id=research_id)
        library = Library(db, scope)
        for raw in view["cards"]:
            card = dict(raw)
            key = card.pop("key")
            library.save(key, card)
        return len(view["cards"])
