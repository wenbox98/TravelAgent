"""Read-only material purpose and day coverage, independent of destination and IDs."""

import re
from typing import Any

from travel_agent.preview.projection import safe_text
from .flow_models import PlanDraft
from .guide_models import GuideDayChoice

VERSION = "advisory-assessment-1.1"
DAY_LABELS = {
    "ACTIVITIES": "已有项目建议",
    "REST": "建议留作休息",
    "SELF_ARRANGED": "建议自行安排",
    "GAP": "资料或安排待补",
}
LEVEL_LABELS = {
    "NAME_ONLY": "只有名称线索，具体玩法不足",
    "ROUTE_CONTEXT": "有来源组合参考，具体玩法仍待补",
    "CONTENT_REFERENCE": "有已审核的活动内容参考，当前可行性未核实",
    "UNVERIFIED": "来源内容支持未确认",
    "SYNTHETIC": "自编测试资料，不代表真实内容充分",
}


def references(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    """Local read only; knowledge uses metadata only, mentions recheck cached lineage."""
    if not p["draft"]["activities"] or p.get("demo"):
        return []
    if p.get("knowledge_mode"):
        from travel_agent.knowledge.planning import verify
        from travel_agent.knowledge.store import no_raw

        try:
            with no_raw(db):
                cards = verify(db, scope, p)
            from travel_agent.knowledge.planning import card_references

            return card_references(cards)
        except ValueError:
            return []  # Unavailable bindings never gain content support from a snapshot.
    from .materials import references as evidence_references

    result = evidence_references(db, scope, sid)
    mentions = [
        a
        for a in PlanDraft.model_validate(p["draft"]).activities
        if a.provenance == "SOURCE_MENTION"
    ]
    if mentions:
        from .discovery import checked, verify_activity

        try:
            leads = checked(db, scope, sid, p)
            for a in mentions:
                lead = verify_activity(a, leads)
                result.append(
                    dict(
                        claim_id=lead["lead_id"],
                        source_id=lead["source_id"],
                        source_version=lead["locator"].split(":chars:")[0],
                        locator=lead["locator"],
                        text=a.name,
                        conditions=a.conditions,
                        topic="PUBLIC_NAME",
                        reference_kind="PLACE_MENTION_ONLY",
                    )
                )
        except ValueError:
            pass  # Unavailable mention bindings cannot establish a context target.
    return result


def materials(activities: list[dict[str, Any]], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {r["claim_id"]: r for r in refs}
    result = []
    for a in activities:
        ids = list(
            dict.fromkeys(
                [
                    *a.get("evidence_ids", []),
                    *a.get("discovery_ids", []),
                    *a.get("knowledge_citation_ids", []),
                    *[r["card_id"] for r in a.get("knowledge_refs", [])],
                ]
            )
        )
        bound = [by_id[i] for i in ids if i in by_id]
        level = "UNVERIFIED"
        if a.get("provenance") == "SYNTHETIC_TEST":
            level = "SYNTHETIC"
        elif a.get("provenance") == "SOURCE_MENTION" or any(
            r.get("knowledge_kind") in {"PLACE_LEAD", "PLAN_PATTERN"} for r in bound
        ):
            level = "NAME_ONLY"
        elif a.get("provenance") == "SOURCE_REFERENCE" and bound:
            level = (
                "ROUTE_CONTEXT"
                if any(r.get("topic") in {"ROUTE", "EXPERIENCE"} for r in bound)
                else "UNVERIFIED"
            )
            names = sorted({v["name"] for v in activities}, key=len, reverse=True)

            def has_content(row: dict[str, Any]) -> bool:
                remainder = row["text"]
                for name in names:
                    remainder = remainder.replace(name, "")
                remainder = re.sub(r"[\W\d_]+", "", remainder)
                return (
                    row.get("topic") == "EXPERIENCE"
                    and a["name"] in row["text"]
                    and len(remainder) >= 8
                    and not re.search(r"→|➜|➡|->", row["text"])
                )

            if any(has_content(r) for r in bound):
                level = "CONTENT_REFERENCE"
        excerpts = []
        if level in {"ROUTE_CONTEXT", "CONTENT_REFERENCE"}:
            for r in bound:
                if a["name"] not in r["text"]:
                    continue
                try:
                    text = safe_text(r["text"][:200], 200)
                except ValueError:
                    continue
                excerpts.append(
                    dict(
                        text=text,
                        truncated=len(r["text"]) > 200,
                        citation_id=r["claim_id"],
                        role=r.get("reference_kind", "UNKNOWN"),
                    )
                )
        result.append(
            dict(
                activity_id=a["activity_id"],
                level=level,
                label=LEVEL_LABELS[level],
                citation_ids=ids,
                roles=sorted({r.get("reference_kind", "UNKNOWN") for r in bound}),
                uses=["NAME_SELECTION", "TENTATIVE_PACING"]
                if level == "NAME_ONLY"
                else ["SOURCE_CONTEXT", "TENTATIVE_COMBINATION"]
                if bound
                else ["TENTATIVE_PACING"],
                excerpts=excerpts[:3],
            )
        )
    return result


def meaningful(choice: GuideDayChoice) -> bool:
    text = re.sub(r"[\s，。；：、,.!！?？:;\d]", "", choice.reason)
    remainder = re.sub(
        r"根据实际情况|根据情况|按实际情况|视情况|到时再定|灵活安排|灵活调整|按需调整|自由活动|自行安排|待定|待补|暂无|未知|留白|机动|休闲|休息|放松|第|天|日",
        "",
        text,
    )
    # A conservative placeholder check, not a claim to prove free-text semantics.
    return len(remainder) >= 4 and choice.kind != "GAP"


def day_coverage(
    activities: list[dict[str, Any]],
    days: int | None,
    first_day: int,
    choices: list[GuideDayChoice],
    pace: str = "UNKNOWN",
) -> dict[str, Any]:
    expected = list(range(first_day, days + 1)) if days is not None else []
    assigned = {a["day"] for a in activities}
    valid_choices = {c.day: c for c in choices}
    rows = []
    for day in expected or sorted(assigned | valid_choices.keys()):
        items = [a["activity_id"] for a in activities if a["day"] == day]
        choice = valid_choices.get(day)
        intentional = bool(choice and meaningful(choice) and not items)
        kind = "ACTIVITIES" if items else choice.kind if intentional and choice else "GAP"
        rows.append(
            dict(
                day=day,
                kind=kind,
                label=DAY_LABELS[kind],
                activity_ids=items,
                reason=choice.reason
                if choice and not items
                else ""
                if items
                else "尚无项目或有依据的休闲/自行安排取舍；不是已完成的一天。",
                origin="PROPOSED_CHOICE" if intentional else "PROGRAM_ASSESSMENT",
            )
        )
    missing = [r["day"] for r in rows if r["kind"] == "GAP"]
    outside = sorted(
        d for d in assigned | valid_choices.keys() if d < first_day or (days and d > days)
    )
    warnings = []
    if (
        pace == "RELAXED"
        and days
        and days > first_day
        and len(activities) > 1
        and len(assigned) == 1
        and missing
    ):
        warnings.append(
            "轻松多日需求的项目仍集中在一天，其他天未作有效取舍；建议重新分散或明确休闲安排。"
        )
    for day in assigned:
        minimum = sum(a.get("stay_min") or 0 for a in activities if a["day"] == day)
        if pace == "RELAXED" and minimum > 360:
            warnings.append(
                f"第 {day} 天仅已知项目的建议下限超过六小时；这是节奏提醒，不含未知移动，也不是硬性限时。"
            )
    status = (
        "UNKNOWN_DURATION"
        if days is None
        else "PARTIAL"
        if missing or outside or not rows
        else "COVERED"
    )
    return dict(
        status=status,
        requested_days=days,
        missing_days=missing,
        outside_days=outside,
        days=rows,
        warnings=warnings,
        meaning="逐日覆盖仅说明建议如何分配；休闲和自行安排均是可修改取舍，不推定用户同意。不表示每天排满或现实可行性已核实。",
    )


def assess(
    activities: list[dict[str, Any]],
    days: int | None,
    first_day: int,
    choices: list[GuideDayChoice],
    support: list[dict[str, Any]],
    pace: str = "UNKNOWN",
) -> dict[str, Any]:
    coverage = day_coverage(activities, days, first_day, choices, pace)
    ids = {a["activity_id"] for a in activities}
    used = [r for r in support if r["activity_id"] in ids]
    insufficient = (
        len(used) != len(ids) or not used or any(r["level"] != "CONTENT_REFERENCE" for r in used)
    )
    status = (
        "PARTIAL"
        if coverage["status"] != "COVERED"
        else "LIMITED_CONTENT"
        if insufficient
        else "ADVISORY_COVERED"
    )
    return dict(
        rule_version=VERSION,
        status=status,
        coverage=coverage,
        materials=used,
        content_limited=insufficient,
        label={
            "PARTIAL": "局部建议：天数覆盖尚不完整",
            "LIMITED_CONTENT": "天数已有安排，玩法内容仍有限",
            "ADVISORY_COVERED": "有内容参考的建议草案，实际可行性未核实",
        }[status],
    )


def for_draft(draft: PlanDraft, refs: list[dict[str, Any]]) -> dict[str, Any]:
    activities = [a.model_dump() for a in draft.activities]
    return assess(
        activities,
        draft.days,
        draft.first_day,
        draft.guide.day_choices,
        materials(activities, refs),
        draft.pace,
    )


def check_days(draft: PlanDraft) -> None:
    days = [c.day for c in draft.guide.day_choices]
    if (
        len(days) != len(set(days))
        or any(
            d < draft.first_day or (draft.days is not None and d > draft.days)
            for d in [*days, *[a.day for a in draft.activities]]
        )
        or (draft.days is not None and draft.first_day > draft.days)
    ):
        raise ValueError("GUIDE_INVALID_DAY")
    if set(days) & {a.day for a in draft.activities}:
        raise ValueError("GUIDE_DAY_CHOICE_CONFLICT")


def current_dining(draft: PlanDraft) -> list[Any]:
    days = {a.day for a in draft.activities} | {
        c.day for c in draft.guide.day_choices if meaningful(c)
    }
    return [
        m.model_copy(update={"strategy": "NEAR_SELECTED_AREA"})
        if m.strategy == "BETWEEN_ACTIVITIES" and sum(a.day == m.day for a in draft.activities) < 2
        else m
        for m in draft.guide.dining
        if m.day in days
    ]
