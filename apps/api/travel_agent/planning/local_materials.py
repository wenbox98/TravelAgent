"""Reversible, local material selection; entry preference never substitutes validation."""

from copy import deepcopy
from typing import Any
from travel_agent.preview.projection import fingerprint

FIELDS = (
    "draft",
    "knowledge_mode",
    "knowledge_include_test",
    "material_test_input",
    "research_ids",
    "discovery",
    "reuse_materials",
    "reused_claim_ids",
    "reused_context_ids",
    "reused_reference_bindings",
    "local_reuse",
    "activity_pool",
)


def begin(p: dict[str, Any]) -> None:
    if p.get("adopted") or p["draft"]["activities"]:
        raise ValueError("REUSE_REQUIRES_EMPTY_DRAFT")
    p["local_material_preview"] = {k: deepcopy(p[k]) for k in FIELDS if k in p}


def cancel(p: dict[str, Any]) -> bool:
    saved = p.pop("local_material_preview", None)
    if saved is None:
        return False
    for k in FIELDS:
        p.pop(k, None)
    p.update(saved)
    return True


def entry(p: dict[str, Any]) -> dict[str, Any]:
    available = not p.get("adopted") and not p["draft"]["activities"]
    return dict(
        can_select=available,
        include_test=bool(p.get("material_include_test")),
        message="可选当前目的地、同账号且来源仍有效的本地资料；知识卡与历史组合任选其一。"
        if available
        else "当前草稿保留。可修改本次组合；切换资料类型请先取消本次选材或另建独立旅行。",
    )


def reference_binding(row: dict[str, Any]) -> str:
    return fingerprint(
        {
            k: row.get(k)
            for k in (
                "claim_id",
                "source_id",
                "source_version",
                "text",
                "conditions",
                "reference_kind",
                "review_status",
                "route_association",
            )
        }
    )
