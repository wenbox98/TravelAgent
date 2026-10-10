"""Conservative presentation of reviewed subjects; never re-approve source records."""

import re
from typing import Any

from .scoped_context import REVIEWED, same_document

PLAY = r"散步|观赏|欣赏|参观|徒步|品尝|看展|漫步|拍照|体验|观鸟|看花|重点看|追随|感受|老建筑|吊脚楼|文化"


def reviewed_subject_names(row: dict[str, Any]) -> list[str]:
    """Exact nouns from audited preceding subject premises, never day headers."""
    if row.get("review_status") not in REVIEWED or not re.search(PLAY, row["text"]):
        return []
    from .materials import place_name, activity_subject
    names = []
    for clause in row.get("clause_context", []):
        if re.search(r"不|没|未|如果|假设|→|➡|->|Day\s*\d|D\s*\d|第.{1,3}天", clause, re.I):
            continue
        match = re.search(r"(?:前往|打卡|到|去|在|沿)(?:免费的)?([\u4e00-\u9fffA-Za-z·]{2,24})[，。；\s]*$", clause)
        name = place_name(match[1]) if match else None
        if name and activity_subject(name) and re.search(r"公园|街区|景区|风景区|古镇|小镇|湿地|步道|广场|博物馆|纪念馆|大坝|画廊|洞|湖|寺|山|谷", name):
            names.append(name)
    return list(dict.fromkeys(names))


def explicit_subject(name: str, text: str) -> bool:
    if re.search(r"→|➜|➡|➝|➠|->", text):
        return False
    short_action = bool(re.search(r"(?:在|沿|到|去)" + re.escape(name) + r"(?:散步|看花|观鸟|参观|游览|欣赏|观赏|拍照|体验|看展|徒步)", text))
    if not short_action and len(re.sub(r"[\W\d_]", "", text.replace(name, ""))) < 8:
        return False
    from .materials import natural_names

    named = set(natural_names(text))
    if named - {name}:
        return False
    return bool(
        named == {name} or short_action
        or re.match(
            r"^(?:在|我(?:们)?(?:计划|想)?在)"
            + re.escape(name)
            + r"(?:观察|散步|看花|观鸟|参观|游览|欣赏|观赏|拍照|体验|看展|游玩|停留)",
            text,
        )
        or re.match(
            r"^[\s📍]*" + re.escape(name) + r"(?:[：:]|适合|可以|不适合|不推荐|需要|的体验)", text
        )
    )


def reviewed_clause_subject(name: str, row: dict[str, Any]) -> bool:
    """A reviewed same-parent subject premise can qualify a separate play clause.

    No day/header or same-document inference: clause_context is projected only
    from exact v2 selected premises after snapshot audit and independent review.
    """
    if explicit_subject(name, row["text"]):
        return True
    if not row.get("clause_context") or not re.search(
        PLAY, row["text"]
    ) or re.search(r"→|➜|➡|->", row["text"]):
        return False
    subject = re.compile(r"(?:前往|打卡|到|去|在|沿)(?:免费的)?" + re.escape(name)
        + r"(?:风景区|景区)?[，。；\s]*$")
    return any(subject.search(c) and not re.search(r"不|没|未|如果|假设|→|➡|->", c)
               for c in row["clause_context"])


def content_references(
    activity: dict[str, Any], refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    from .scoped_context import ids
    from .materials import activities

    if activity.get("provenance") != "SOURCE_REFERENCE":
        return []
    by_id = {r["claim_id"]: r for r in refs}
    bound = [by_id[i] for i in ids(activity) if i in by_id]
    other_subjects = {a.name for a in activities(refs, "", limit=None)} - {activity["name"]}
    return [
        r
        for r in refs
        if r.get("topic") == "EXPERIENCE"
        and r.get("review_status") in REVIEWED
        and reviewed_clause_subject(activity["name"], r)
        and not any(name in "\n".join([r["text"], *r.get("clause_context", [])]) for name in other_subjects)
        and any(same_document(b, r) for b in bound)
    ]


def travel_conditions(activity: dict[str, Any], activities: list[dict[str, Any]]) -> list[str]:
    """Display only narrow source restrictions here; complete premises remain in references.

    This is not semantic approval and never changes conditions used by validators.
    Ambiguous/mixed paragraphs stay in the source-context expansion intact.
    """
    others = [a["name"] for a in activities if a["name"] != activity["name"]]
    cues = r"未亲历|未出发|还未|计划|打算|自驾|公共交通|包车|班车|雨天|晴天|春季|夏季|秋季|冬季|不推荐|不适合|仅限|如果|假设|\d+月"
    standalone = r"(?:作者未亲历|作者未出发|未亲历|未出发|春季|夏季|秋季|冬季|雨天|晴天|\d{1,2}月|仅限自驾|自驾|公共交通|包车|班车)[。；]?"
    return [
        text
        for text in activity.get("conditions", [])
        if len(text) <= 200
        and re.search(cues, text)
        and (explicit_subject(activity["name"], text) or re.fullmatch(standalone, text))
        and not any(name in text for name in others)
        and not re.search(r"→|➜|➡|➝|➠|->", text)
    ]


def presentation(activity: dict[str, Any], refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(
            citation_id=r["claim_id"],
            text=r["text"],
            conditions=r["conditions"],
            role=r.get("reference_kind", "UNKNOWN"),
            review_status=r["review_status"],
        )
        for r in content_references(activity, refs)
    ]


def source_contexts(
    activities: list[dict[str, Any]], refs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Deduplicate complete premises, never silently discard mixed-object conditions."""
    from .scoped_context import ids

    needed = {cid for a in activities for cid in ids(a)}
    needed.update(r["claim_id"] for a in activities for r in content_references(a, refs))
    return [
        dict(
            citation_id=r["claim_id"],
            text=r["text"],
            conditions=r.get("conditions", []),
            role=r.get("reference_kind", "UNKNOWN"),
        )
        for r in refs
        if r["claim_id"] in needed
    ]
