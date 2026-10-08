"""Trip-scoped reviewed references and conservative public activity projection."""

import re
from typing import Any

from travel_agent.preview.projection import fingerprint
from travel_agent.preview.service import PreviewService
from .flow_models import Activity

_SEQUENCE = re.compile(r"\s*(?:→|->|➡|➜|—>|👉)\s*")
_DAY = re.compile(
    r"^\s*(?:Day\s*\d+|D\s*\d+|第[一二三四五六七八九十\d]+天|路线|行程)\s*[：:]?\s*", re.I
)
_BAD_NAME = re.compile(
    r"[。！？?！：:；;\n]|\d+(?:点|小时|分钟)|路线|行程|攻略|建议|可以|不去|不要|不推荐|上午|下午|晚上|车程|入住"
)


def scope_gaps(city_area_requested: bool, rows: list[dict[str, Any]]) -> list[str]:
    if city_area_requested and any(
        re.search(r"从.{0,16}市区出发", text)
        for e in rows
        for text in [e["text"], *e["conditions"]]
    ):
        return [
            "资料包含从市区出发的外围行程线索；这些活动是否符合本次市区范围尚未核实，不能当作中心城区安排。"
        ]
    return []


def place_name(text: str) -> str | None:
    text = text.strip().removesuffix("。").strip()
    text = re.sub(r"^[\s\d.、)（(\-•●]+", "", text).strip()
    text = re.sub(r"[（(][^（）()]*[）)]", "", text).strip()
    return (
        text
        if 2 <= len(text) <= 30
        and not _BAD_NAME.search(text)
        and re.fullmatch(r"[\w\u4e00-\u9fff·\- ]+", text)
        else None
    )


def references(db: Any, scope: str, sid: str) -> list[dict[str, Any]]:
    from .flow import PlanningService

    row, state = PlanningService(db, scope).load(sid)
    p = state["planning"]
    if p["demo"] or row["mode"] != "CACHED_PRIVATE_PREVIEW":
        return []
    service = PreviewService(db, scope, row["mode"])
    result: dict[str, dict[str, Any]] = {}
    # Only explicitly attached compatible researches. No global source fallback.
    ids = sorted(
        set(p.get("research_ids", []) + ([row["research_id"]] if row["research_id"] else []))
    )
    from travel_agent.preview.projection import project

    for rid in ids:
        q, evidence = service._cache(rid)
        import json

        if json.loads(q["request_json"]).get("destination") != p["destination"]:
            continue
        data = project(evidence, scope=scope, research_id=rid, now=db.clock())
        for e in [e for option in data["options"] for e in option["evidence"]] + data[
            "other_clues"
        ]:
            if db.connection.execute(
                "SELECT 1 FROM knowledge_withdrawals WHERE account_scope=? AND source_id=?",
                (scope, e["source_id"]),
            ).fetchone():
                continue
            if (
                "reused_claim_ids" in p
                and rid not in p.get("own_research_ids", [])
                and e["claim_id"] not in [*p["reused_claim_ids"], *p.get("reused_context_ids", [])]
            ):
                continue
            if e["topic"] in {"ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT", "RISK", "SEASON", "TRADEOFF"}:
                from .local_materials import reference_binding

                bound = p.get("reused_reference_bindings", {}).get(e["claim_id"])
                if bound and bound != reference_binding(e):
                    continue
                result[e["claim_id"]] = e
    return sorted(result.values(), key=lambda e: (e["source_id"], e["claim_id"]))


def candidate_from_name(
    name: str, rows: list[dict[str, Any]], region: str, intent: str = "UNDECIDED"
) -> Activity:
    if place_name(name) != name or not rows or any(name not in e["text"] for e in rows):
        raise ValueError("ACTIVITY_SUPPORT_REQUIRED")
    if any(re.search(r"不去|不要去|不推荐|禁止|不能去", e["text"]) for e in rows):
        raise ValueError("ACTIVITY_CONTEXT_NEGATIVE")
    ids = sorted({e["claim_id"] for e in rows})
    from .spatial import classify

    status, basis = classify(name, rows, intent)
    return Activity(
        activity_id="activity-" + fingerprint([name, ids])[:24],
        name=name,
        region=region,
        region_origin="REQUEST_FILTER",
        spatial_status=status,
        spatial_basis=basis,
        source_locations=[b["text"] for b in basis if b["kind"] == "SOURCE_CONTEXT"],
        description="来源中的地点/体验线索；当前运营待核实",
        evidence_ids=ids,
        conditions=list(dict.fromkeys(c for e in rows for c in e["conditions"])),
        reference_kinds=sorted({e["reference_kind"] for e in rows}),
        provenance="SOURCE_REFERENCE",
    )


def activities(
    rows: list[dict[str, Any]], region: str, intent: str = "UNDECIDED"
) -> list[Activity]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for e in rows:
        if e["topic"] not in {"ROUTE", "EXPERIENCE"}:
            continue
        text = _DAY.sub("", e["text"])
        text = re.sub(
            r"^(?:[^：:]{0,16})?(?:市区|市内|主城区|中心城区)(?:一日游|游览|游玩|路线|行程)*[：:]",
            "",
            text,
        )
        parts = _SEQUENCE.split(text)
        if len(parts) == 1:
            marked = re.findall(r"(?:📍|地点[：:]|【)([^\n，。】]{2,30})", text)
            parts = marked or ([text] if e["topic"] == "ROUTE" else [])
        for part in parts:
            name = place_name(part)
            if name:
                grouped.setdefault(name, []).append(e)
    output = []
    for name, support in grouped.items():
        try:
            output.append(candidate_from_name(name, support, region, intent))
        except ValueError:
            continue
    return output[:12]
