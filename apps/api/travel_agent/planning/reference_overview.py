"""Cited macro references are useful without manufacturing concrete activities."""

from copy import deepcopy
from typing import Any
from typing import Literal
from pydantic import Field
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import fingerprint
from travel_agent.research.advisory_coverage import REVIEWED
from travel_agent.research.quality import reference_conflicts
from .local_materials import reference_binding

VERSION = "local-route-overview-3"


class ReferenceOverviewExport(StrictModel):
    filename: str
    markdown: str
    revision: int = Field(ge=0)
    kind: Literal["LOCAL_REFERENCE_OVERVIEW"]
    version: int = Field(ge=1)


ROLES = {
    "GUIDE_SUGGESTION": "作者攻略建议",
    "AUTHOR_PROPOSED_PLAN": "作者计划，未证实成行",
    "AUTHOR_RECORDED_TRIP": "作者历史经历，非当前保证",
}


def references(db: Any, scope: str, sid: str, p: dict[str, Any]) -> list[dict[str, Any]]:
    from .materials import references as evidence
    from .guide_assessment import references as selected

    # Attached research is allowed even when the current activity pool is empty.
    # No global destination search, raw candidate or rejected-claim fallback.
    rows = {r["claim_id"]: r for r in evidence(db, scope, sid)}
    rows.update({r["claim_id"]: r for r in selected(db, scope, sid, p)})
    return sorted(
        (
            r
            for r in rows.values()
            if r.get("review_status") in REVIEWED
            and r.get("reference_kind") in ROLES
            and r.get("locator")
            and r.get("knowledge_kind") in {None, "SOURCE_REFERENCE"}
        ),
        key=lambda r: (r["source_id"], r["claim_id"]),
    )


def object_key(row: dict[str, Any]) -> tuple[str, str, str, str, str] | None:
    relation = row.get("route_association")
    if not relation or not relation.get("object_quote"):
        return None
    return (
        row["source_id"],
        relation["scope"],
        relation["object_quote"],
        row["reference_kind"],
        relation.get("object_locator", ""),
    )


def project(rows: list[dict[str, Any]], p: dict[str, Any]) -> dict[str, Any]:
    conflicts = reference_conflicts([(r["source_id"], r) for r in rows])
    disputed = {cid for conflict in conflicts for cid in conflict.claim_ids}
    accepted = [
        r
        for r in rows
        if (
            r["claim_id"] not in disputed
            and r.get("topic") in {"ROUTE", "DURATION", "TRADEOFF"}
            and r.get("review_status") in REVIEWED
            and r.get("reference_kind") in ROLES
        )
    ]
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = {}
    for r in accepted:
        if r["topic"] == "ROUTE":
            # An accepted standalone route is its own object. It does not prove
            # a relationship for another claim with no explicit association.
            key = object_key(r) or (
                r["source_id"],
                "STANDALONE",
                r["text"],
                r["reference_kind"],
                r.get("locator", ""),
            )
            grouped.setdefault(key, []).append(r)
    for r in accepted:
        association_key = object_key(r)
        if r["topic"] != "ROUTE" and association_key in grouped:
            grouped[association_key].append(r)
    cards: list[dict[str, Any]] = []
    for key, entries in sorted(grouped.items()):
        bindings = {
            r["claim_id"]: fingerprint([reference_binding(r), r.get("duration_scope", "UNKNOWN")])
            for r in entries
        }
        conditions = list(
            dict.fromkeys(
                c for r in entries for c in r.get("conditions", []) if c.strip() != key[2].strip()
            )
        )
        cards.append(
            dict(
                option_id="reference-" + fingerprint(key)[:32],
                title=key[2],
                object_scope=key[1],
                role_label=ROLES[key[3]],
                source_count=1,
                condition_excerpts=[
                    dict(text=c[:80], truncated=len(c) > 80) for c in conditions[:2]
                ],
                summary="有来源路线参考；具体活动与当前交通需分别核实。",
                entries=[
                    dict(
                        citation_id=r["claim_id"],
                        topic=r["topic"],
                        text=r["text"],
                        conditions=r.get("conditions", []),
                        role=r["reference_kind"],
                        role_label=ROLES[r["reference_kind"]],
                        review=r["review_status"],
                        source_title=r.get("source_title"),
                        duration_scope=r.get("duration_scope", "UNKNOWN"),
                        # Kept as a relationship, never inferred from sharing a source.
                        route_association=r.get("route_association"),
                    )
                    for r in entries
                ],
                bindings=bindings,
            )
        )
    gaps = [g["label"] for g in p.get("automatic_coverage", {}).get("gaps", [])]
    if not gaps:
        gaps = ["具体玩法、交通、季节和当前可行性仍须分别核实。"]
    source_count = len({key[0] for key in grouped})
    if source_count < 2:
        gaps.append("这些备选只有一份或没有合格来源，不构成独立来源对照。")
    return dict(
        rule_version=VERSION,
        kind="LOCAL_REFERENCE_OVERVIEW",
        cards=cards,
        source_count=source_count,
        direction_count=len(cards),
        confirmed_independent_authors=None,
        unassigned_reference_count=len(accepted) - sum(len(c["entries"]) for c in cards),
        gaps=list(dict.fromkeys(gaps)),
        activity_count=len(p["draft"]["activities"]),
        meaning="按原引用整理的路线参考，不是新模型攻略、具体活动或现实可行性结论。",
    )


