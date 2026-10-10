"""Goal and gap driven search perspectives; only filtered material enters a model."""

from typing import Any
from travel_agent.preview.projection import fingerprint

DIRECT = {"ROUTES", "PLAY", "PLAY_DETAIL", "DURATION", "ACTIVITY_SCOPE", "DIRECT_REVIEW"}
TERMS = {
    "ROUTES": "路线 区域 顺序 取舍", "PLAY": "具体玩法 看点 游玩体验",
    "PLAY_DETAIL": "具体怎么玩 参观体验 停留", "DURATION": "行程 停留 天数",
    "ACTIVITY_SCOPE": "玩法 区域组合", "DIRECT_REVIEW": "行程 路线 具体玩法",
    "LODGING": "住宿片区 交通便利 落脚 取舍", "TRANSPORT": "交通 接驳 衔接 限制",
    "SEASON": "雨天 替代 季节 注意事项", "CONFLICT": "交通 时间 限制 注意事项",
    "SOURCE_COMPARISON": "不同体验 路线取舍 避坑", "CROSS_CHECK": "住宿片区 交通接驳 避坑",
}


def angle(gap_key: str | None) -> str:
    return "DIRECT" if gap_key in DIRECT else "LATERAL"


def context(p: dict[str, Any], gaps: list[dict[str, Any]], remaining: dict[str, Any]) -> dict[str, Any]:
    history = [r for r in p.get("agent_rounds", []) if r["tool"] == "RESEARCH_GAP"
               and r.get("result", {}).get("search_count", 0)]
    done = {r.get("search_angle", angle(r.get("gap_key"))) for r in history}
    missing = [v for v in ("DIRECT", "LATERAL") if v not in done]
    wanted = missing[0] if missing else None
    ordered = sorted(gaps, key=lambda g: (g["key"] != "PLAY_DETAIL", g["key"] != "LODGING"))
    matches = [g for g in ordered if wanted is None or angle(g["key"]) == wanted]
    gap = matches[0]["key"] if matches else "DIRECT_REVIEW" if wanted == "DIRECT" else "CROSS_CHECK"
    terms = TERMS.get(gap, "玩法 交通 住宿取舍")
    if gap == "TRANSPORT" and p["draft"]["driving"] == "NO":
        terms = "不自驾 公交 步行 区域接驳"
    query = f"{p['destination']} {terms}"
    missing_play = p.get("agent_missing_play_names", [])[:2]
    if gap == "PLAY_DETAIL" and missing_play:
        query = f"{p['destination']} {' '.join(missing_play)} 具体玩法"
    return dict(
        completed_angles=sorted(done), missing_angles=missing,
        recommended=dict(search_angle=angle(gap), gap_key=gap, query=query),
        remaining_search=remaining["search"], remaining_bodies=remaining["detail"],
        meaning="正面研究行程与具体玩法；侧面按缺口研究住宿、交通、季节替代和取舍。每步根据实际结果重排，不重复失败请求。",
    )


def progress(p: dict[str, Any], coverage: dict[str, Any]) -> str:
    """Counts or genuine content/state changes, never another decision's timestamp."""
    return fingerprint([p["draft"], p.get("reference_model_choices"), p.get("selected_reference_overview"),
                        coverage["unique_fact_count"], coverage["source_count"], coverage["gaps"]])
