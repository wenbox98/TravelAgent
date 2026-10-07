"""Selected card bindings enter existing planning, with SQL raw reads denied."""

from copy import deepcopy
from typing import Any
from travel_agent.planning.flow_models import Activity, PlanDraft, KnowledgeBinding
from travel_agent.research.canonical import body_blocks
from travel_agent.research.model_input import outbound_blocks
from travel_agent.preview.projection import fingerprint
from .store import Library, binding, no_raw


def card_references(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {}
    for c in cards:
        related = c.get("scoped_references", []) if c["kind"] == "SOURCE_REFERENCE" else []
        own: dict[str, Any] = next((r for r in related if r["claim_id"] in c["evidence_links"]), {})
        main = dict(
            own,
            claim_id=c["card_id"],
            text=c["text"],
            conditions=c["conditions"],
            reference_kind=c["review_scope"],
            review_status=c["review_method"],
            topic="PUBLIC_NAME"
            if c["kind"] == "PLACE_LEAD"
            else "ARRANGEMENT"
            if c["kind"] == "PLAN_PATTERN"
            else c["tags"][0],
            knowledge_kind=c["kind"],
            knowledge_binding=binding(c),
        )
        rows[main["claim_id"]] = main
        for r in related:
            if r["claim_id"] not in c["evidence_links"]:
                rows[r["claim_id"]] = dict(r, knowledge_binding=binding(c))
    return list(rows.values())


def templates(c: dict[str, Any]) -> list[Activity]:
    entries = c.get("activities") or [dict(name=n) for n in c["entities"]]
    result = []
    for i, a in enumerate(entries):
        is_mention = c["kind"] != "SOURCE_REFERENCE"
        result.append(
            Activity(
                activity_id="knowledge-" + fingerprint([c["card_id"], i])[:24],
                name=a["name"],
                region=c["destination"],
                provenance="SOURCE_MENTION" if is_mention else "SOURCE_REFERENCE",
                spatial_status=c["spatial_status"],
                knowledge_refs=[KnowledgeBinding.model_validate(binding(c))],
                reference_kinds=[c["review_scope"]],
                conditions=list(dict.fromkeys(c["conditions"] + a.get("conditions", []))),
                description="知识卡引用；适用条件与历史角色保留，当前可行性未核实",
                day=a.get("day", 1),
                stay_min=a.get("stay_min"),
                stay_max=a.get("stay_max"),
                rest_minutes=a.get("rest_minutes"),
                timing_origin=a.get("timing_origin", "UNKNOWN"),
            )
        )
    return result


def verify(
    db: Any, scope: str, p: dict[str, Any], *, outbound: bool = False
) -> list[dict[str, Any]]:
    library = Library(db, scope)
    cards = {}
    for a in PlanDraft.model_validate(p["draft"]).activities:
        if not a.knowledge_refs:
            raise ValueError("KNOWLEDGE_MIXED_INPUT_UNSUPPORTED")
        refs = [r.model_dump() for r in a.knowledge_refs]
        for r in refs:
            c = library.get(r, outbound=outbound)
            if c["destination"] != p["destination"] or (
                c["test_input"] and not p.get("knowledge_include_test")
            ):
                raise ValueError("KNOWLEDGE_SCOPE_MISMATCH")
            expected = next((x for x in templates(c) if x.activity_id == a.activity_id), None)
            if not expected or any(
                getattr(a, k) != getattr(expected, k)
                for k in (
                    "name",
                    "region",
                    "conditions",
                    "provenance",
                    "knowledge_refs",
                    "spatial_status",
                    "reference_kinds",
                )
            ):
                raise ValueError("KNOWLEDGE_BINDING_CHANGED")
            cards[c["card_id"]] = c
    if not cards:
        raise ValueError("PLANNING_REFERENCE_UNAVAILABLE")
    return list(cards.values())


def attach(
    db: Any, scope: str, sid: str, refs: list[dict[str, Any]], revision: int, include_test: bool
) -> dict[str, Any]:
    from travel_agent.planning.flow import PlanningService
    import json

    service = PlanningService(db, scope)
    with db.transaction():
        row, state = service.load(sid)
        p = state["planning"]
        if row["revision"] != revision:
            raise ValueError("STALE_REVISION")
        if p.get("adopted") or p["draft"]["activities"]:
            raise ValueError("REUSE_REQUIRES_EMPTY_DRAFT")
        if p.get("runtime_mode") != "DAILY":
            raise ValueError("DAILY_TRIP_REQUIRED")
        cards = [Library(db, scope).get(r) for r in refs]
        if not cards or len(cards) > 12:
            raise ValueError("INVALID_INPUT")
        activities = {a.activity_id: a.model_dump() for c in cards for a in templates(c)}
        if not activities:
            raise ValueError("KNOWLEDGE_NO_PUBLIC_ACTIVITY")
        p["draft"]["activities"] = list(activities.values())
        PlanDraft.model_validate(p["draft"])
        p.update(knowledge_mode=True, knowledge_include_test=include_test, protocol_version=2)
        p["collapsed"]["activities"] = False
        verify(db, scope, p)
        db.connection.execute(
            "UPDATE preview_sessions SET state_json=?,revision=revision+1,updated_at=? WHERE session_id=?",
            (json.dumps(state, ensure_ascii=False), db.stamp(), sid),
        )
        return service.get(sid)


def payload(db: Any, scope: str, p: dict[str, Any]) -> dict[str, Any]:
    from travel_agent.planning.private_payload import assemble

    with no_raw(db):
        cards = verify(db, scope, p, outbound=True)
        draft = PlanDraft.model_validate(p["draft"])
        lengths: dict[str, int] = {}
        selected = card_references(cards)
        for entry in selected:
            c = next(c for c in cards if c["card_id"] == entry["knowledge_binding"]["card_id"])
            text = "\n".join(
                [
                    entry["text"],
                    *entry["conditions"],
                    (entry.get("route_association") or {}).get("object_quote", ""),
                ]
            )
            blocks = body_blocks(text)
            if len(outbound_blocks(blocks)) != len(blocks):
                raise ValueError("KNOWLEDGE_UNSAFE_INPUT")
            for s in c["sources"]:
                lengths[s["source_id"]] = lengths.get(s["source_id"], 0) + len(text)
            entry.update(
                review_method=c["review_method"],
                historical_only=True,
                completeness=sorted({s["completeness"] for s in c["sources"]}),
            )
        if len(lengths) > 2 or any(n > 6000 for n in lengths.values()):
            raise ValueError("KNOWLEDGE_INPUT_LIMIT")
        result = assemble(
            p, draft, selected, any(c["kind"] != "SOURCE_REFERENCE" for c in cards), []
        )
        result["knowledge_bindings"] = [binding(c) for c in cards]
        result["knowledge_mode"] = True
        for a, original in zip(result["activities"], draft.activities, strict=True):
            a["knowledge_citation_ids"] = [r.card_id for r in original.knowledge_refs]
        from travel_agent.planning.scoped_context import attach_context

        attach_context(result, lengths)
        result["instructions"] += (
            " 知识卡为历史有限条目；名称提及、来源参考和已采用节奏不是实测事实。仅使用本次列出的知识卡引用，不推测原文，不改写适用条件。"
        )
        return deepcopy(result)