def choices(rows: list[dict[str, Any]], p: dict[str, Any]) -> dict[str, Any]:
    """Bindings survive condition edits, but never source/rule changes."""
    cards = {c["option_id"]: c for c in project(rows, p)["cards"]}

    def checked(saved: dict[str, Any] | None) -> dict[str, Any] | None:
        card = cards.get((saved or {}).get("option_id"))
        if (
            not saved
            or not card
            or saved.get("rule_version") != VERSION
            or saved.get("bindings") != card["bindings"]
        ):
            return None
        return dict(
            option_id=card["option_id"],
            bindings=card["bindings"],
            citation_ids=list(card["bindings"]),
            object_scope=card["object_scope"],
        )

    excluded = [v for saved in p.get("excluded_reference_overviews", []) if (v := checked(saved))]
    selected = checked(p.get("selected_reference_overview"))
    if selected and selected["option_id"] in {v["option_id"] for v in excluded}:
        selected = None
    return dict(selected_reference=selected, excluded_references=excluded)


def focused(rows: list[dict[str, Any]], p: dict[str, Any]) -> list[dict[str, Any]]:
    context = choices(rows, p)
    excluded = {cid for c in context["excluded_references"] for cid in c["citation_ids"]}
    selected = context["selected_reference"]
    bound = {cid for c in project(rows, p)["cards"] for cid in c["bindings"]}
    return [
        r
        for r in rows
        if r["claim_id"] not in excluded
        and (
            not selected or r["claim_id"] in selected["citation_ids"] or r["claim_id"] not in bound
        )
    ]


def derive(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    data = project(references(db, scope, sid, p), p)
    if not data["cards"]:
        raise ValueError("REVIEWED_ROUTE_REFERENCE_REQUIRED")
    data["input_hash"] = fingerprint([p["destination"], p["draft"], data])
    history = p.setdefault("reference_overview_history", [])
    if history and history[-1]["input_hash"] == data["input_hash"]:
        return dict(history[-1])
    result = dict(
        data,
        version=len(history) + 1,
        created_at=db.stamp(),
        parent_task_id=p.get("automatic_task_id"),
    )
    history.append(deepcopy(result))
    return result


def view(db: Any, scope: str, sid: str, p: dict[str, Any]) -> dict[str, Any]:
    available = project(references(db, scope, sid, p), p)
    saved = p.get("reference_overview_history", [])
    current = saved[-1] if saved else None
    valid = bool(
        current
        and current["rule_version"] == VERSION
        and current["input_hash"] == fingerprint([p["destination"], p["draft"], available])
    )
    chosen = p.get("selected_reference_overview")
    checked = choices(references(db, scope, sid, p), p)
    return dict(
        available=bool(available["cards"]),
        current=current,
        valid=valid,
        selected=chosen,
        selected_current=bool(checked["selected_reference"]),
        excluded_current=[v["option_id"] for v in checked["excluded_references"]],
        history_count=len(saved),
    )


def export(db: Any, scope: str, sid: str) -> dict[str, Any]:
    from .flow import PlanningService
    from .guide_view import escaped

    row, state = PlanningService(db, scope).load(sid)
    result = view(db, scope, sid, state["planning"])
    if not result["valid"]:
        raise ValueError("REFERENCE_OVERVIEW_STALE")
    current = result["current"]
    lines = [
        "# 本地路线参考",
        "",
        current["meaning"],
        "",
        f"本地整理版本：{current['version']}；不是已采用攻略。",
        "",
    ]
    for card in current["cards"]:
        lines += ["## " + card["title"], ""]
        for e in card["entries"]:
            lines += [
                "- " + escaped(e["text"]),
                "  - 角色：" + e["role_label"],
                "  - 审核性质：" + e["review"],
                "  - 条件：" + "；".join(escaped(c) for c in e["conditions"]),
                "  - 引用：" + escaped(e["citation_id"]),
            ]
            if e["topic"] == "DURATION":
                lines.append("  - 时长作用范围：" + e.get("duration_scope", "UNKNOWN"))
            association = e.get("route_association")
            lines.append(
                "  - 路线关系："
                + (
                    escaped(association["object_quote"]) + "（" + association["scope"] + "）"
                    if association
                    else "未证明与其他条目的具体关联，不能因同源自动套用。"
                )
            )
    lines += ["", "## 仍缺的资料", ""] + ["- " + escaped(g) for g in current["gaps"]]
    return dict(
        filename="route-reference.md",
        markdown="\n".join(lines) + "\n",
        revision=row["revision"],
        kind=current["kind"],
        version=current["version"],
    )
