"""Demand coverage for bounded advice research, never itinerary feasibility."""

import re
from typing import Any
from .models import ResearchGap, ResearchRequest
from .planning import QueryPlanner, SufficiencyEvaluator
from .quality import normalize_claim, reference_conflicts

VERSION = "advisory-research-coverage-2"
REVIEWED = {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"}


def limits(days: int | None, regional: bool = False) -> dict[str, int]:
    # These are ceilings, not targets. Independent useful coverage can stop earlier.
    detail = 6 if regional or (days is not None and days >= 3) else 4
    return dict(
        connect=1,
        search=3 if detail == 6 else 2,
        detail=detail,
        model=2 * detail + 1,
        map_place=0,
        map_route=0,
    )


def assess(
    rows: list[dict[str, Any]], request: ResearchRequest, intent: str = "UNDECIDED", *, require_activity_content: bool = False
) -> dict[str, Any]:
    from travel_agent.planning.materials import activities

    rows = [
        r
        for r in rows
        if r.get("review_status") in REVIEWED
        and r.get("source_id")
        and r.get("locator")
        and r.get("knowledge_kind") in {None, "SOURCE_REFERENCE"}
        and r.get("topic")
        in {"ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT", "SEASON", "RISK", "TRADEOFF"}
    ]
    unique = {(r["topic"], normalize_claim(r["text"])): r for r in rows}
    conflicts = reference_conflicts([(r["source_id"], r) for r in rows])
    conflicted = {cid for c in conflicts for cid in c.claim_ids}
    facts: dict[str, set[str]] = {}
    for r in rows:
        facts.setdefault(r["source_id"], set()).add(normalize_claim(r["text"]))
    groups: list[set[str]] = []
    for values in facts.values():
        if not any(len(values & g) / max(1, min(len(values), len(g))) >= 0.8 for g in groups):
            groups.append(values)
    by_topic = {
        t: [r for r in unique.values() if r["topic"] == t and r["claim_id"] not in conflicted]
        for t in ("ROUTE", "EXPERIENCE", "DURATION", "TRANSPORT", "SEASON", "RISK")
    }
    candidates = [
        a
        for a in activities(rows, request.destination or "", intent)
        if a.spatial_status != "MISMATCH"
    ]
    target = min(8, max(2, ((request.days or 2) + 1) // 2 + 1))
    conditions = [c for r in rows for c in r.get("conditions", [])]
    transport = by_topic["TRANSPORT"]
    if request.no_self_drive or request.transport == "PUBLIC_TRANSIT":
        transport = [
            r
            for r in transport
            if re.search(r"公交|公共交通|铁路|高铁|火车|班车|接驳|包车|地铁|大巴|巴士", r["text"])
            and not re.search(r"没有|无班车|无法|不能", r["text"])
        ]
        if request.transport == "PUBLIC_TRANSIT":
            transport = [
                r
                for r in transport
                if re.search(r"公交|公共交通|铁路|高铁|火车|班车|接驳|地铁|大巴|巴士", r["text"])
            ]
    season = by_topic["SEASON"] + [
        r
        for r in rows
        if re.search(
            r"季节|冬季|夏季|春季|秋季|月份|雨季|雪季|结冰|[一二三四五六七八九十\d]+月",
            " ".join([r["text"], *r.get("conditions", [])]),
        )
    ]
    features = [r for r in by_topic["EXPERIENCE"] if len(normalize_claim(r["text"])) >= 12]
    specs = [
        (
            "ROUTES",
            "路线区域、顺序与替代选择",
            len(by_topic["ROUTE"]) >= (2 if (request.days or 2) > 1 else 1),
            by_topic["ROUTE"],
        ),
        ("PLAY", "玩法与取舍的正文支持", bool(features), features),
        ("DURATION", "停留或行程长度参考", bool(by_topic["DURATION"]), by_topic["DURATION"]),
        ("TRANSPORT", "适用交通与区域衔接参考", bool(transport), transport),
        ("SEASON", "时令或季节条件参考", bool(season), season),
        ("SOURCE_COMPARISON", "不同内容来源对照（作者独立性仍未知）", len(groups) >= 2, rows),
        (
            "ACTIVITY_SCOPE",
            f"本次天数下的玩法选择面（目标{target}个，非每日必排）",
            len({a.name for a in candidates}) >= target,
            rows,
        ),
    ]
    uncovered_play: list[str] = []
    if require_activity_content:
        from travel_agent.planning.activity_content import content_references
        supported = []
        for activity in candidates:
            direct = content_references(activity.model_dump(), rows)
            if direct:
                supported.extend(direct)
            else:
                uncovered_play.append(activity.name)
        supported_count = len(candidates) - len(uncovered_play)
        specs.append(("PLAY_DETAIL", "主要备选项目的具体玩法与体验取舍", bool(candidates) and
                      supported_count >= min(target, len(candidates)), supported))
    if request.days and request.days > 1:
        lodging = [
            r
            for r in rows
            if r["claim_id"] not in conflicted
            and re.search(r"住宿|住在|入住|酒店|民宿|落脚", r["text"])
            and len(normalize_claim(r["text"])) >= 12
        ]
        specs.append(("LODGING", "住宿片区与落脚取舍参考", bool(lodging), lodging))
    dimensions: list[dict[str, Any]] = [
        dict(
            key=k,
            label=label,
            status="SUPPORTED_REFERENCE" if ok else "GAP",
            citation_ids=sorted({r["claim_id"] for r in support}),
        )
        for k, label, ok, support in specs
    ]
    gaps = [d for d in dimensions if d["status"] == "GAP"]
    if conflicts:
        conflict_gap = dict(
            key="CONFLICT",
            label="来源对时间或交通存在潜在分歧，适用条件仍待核对",
            status="GAP",
            citation_ids=sorted(conflicted),
        )
        dimensions.append(conflict_gap)
        gaps.append(conflict_gap)
    return dict(
        version=VERSION,
        sufficient=not gaps,
        dimensions=dimensions,
        gaps=gaps,
        activity_count=len({a.name for a in candidates}),
        activity_target=target,
        source_count=len(facts),
        distinct_content_groups=len(groups),
        confirmed_independent_authors=None,
        unique_fact_count=len(unique),
        conflict_count=len(conflicts),
        uncovered_play=uncovered_play,
        conditions=sorted(set(conditions)),
        meaning="仅表示建议研究的材料覆盖；不证明天数、季节、交通或实际可行性已经核实。",
    )


class CoverageEvaluator(SufficiencyEvaluator):
    def __init__(
        self, base: list[dict[str, Any]], scope: str, research_id: str, intent: str, clock: Any,
        *, require_activity_content: bool = False, perspective_gap: str | None = None,
    ):
        self.base, self.scope, self.research_id, self.intent, self.clock = (
            base,
            scope,
            research_id,
            intent,
            clock,
        )
        self.last: dict[str, Any] = {}
        self.require_activity_content = require_activity_content
        self.perspective_gap = perspective_gap

    def gaps(self, request: ResearchRequest, evidence: Any) -> tuple[ResearchGap, ...]:
        from travel_agent.preview.projection import project

        p = project(evidence, scope=self.scope, research_id=self.research_id, now=self.clock())
        rows = [*self.base, *[e for o in p["options"] for e in o["evidence"]], *p["other_clues"]]
        self.last = assess(rows, request, self.intent, require_activity_content=self.require_activity_content)
        # An explicit new perspective must get a chance to inspect one different
        # body even if coarse historical dimensions already appeared covered.
        if self.perspective_gap in {"DIRECT_REVIEW", "CROSS_CHECK"} and not evidence:
            self.last["gaps"].append(dict(key=self.perspective_gap,
                label="按本次新研究视角核对不同正文", status="GAP", citation_ids=[]))
        topics = {
            "ROUTES": ("ROUTE",),
            "PLAY": ("EXPERIENCE",),
            "PLAY_DETAIL": ("EXPERIENCE",),
            "DURATION": ("DURATION",),
            "TRANSPORT": ("TRANSPORT",),
            "SEASON": ("SEASON",),
            "LODGING": ("TRADEOFF",),
            "SOURCE_COMPARISON": ("ROUTE", "EXPERIENCE"),
            "ACTIVITY_SCOPE": ("ROUTE", "EXPERIENCE"),
        }
        return tuple(
            ResearchGap(d["key"], d["label"], topics.get(d["key"], ())) for d in self.last["gaps"]
        )


class CoveragePlanner(QueryPlanner):
    def __init__(self, focus: str | None, *, has_cache: bool = False):
        self.focus = focus
        self.has_cache = has_cache

    def plan(self, request: ResearchRequest, evidence: Any, gaps: Any, previous: set[str]) -> Any:
        from .models import SearchQuery

        prefix = " ".join(t for t in (request.destination, request.time_hint, self.focus) if t)
        terms = {
            "ROUTES": "路线 区域 顺序 取舍",
            "PLAY": "玩法 体验 看点",
            "DURATION": "停留 几天 时间",
            "TRANSPORT": "不自驾 公共交通 区域接驳"
            if request.no_self_drive or request.transport == "PUBLIC_TRANSIT"
            else "交通 区域衔接 限制",
            "SEASON": "季节 月份 注意事项",
            "LODGING": "住宿 片区 落脚 取舍",
            "SOURCE_COMPARISON": "不同路线 体验对比",
            "ACTIVITY_SCOPE": f"{request.days or ''}天 玩法 区域组合",
        }
        options = []
        # Start broad, then issue genuinely different queries for remaining gaps.
        if not previous and not self.has_cache:
            options.append(
                SearchQuery(
                    prefix + f" {request.days or ''}天 路线 玩法",
                    tuple(g.gap_id for g in gaps),
                    "建立玩法与路线比较材料",
                )
            )
        for g in gaps:
            options.append(
                SearchQuery(
                    prefix + " " + terms.get(g.gap_id, "玩法 取舍"), (g.gap_id,), g.description
                )
            )
        seen = {self.normalize(p) for p in previous}
        result = []
        for q in options:
            key = self.normalize(q.text)
            if key not in seen:
                result.append(q)
                seen.add(key)
        return tuple(result)
