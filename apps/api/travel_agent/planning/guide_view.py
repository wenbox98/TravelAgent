"""Runtime guide projection and safe Markdown from the adopted version only."""

from copy import deepcopy
import re
from typing import Any
from travel_agent.preview.projection import safe_text
from .flow_models import PlanDraft
from .guide_context import walking, budget_context
from .trip_budget import calculate, defaults

PERIODS = {"UNDECIDED": "时段自定", "MORNING": "上午", "AFTERNOON": "午后", "EVENING": "傍晚"}
DINING = {
    "BETWEEN_ACTIVITIES": "在两个项目之间留用餐窗口，不必卡死钟点。",
    "NEAR_SELECTED_AREA": "优先在已选活动片区解决用餐，具体店铺待选。",
    "OPTIONAL_FINISH": "可以把晚餐作为可选收尾，是否保留由你决定。",
}
LODGING = {
    "NOT_APPLICABLE": "一日不住宿，不纳入本次预算；不是免费酒店。",
    "UNDECIDED": "住宿未定：可比较靠近活动、衔接次日行程和减少换酒店三种思路。",
    "NEAR_ACTIVITIES": "住在活动集中处附近可减少折返；具体交通与房源仍待核实。",
    "NEXT_DAY_AREA": "可考虑衔接次日活动的片区；首日晚间移动是需要权衡的部分。",
    "FEWER_MOVES": "可优先减少换酒店，换取更轻松的打包节奏；可能增加部分往返。",
}


