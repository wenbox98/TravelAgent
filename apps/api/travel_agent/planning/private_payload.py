"""Minimal, trip-scoped planning input. Never serializes map data or endpoints."""

import json
from typing import Any

from travel_agent.research.canonical import body_blocks
from travel_agent.research.model_input import outbound_blocks
from .flow_models import PlanDraft
from .materials import activities, candidate_from_name, references, scope_gaps
from .private_budget import PrivatePlanningBudget


def payload(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    if p.get("knowledge_mode"):
        from travel_agent.knowledge.planning import payload as knowledge_payload

        return knowledge_payload(db, scope, p)
    from .workbench import daily

    if not daily(p):
        PrivatePlanningBudget.for_trip(db, sid).check_trip(scope, sid)
    draft = PlanDraft.model_validate(p["draft"])
    discovery_mode = bool(draft.activities) and any(
        a.provenance == "SOURCE_MENTION" for a in draft.activities
    )
    refs = references(db, scope, sid)
    from .scoped_context import derive

    mentions = []
    if discovery_mode:
        from .discovery import model_references

        mention_draft = draft.model_copy(deep=True)
        mention_draft.activities = [a for a in draft.activities if a.provenance == "SOURCE_MENTION"]
        mentions = model_references(db, scope, sid, p, mention_draft)
    backgrounds = derive([a.model_dump() for a in draft.activities], [*refs, *mentions])[
        "backgrounds"
    ]
    if p.get("protocol_version") == 2 and draft.activities:
        needed = {identifier for a in draft.activities for identifier in a.evidence_ids}
        needed.update(c["citation_id"] for c in backgrounds)
        needed.update(b["citation_id"] for c in backgrounds for b in c["basis"])
        refs = [e for e in refs if e["claim_id"] in needed]
    selected: list[dict[str, Any]] = list(mentions)
    lengths: dict[str, int] = {}
    for e in mentions:
        lengths[e["source_id"]] = (
            lengths.get(e["source_id"], 0) + len(e["text"]) + sum(map(len, e["conditions"]))
        )
    for e in refs:
        policy = db.connection.execute(
            "SELECT p.policy_json FROM sources b JOIN source_policies p ON p.policy_id=b.policy_id "
            "WHERE b.source_id=? AND b.account_scope=? ORDER BY p.version DESC LIMIT 1",
            (e["source_id"], scope),
        ).fetchone()
        if not policy or not all(
            json.loads(policy[0]).get(k) for k in ("allow_inference", "allow_external_model")
        ):
            continue
        text = "\n".join(
            [
                e["text"],
                *e["conditions"],
                (e.get("route_association") or {}).get("object_quote", ""),
            ]
        )
        blocks = body_blocks(text)
        if len(outbound_blocks(blocks)) != len(blocks):
            continue
        source = e["source_id"]
        if source not in lengths and len(lengths) >= p.get("automatic_material_source_limit", 2):
            continue
        if lengths.get(source, 0) + len(text) > 6000:
            continue
        lengths[source] = lengths.get(source, 0) + len(text)
        selected.append(
            {
                k: e[k]
                for k in (
                    "claim_id",
                    "text",
                    "conditions",
                    "reference_kind",
                    "topic",
                    "source_id",
                    "source_version",
                    "locator",
                    "route_association",
                    "review_status",
                )
                if k in e
            }
        )
    allowed = {e["claim_id"]: e for e in selected}
    catalog = {a.activity_id: a for a in activities(refs, p["destination"])}
    for a in draft.activities:
        if a.provenance == "SOURCE_MENTION":
            continue
        if (
            a.provenance != "SOURCE_REFERENCE"
            or not a.evidence_ids
            or not set(a.evidence_ids) <= allowed.keys()
        ):
            raise ValueError("PLANNING_REFERENCE_UNAVAILABLE")
        supported = candidate_from_name(
            a.name, [allowed[i] for i in a.evidence_ids], p["destination"], draft.spatial.intent
        )
        if (
            supported.activity_id,
            supported.region,
            supported.conditions,
            supported.reference_kinds,
        ) != (a.activity_id, a.region, a.conditions, a.reference_kinds):
            raise ValueError("PLANNING_REFERENCE_UNAVAILABLE")
        if (
            p.get("protocol_version") == 2
            and draft.spatial.intent == "CITY_CORE"
            and supported.spatial_status
            not in ({"MATCH", "UNKNOWN"} if draft.planning_mode == "ADVISORY" else {"MATCH"})
        ):
            raise ValueError("PLANNING_SCOPE_UNVERIFIED")
        a.spatial_status, a.spatial_basis, a.source_locations = (
            supported.spatial_status,
            supported.spatial_basis,
            supported.source_locations,
        )
        catalog[a.activity_id] = a
    if not selected:
        raise ValueError("PLANNING_REFERENCE_UNAVAILABLE")
    if (
        p.get("protocol_version") == 2
        and draft.spatial.intent == "CITY_CORE"
        and not draft.activities
    ):
        raise ValueError("ACTIVITY_SELECTION_REQUIRED")
    data = assemble(p, draft, selected, discovery_mode, refs)
    from .scoped_context import attach_context

    attach_context(data, lengths, max_sources=p.get("automatic_material_source_limit", 2))
    return data


def assemble(
    p: dict[str, Any],
    draft: PlanDraft,
    selected: list[dict[str, Any]],
    discovery_mode: bool,
    refs: list[dict[str, Any]],
) -> dict[str, Any]:
    result = {
        "protocol_version": p.get("protocol_version", 1),
        "discovery_mode": discovery_mode,
        "spatial_intent": draft.spatial.intent,
        "purpose": "PRIVATE_PLANNING",
        "city_area_requested": p["travel_kind"] == "CITY" and "市区" in p["request"],
        "area_unknowns": scope_gaps(p["travel_kind"] == "CITY" and "市区" in p["request"], refs),
        "destination": p["destination"],
        "travel_kind": p["travel_kind"],
        "scope": draft.inputs.planning_scope,
        "days": draft.days,
        "transport": draft.transport,
        "walking_allowed": draft.walking_allowed,
        "driving": draft.driving,
        "charter": draft.inputs.charter,
        "first_start": draft.inputs.activity_start,
        "first_day": draft.first_day,
        "first_period": draft.first_period,
        "return_deadline": draft.return_deadline,
        "activity_end": draft.inputs.activity_end,
        "adjustment": draft.adjustment,
        "activities": [
            {
                k: a.model_dump()[k]
                for k in (
                    "activity_id",
                    "provenance",
                    "reference_kinds",
                    "name",
                    "region",
                    "day",
                    "locked_start",
                    "stay_min",
                    "stay_max",
                    "rest_minutes",
                    "evidence_ids",
                    "discovery_ids",
                    "conditions",
                    "spatial_status",
                )
            }
            for a in draft.activities
        ],
        "references": selected,
        "allowed_citation_ids": sorted(e["claim_id"] for e in selected),
        "known_map_values": [],
        "instructions": (
            "SOURCE_MENTION活动仅证明公共名称被原文提及，其引用ID是发现依据，不是获准的作者事实。独立已审核scoped_context可按标定范围用于取舍，不能升级提及的性质。只给顺序、建议停留/休息和节奏取舍；不得添加地点历史、展览、特色、开放或预约事实。范围UNKNOWN的选项仅为临时草案。"
            if discovery_mode
            else ""
        )
        + "仅安排已提供活动，保留锁定预约、首项时间、交通和硬截止。停留与休息为AI建议，交通耗时/开放/预约/票价未知，不得编造。遵循adjustment改选。若活动为空，可从ROUTE/EXPERIENCE引用逐字选择短公共地点名，以grounded_activities提供candidate-N及证据ID，再在proposals引用candidate-N。不得新增来源中不存在的地点。不要把作者计划当历史经历或当前保证。",
    }
    if p.get("conversation_model_context"):
        result["conversation"] = p["conversation_model_context"]
        excluded = set(result["conversation"].get("excluded_activity_ids", []))
        excluded_citations = {
            cid
            for c in result["conversation"].get("excluded_references", [])
            for cid in c["citation_ids"]
        }
        for a in draft.activities:
            citations = (
                set(a.evidence_ids) | {r.card_id for r in a.knowledge_refs} | set(a.discovery_ids)
            )
            if citations & excluded_citations:
                if a.locked or a.locked_start:
                    raise ValueError("PLANNING_LOCKED_CONSTRAINT")
                excluded.add(a.activity_id)
        result["references"] = [
            r for r in result["references"] if r["claim_id"] not in excluded_citations
        ]
        result["allowed_citation_ids"] = sorted(r["claim_id"] for r in result["references"])
        result["activities"] = [a for a in result["activities"] if a["activity_id"] not in excluded]
        if draft.activities and not result["activities"]:
            raise ValueError("CONVERSATION_ALL_ACTIVITIES_EXCLUDED")
        result["instructions"] += (
            " conversation是本次可修改的用户选择和最小对话摘要，不能作为来源事实。优先考虑selected方案及selected_reference路线对象；excluded/excluded_references是本轮排除方向，不照抄。路线对象只约束方向，不能变成每个地点特色；时长仅适用于原证明对象。只安排本次allowed activities，保护锁定项。无法落实时保留缺口，不假装修改成功。"
        )
    return result


def ground(
    raw: dict[str, Any], data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Names selected in the same call still require current contextual support."""
    from copy import deepcopy
    from .flow_models import PlanningResponse

    value = PlanningResponse.model_validate(raw).model_dump()
    data = deepcopy(data)
    refs = {e["claim_id"]: e for e in data.get("references", [])}
    names, ids, catalog = set(), set(), []
    if value["grounded_activities"] and data["activities"]:
        raise ValueError("PLANNING_UNKNOWN_REFERENCE")
    for selected in value.pop("grounded_activities"):
        if selected["candidate_key"] in ids or selected["place_name"] in names:
            raise ValueError("PLANNING_UNKNOWN_REFERENCE")
        support = [refs[i] for i in selected["evidence_ids"] if i in refs]
        if len(support) != len(selected["evidence_ids"]) or any(
            e["topic"] not in {"ROUTE", "EXPERIENCE"} for e in support
        ):
            raise ValueError("PLANNING_UNKNOWN_REFERENCE")
        a = candidate_from_name(selected["place_name"], support, data["destination"])
        names.add(a.name)
        ids.add(selected["candidate_key"])
        catalog.append(a.model_dump())
        data["activities"].append(a.model_dump())
        for proposal in value["proposals"]:
            for item in proposal["activities"]:
                if item["activity_id"] == selected["candidate_key"]:
                    item["activity_id"] = a.activity_id
    return value, data, catalog
