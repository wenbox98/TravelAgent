"""Conservative citation aliases; a shared title or quotation alone proves nothing."""

from typing import Any
import json


def normalized(text: str) -> str:
    return " ".join(text.split())


def meaning(row: dict[str, Any]) -> list[Any]:
    return [
        row.get("topic"),
        normalized(row["text"]),
        [normalized(c) for c in row.get("conditions", [])],
        row.get("reference_kind", row.get("role")),
        row.get("review_status", row.get("review")),
        row.get("duration_scope") or "UNKNOWN",
        row.get("route_association"),
    ]


def groups(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        locator = row.get("locator")
        version = row.get("source_version")
        if (
            not version
            and row.get("knowledge_kind") == "SOURCE_REFERENCE"
            and locator
            and ":chars:" in locator
        ):
            # Verified cards retain the same exact original locator even without a
            # separately stored source_version. Never infer lineage from their title.
            version = locator.split(":chars:")[0]
        if not row.get("source_id") or not version or not locator:
            key = "unproved:" + str(index)
        else:
            key = json.dumps(
                [row["source_id"], version, locator, meaning(row)],
                sort_keys=True,
                ensure_ascii=False,
            )
        result.setdefault(key, []).append(row)
    return list(result.values())


def representative(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return min(
        rows,
        key=lambda r: (
            bool(r.get("knowledge_binding")),
            r.get("claim_id", r.get("citation_id", "")),
        ),
    )


def aliases(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {
        representative(group)["claim_id"]: sorted(
            r["claim_id"] for r in group if r["claim_id"] != representative(group)["claim_id"]
        )
        for group in groups(rows)
        if len(group) > 1
    }


def model_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Compact only the wire representation; frozen inputs and validators keep IDs."""
    rows = data.get("references", [])
    if not rows:
        return data
    proven = (
        aliases(rows)
        if all("claim_id" in r for r in rows)
        else (
            data.get("reference_aliases", {})
            if data.get("protocol") == "CACHED_QUESTION_V1"
            else {}
        )
    )
    by_id = {r.get("claim_id", r.get("citation_id")): r for r in rows}
    checked = {
        cid: ids
        for cid, ids in proven.items()
        if cid in by_id
        and ids
        and all(i in by_id and meaning(by_id[i]) == meaning(by_id[cid]) for i in ids)
    }
    if not checked:
        return (
            {k: v for k, v in data.items() if k != "reference_aliases"}
            if "reference_aliases" in data
            else data
        )
    omitted = {i for ids in checked.values() for i in ids}
    result = dict(
        data,
        references=[r for cid, r in by_id.items() if cid not in omitted],
        reference_aliases=checked,
    )
    result["instructions"] = data.get("instructions", "") + (
        " reference_aliases仅表示同一来源同版本同位置且条件、角色、对象相同的引用别名；"
        "正文只列一次，别名仍可引用，不构成新增事实或独立来源。"
    )
    return result