def project(p: dict[str, Any], refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    d = PlanDraft.model_validate(p["draft"])
    from .lodging import context as lodging_context, project_line

    lodging_decision = lodging_context(d)
    b = d.trip_budget.model_copy(deep=True)
    context = budget_context(d)
    b.days = context["days"]
    categories = {(v.category, v.transport_scope) for v in b.lines}
    for v in defaults(d.days, d.inputs.planning_scope == "ACTIVITY_WINDOW"):
        if (v.category, v.transport_scope) not in categories:
            b.lines.append(v)
    b.lines = [project_line(v, lodging_decision) for v in b.lines]
    for v in b.lines:
        if v.locked or v.paid_fen:
            continue
        if v.transport_scope == "ROUND_TRIP" and d.inputs.planning_scope == "ACTIVITY_WINDOW":
            from .guide_models import AmountRange

            v.basis = "EXCLUDED_SELF_ARRANGED"
            v.unit_amount = AmountRange()
            v.status = "UNKNOWN"
    money = calculate(b, [a.activity_id for a in d.activities])
    old = p.get("adopted")
    delta = None
    if old:
        old_p = dict(p, draft=old, adopted=None)
        previous = project(old_p)["budget"]["known_total"]
        now = money["known_total"]
        if previous["min_fen"] is not None and now["min_fen"] is not None:
            delta = dict(
                min_fen=now["min_fen"] - previous["min_fen"],
                max_fen=now["max_fen"] - previous["max_fen"],
                meaning="仅已计入部分的变化，未知项未折算",
            )
    from .guide_assessment import for_draft, current_dining

    assessment = for_draft(d, refs or [])
    from .scoped_context import view as context_view

    context_background = context_view(
        [a.model_dump() for a in d.activities], refs or [], d.guide.context_uses
    )
    dining = [
        dict(day=m.day, window="午餐" if m.window == "LUNCH" else "晚餐", text=DINING[m.strategy])
        for m in current_dining(d)
    ]
    covered = {m["day"] for m in dining}
    if d.activities:
        dining += [
            dict(day=day, window="午餐", text=DINING["NEAR_SELECTED_AREA"])
            for day in sorted({a.day for a in d.activities} - covered)
        ]
    lodging = (
        "NOT_APPLICABLE"
        if lodging_decision["state"] == "OUT_OF_SCOPE"
        else d.guide.lodging.strategy
    )
    if lodging == "NOT_APPLICABLE" and lodging_decision["state"] != "OUT_OF_SCOPE":
        lodging = "UNDECIDED"
    areas = {a["area_id"]: a["name"] for a in p.get("lodging_areas", [])}
    return dict(
        context=context_background,
        assessment=assessment,
        title=d.guide.title,
        reason=d.guide.reason,
        origin=d.guide.origin,
        local_revalidation=bool(
            p.get("local_guide_preview") or p.get("last_guide_revalidation_adoption")
        ),
        walking=walking(d, p.get("request", "")),
        walking_suggestion="步行仅为待选择的建议，尚未核实路线或取得同意。"
        if d.guide.walking_requirement == "OPTIONAL"
        else None,
        budget_context=context,
        available=bool(d.activities),
        feasibility="UNVERIFIED",
        summary=f"{d.days or '天数未定'}{'天' if d.days else ''} · "
        + (
            "交通未定"
            if d.transport == "UNKNOWN"
            else {
                "PUBLIC_TRANSIT": "公共交通优先",
                "WALKING": "步行优先",
                "SELF_DRIVE": "自驾",
                "LOCAL_SERVICE": "当地服务待核实",
            }[d.transport]
        )
        + " · "
        + ("往返自行安排" if d.inputs.planning_scope == "ACTIVITY_WINDOW" else "门到门范围待核实"),
        activities=[
            dict(
                activity_id=a.activity_id,
                name=a.name,
                day=a.day,
                period=PERIODS[a.period],
                stay="停留待选" if a.stay_min is None else f"建议 {a.stay_min}–{a.stay_max} 分钟",
                rest="休息自定" if a.rest_minutes is None else f"建议休息 {a.rest_minutes} 分钟",
                highlight="已发现地点，具体看点资料不足"
                if a.provenance == "SOURCE_MENTION"
                else "自编合成项目，不是现实地点"
                if a.provenance == "SYNTHETIC_TEST"
                else a.description or "来源提供有限参考，适用条件保留",
                provenance=a.provenance,
                timing_origin=a.timing_origin,
                locked_start=a.locked_start,
                locked=a.locked,
                conditions=a.conditions,
                spatial_status=a.spatial_status,
            )
            for a in d.activities
        ],
        dining=dining,
        lodging=dict(
            strategy=lodging,
            text=lodging_decision["reason"] if lodging == "NOT_APPLICABLE" else LODGING[lodging],
            scope=lodging_decision,
            areas=[areas[i] for i in d.guide.lodging.area_ids if i in areas],
            nights=b.nights,
            rooms=b.rooms,
        ),
        budget=money,
        budget_difference=delta,
        assumptions=[*d.guide.assumptions, *b.assumptions],
        tradeoffs=d.guide.impacts,
        unknowns=list(
            dict.fromkeys(
                [
                    *d.guide.unknowns,
                    *d.hard_notes,
                    "路程、开放、预约与实际花费尚未核实；需要时再主动核实。",
                ]
            )
        ),
        test_input=bool(p.get("validation_trip") or p.get("demo")),
    )


def escaped(text: str) -> str:
    safe_text(text, 6000)
    # Never emit HTML, executable Markdown, addresses from endpoints or local paths.
    if re.search(r"(?:[A-Za-z]:[\\/]|file:|localhost|127\.0\.0\.1)", text, re.I):
        raise ValueError("UNSAFE_EXPORT")
    return re.sub(r"([\\`*_{}\[\]()#+.!|<>])", r"\\\1", text).replace("\r", "").replace("\n", " ")


def money_text(v: dict[str, Any]) -> str:
    return (
        "未知" if v["min_fen"] is None else f"{v['min_fen'] / 100:.2f}–{v['max_fen'] / 100:.2f} 元"
    )


def export(db: Any, scope: str, sid: str) -> dict[str, Any]:
    from .flow import PlanningService
    from .advisory import verify_current

    row, state = PlanningService(db, scope).load(sid)
    p = deepcopy(state["planning"])
    if not p.get("adopted"):
        raise ValueError("GUIDE_ADOPT_FIRST")
    p["draft"] = deepcopy(p["adopted"])
    if p["draft"].get("planning_mode") != "ADVISORY":
        raise ValueError("GUIDE_MODE_REQUIRED")
    verify_current(db, scope, sid, p)
    from .guide_assessment import references

    guide = project(p, references(db, scope, sid, p))
    lines = [
        "# " + escaped(p["destination"]) + " · 建议攻略",
        "",
        escaped(guide["summary"]),
        escaped(guide["walking"]["label"]),
        escaped(guide["walking_suggestion"]) if guide["walking_suggestion"] else "",
        "",
        "独立开发测试资料，不是长期偏好。" if guide["test_input"] else "本次私人旅行建议。",
        "",
        "## 玩法与取舍",
        "",
        escaped(guide["title"]),
        escaped(guide["reason"]),
        "本版经本地规则复核（LOCAL_REVALIDATION）；保留原模型判定记录。活动与停留仍为 AI 建议。"
        if guide["local_revalidation"]
        else "",
    ]
    assessment = guide["assessment"]
    lines += ["", "## 内容与天数覆盖", "", assessment["label"], assessment["coverage"]["meaning"]]
    for day in assessment["coverage"]["days"]:
        lines.append(
            f"- 第 {day['day']} 天：{day['label']}"
            + ("；" + escaped(day["reason"]) if day["reason"] else "")
        )
    lines += ["- " + escaped(w) for w in assessment["coverage"]["warnings"]]
    if assessment["coverage"]["status"] == "UNKNOWN_DURATION":
        lines.append("- 总天数未定，尚不能判断是否覆盖整趟旅行。")
    for support in assessment["materials"]:
        name = next(
            a["name"] for a in guide["activities"] if a["activity_id"] == support["activity_id"]
        )
        lines.append("- " + escaped(name) + "：" + support["label"])
        lines += [
            "  - 来源片段（"
            + escaped(e["role"])
            + "，保留原条件）："
            + escaped(e["text"])
            + ("（节选）" if e["truncated"] else "")
            for e in support["excerpts"]
        ]
    for a in guide["activities"]:
        lines += [
            "",
            f"### 第 {a['day']} 天 · {escaped(a['period'])} · {escaped(a['name'])}",
            "",
            escaped(a["highlight"]),
            escaped(a["stay"]) + "；" + escaped(a["rest"]) + "（建议，不是实测）。",
        ]
        if a["locked_start"]:
            lines.append("用户锁定预约：" + a["locked_start"])
        lines += ["- 适用条件：" + escaped(c) for c in a["conditions"]]
    context = guide["context"]
    if context["backgrounds"] or context["supplements"]:
        lines += ["", "## 这组玩法的背景与取舍", ""]
        for item in context["backgrounds"]:
            lines += [
                "- "
                + ("整体背景" if item["scope"] == "GROUP_BACKGROUND" else "直接地点内容")
                + "："
                + escaped(item["subject"])
                + "（"
                + escaped(item["reference_kind"])
                + "）",
                "  - 来源内容：" + escaped(item["text"]),
                "  - 原条件：" + escaped("；".join(item["conditions"])),
                "  - 本次组合线索：" + escaped("、".join(item["activity_names"])),
                "  - " + item["limitation"],
                "  - 引用："
                + escaped(item["citation_id"])
                + "；对象定位："
                + escaped(item["object_locator"]),
            ]
        for use in context["uses"]:
            lines.append("- AI取舍建议：" + escaped(use["reason"]) + "（建议，不是来源事实）")
        for item in context["supplements"]:
            lines += [
                "- 未关联的来源补充：" + escaped(item["text"]),
                "  - 性质："
                + escaped(item["reference_kind"])
                + "；原条件："
                + escaped("；".join(item["conditions"])),
                "  - " + item["reason"],
            ]
    lines += ["", "## 食宿策略", ""]
    lines += [f"- 第 {m['day']} 天{m['window']}：{m['text']}" for m in guide["dining"]]
    lines += [
        guide["lodging"]["text"],
        "片区备选：" + "、".join(escaped(v) for v in guide["lodging"]["areas"])
        if guide["lodging"]["areas"]
        else "具体片区未定。",
    ]
    lines += [
        "",
        "## 参考预算",
        "",
        "口径：" + escaped(guide["budget"]["meaning"]),
        "已知条件：" + "、".join(guide["budget_context"]["known_conditions"]),
        "待补充条件："
        + (
            "、".join(guide["budget_context"]["pending_conditions"])
            or "人数、天数与房晚条件已明确；实际价格仍待核实"
        ),
    ]
    for v in guide["budget"]["lines"]:
        lines.append(
            f"- {escaped(v['label'])}：{v['basis_label']}；{v['unit_label']} × {v['quantity']}，单价目标 {money_text(v['unit_amount'])}；本次计入 {money_text(v['total'])}。{v['note']}"
        )
        lines.extend("  - 条件：" + escaped(c) for c in v["conditions"])
    lines += [
        "",
        "已计入部分：" + money_text(guide["budget"]["known_total"]),
        "未计入或未知类别："
        + "、".join(
            guide["budget"]["missing_categories"]
            + [escaped(v["label"]) for v in guide["budget"]["lines"] if v["counting"] != "INCLUDED"]
        ),
    ]
    lines += ["", "## 假设、取舍与尚待核实", ""]
    lines += [
        "- " + escaped(v) for v in [*guide["assumptions"], *guide["tradeoffs"], *guide["unknowns"]]
    ]
    lines += ["", "## 来源依据", ""]
    if p.get("knowledge_mode"):
        from travel_agent.knowledge.planning import verify

        for c in verify(db, scope, p):
            lines.append(
                "- "
                + escaped(c["title"])
                + "；"
                + escaped(c["kind"])
                + "；历史审核性质："
                + escaped(c["review_scope"])
                + "。"
            )
            for s in c["sources"]:
                # No URL is needed to expose credentials: only canonical allowed URLs.
                url = s.get("canonical_url") or s.get("url")
                if url and re.fullmatch(
                    r"https://(?:www\.)?xiaohongshu\.com/explore/[a-zA-Z0-9]+", url
                ):
                    lines.append("  - 来源：" + url)
    elif p.get("demo"):
        lines.append("- 全部为明确合成的活动与预算假设；无供应商报价。")
    else:
        lines.append("- 沿用本次所选资料；来源历史条件保留，当前可行性未核实。")
    return dict(
        filename="travel-guide.md",
        markdown="\n".join(lines) + "\n",
        adopted_version=p.get("adopted_version", 0),
        revision=row["revision"],
    )
