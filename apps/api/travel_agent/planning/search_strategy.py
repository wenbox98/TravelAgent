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
    from travel_agent.research.planning import QueryPlanner
    from .materials import activity_subject

    seen = {QueryPlanner.normalize(r.get("query", "")) for r in history}
    keys = [g["key"] for g in matches] or ["DIRECT_REVIEW" if wanted == "DIRECT" else "CROSS_CHECK"]
    candidates: list[tuple[str, str]] = []
    missing_play = [n for n in p.get("agent_missing_play_names", []) if activity_subject(n)]
    for gap in keys:
        terms = TERMS.get(gap, "玩法 交通 住宿取舍")
        if gap == "TRANSPORT" and p["draft"]["driving"] == "NO":
            terms = "不自驾 公交 步行 区域接驳"
        if gap == "PLAY_DETAIL":
            candidates.extend((gap, f"{p['destination']} {' '.join(missing_play[i:i+2])} 具体玩法")
                              for i in range(0, len(missing_play), 2))
        candidates.append((gap, f"{p['destination']} {terms}"))
    gap, query = next(((g, q) for g, q in candidates if QueryPlanner.normalize(q) not in seen), (keys[0], ""))
    return dict(
        completed_angles=sorted(done), missing_angles=missing,
        recommended=dict(search_angle=angle(gap), gap_key=gap, query=query),
        has_new_query=bool(query),
        remaining_search=remaining["search"], remaining_bodies=remaining["detail"],
        meaning="正面研究行程与具体玩法；侧面按缺口研究住宿、交通、季节替代和取舍。每步根据实际结果重排，不重复失败请求。",
    )


def progress(p: dict[str, Any], coverage: dict[str, Any]) -> str:
    """Counts or genuine content/state changes, never another decision's timestamp."""
    return fingerprint([p["draft"], p.get("reference_model_choices"), p.get("selected_reference_overview"),
                        coverage["unique_fact_count"], coverage["source_count"], coverage["gaps"]])


def proposal_gaps(proposals: list[dict[str, Any]], draft: dict[str, Any]) -> list[dict[str, Any]]:
    """At least one useful proposal must cover days, concrete play and overnight area advice."""
    choices = []
    for proposal in proposals:
        assessment = proposal.get("assessment", {})
        missing = []
        if assessment.get("coverage", {}).get("missing_days"):
            missing.append(("DURATION", "生成建议仍有未安排的旅行天数"))
        if assessment.get("content_limited", True):
            missing.append(("PLAY_DETAIL", "生成建议仍有只有名称、没有具体玩法支持的项目"))
        if (draft.get("days") or 0) > 1 and draft.get("trip_budget", {}).get("lodging_scope") != "EXCLUDE" and draft.get("trip_budget", {}).get("nights") != 0 and not proposal.get("lodging", {}).get("area_ids"):
            missing.append(("LODGING", "生成建议仍缺少有来源支持的住宿片区取舍"))
        choices.append(missing)
    best = min(choices, key=len) if choices else [("PLAY_DETAIL", "尚无可用攻略")]
    return [dict(key=k, label=label, status="GAP", citation_ids=[]) for k, label in best]
