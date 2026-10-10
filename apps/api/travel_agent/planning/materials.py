"""Trip-scoped reviewed references and conservative public activity projection."""

import re
from typing import Any

from travel_agent.preview.projection import fingerprint
from travel_agent.preview.service import PreviewService
from .flow_models import Activity

_SEQUENCE = re.compile(r"\s*(?:→|->|➡|➜|➝|➞|➔|➠|—>|👉)\s*")
_DAY = re.compile(
    r"^\s*[🔸🔹]?\s*(?:Day\s*\d+|D\s*\d+|第[一二三四五六七八九十\d]+天|路线|行程)\s*[：:|｜]?\s*", re.I
)
_BAD_NAME = re.compile(
    r"[。！？?！：:；;\n]|\d+(?:点|小时|分钟)|路线|环线|游线|行程|攻略|建议|可以|不去|不要|不推荐|上午|下午|晚上|车程|入住"
)


def activity_subject(name: str) -> bool:
    """Generic transfer/arrival steps remain route context, not sightseeing choices."""
    return name.strip() not in {"游客中心", "景交车", "索道上山", "索道下山", "抵达市区", "机场", "酒店", "民宿", "市区", "返程", "还车", "出发"}


def natural_names(text: str) -> list[str]:
    """Exact public noun phrases next to explicit actions; no outside entity lookup."""
    names = [name for raw in re.findall(r"📍([^\n，。；：:]{2,30})[：:]", text)
             if (name := place_name(raw))]
    for clause in re.split(r"[，。；！？\n]", text):
        if re.search(r"不推荐|不要|不能|禁止|不去|没去|未去", clause):
            continue
        for match in re.finditer(
            r"(?:我(?:们)?(?:想|计划)?在|我(?:们)?(?:想|计划)?去|推荐去|建议去|再去|然后去|前往|走进|参观|游览|到|在|去)([\u4e00-\u9fffA-Za-z·]{2,24}?)"
            r"(?:散步|看花|观鸟|参观|游览|欣赏|观赏|拍照|体验|看展|游玩|停留)",
            clause,
        ):
            name = place_name(match[1])
            if (
                name
                and name in text
                and re.search(
                    r"(?:公园|园|馆|湖|山|谷|寺|古镇|湿地|步道|街区|广场|森林|村|海滩|景区|小镇)$",
                    name,
                )
            ):
                names.append(name)
    return list(dict.fromkeys(names))


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
    owned_ids = {
        r[0]
        for r in db.connection.execute(
            "SELECT DISTINCT j.research_id FROM preview_jobs j JOIN research_questions q USING(research_id) "
            "WHERE j.session_id=? AND j.account_scope=? AND j.status IN ('COMPLETED','PARTIAL','NEEDS_REVIEW','FAILED')",
            (sid, scope),
        )
    }
    ids = sorted(set(ids) | owned_ids)
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
                and rid not in set(p.get("own_research_ids", [])) | owned_ids
                and e["claim_id"] not in [*p["reused_claim_ids"], *p.get("reused_context_ids", [])]
            ):
                continue
            if e["topic"] in {
                "ROUTE",
                "EXPERIENCE",
                "DURATION",
                "TRANSPORT",
                "SEASON",
                "TRADEOFF",
            }:
                from .local_materials import reference_binding

                bound = p.get("reused_reference_bindings", {}).get(e["claim_id"])
                if bound and bound != reference_binding(e):
                    continue
                result[e["claim_id"]] = e
    return sorted(result.values(), key=lambda e: (e["source_id"], e["claim_id"]))


def same_conditions(left: list[str], right: list[str]) -> bool:
    """Preserve every exact condition and its multiplicity, independent of row order."""
    return sorted(left) == sorted(right)


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
    rows: list[dict[str, Any]], region: str, intent: str = "UNDECIDED", *, limit: int | None = 12
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
            marked = re.findall(r"(?:📍|地点[：:]|【)([^\n，。】：:]{2,30})", text)
            parts = marked or ([text] if e["topic"] == "ROUTE" else natural_names(text))
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
    # A long route's names must not consume the whole catalog before a later
    # reviewed, explicitly named action can be considered. This is selection
    # priority only, never a new content/identity/evidence classification.
    action_names = {name for e in rows if e["topic"] == "EXPERIENCE"
                    for name in natural_names(e["text"])}
    output.sort(key=lambda a: a.name not in action_names)
    return output if limit is None else output[:limit]
