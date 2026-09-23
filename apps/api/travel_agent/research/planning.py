"""Deterministic gaps, bounded queries and metadata-only candidate selection."""

import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from travel_agent.domain.models import EvidenceBundle
from travel_agent.providers.llm import LLMProvider

from .models import Candidate, CandidateChoice, ResearchGap, ResearchRequest, SearchQuery
from .quality import claim_clusters, evaluate_coverage, evidence_conflicts, lexical_similarity, source_independence
from .reporting import build_directions


class SufficiencyEvaluator:
    """Conservative coverage for research materials, never a route feasibility proof."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def gaps(self, request: ResearchRequest, evidence: tuple[EvidenceBundle, ...]) -> tuple[ResearchGap, ...]:
        coverage = {item.question_id: item for item in evaluate_coverage(evidence, now=self.clock())}
        specs = (
            ("ROUTES", "主要路线或区域组合尚缺可靠正文依据", "ROUTE", "Q1_ROUTES"),
            ("EXPERIENCES", "主要体验差异尚缺可靠正文依据", "EXPERIENCE", "Q2_EXPERIENCES"),
            ("DURATION", "大致需要几天尚缺可靠正文依据", "DURATION", "Q3_DURATION"),
            ("TRANSPORT", "重要限制、交通或风险尚缺可用依据", "TRANSPORT", "Q4_LIMITATIONS"),
        )
        gaps = [ResearchGap(key, text, (topic,)) for key, text, topic, question in specs
                if coverage[question].status != "SUPPORTED"]
        independence = source_independence(evidence)
        if independence.group_count < 2:
            gaps.append(ResearchGap("SOURCE_CORROBORATION", "尚缺不同来源材料对照；单来源不能概括为普遍结论"))
        if evidence_conflicts(evidence):
            gaps.append(ResearchGap("CONFLICTING_EXPERIENCES", "不同来源存在差异，需要核对各自路线和适用条件"))
        if len({cluster.topic for cluster in claim_clusters(evidence)}) < 3:
            gaps.append(ResearchGap("CLAIM_DIVERSITY", "材料主题单一，尚不足以形成大致研究方向"))
        if any(direction["unknown"] for direction in build_directions(evidence, now=self.clock())):
            gaps.append(ResearchGap("DIRECTION_ASSOCIATION", "部分候选方向尚缺可直接关联的体验、时长或限制材料"))
        # User constraints never become evidence conditions merely by being requested.
        if request.days is not None:
            # A mention of five days does not establish whole-route feasibility.
            # T05 produces materials, so constraint compatibility remains explicit.
            gaps.append(ResearchGap("DAYS_FIT", f"需要后续研究 {request.days} 天适配性", ("DURATION",)))
        if request.no_self_drive:
            gaps.append(ResearchGap("NON_SELF_DRIVE", "需要后续研究不自驾条件", ("TRANSPORT",)))
        if any("IMAGE_INFORMATION_REQUIRED" in bundle["missing_fields"] for bundle in evidence):
            gaps.append(ResearchGap("IMAGE_INFORMATION_REQUIRED", "关键内容指向图片，图片未分析，不能推测"))
        return tuple(gaps)


class QueryPlanner:
    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.split()).casefold()

    def plan(self, request: ResearchRequest, evidence: tuple[EvidenceBundle, ...],
             gaps: tuple[ResearchGap, ...], previous: set[str]) -> tuple[SearchQuery, ...]:
        seen = {self.normalize(value) for value in previous}
        prefix = " ".join(value for value in (request.departure, request.destination, request.time_hint)
                          if value)
        queries: list[SearchQuery] = []
        if not evidence and gaps and not previous:
            queries.append(SearchQuery(prefix + " 攻略", tuple(gap.gap_id for gap in gaps),
                                       "建立路线、体验、时长与交通的初始材料"))
        terms = {"ROUTES": "路线 区域", "EXPERIENCES": "体验 差异",
                 "DURATION": "路线 几天", "TRANSPORT": "交通 限制",
                 "DAYS_FIT": f"{request.days}天 路线", "NON_SELF_DRIVE": "不自驾 公共交通"}
        terms.update({"SOURCE_CORROBORATION": "不同路线 体验对比", "CLAIM_DIVERSITY": "游玩体验 时长",
                      "CONFLICTING_EXPERIENCES": "路线 时长 条件 差异",
                      "DIRECTION_ASSOCIATION": "路线 体验 天数 交通"})
        for gap in gaps:
            term = terms.get(gap.gap_id)
            if term:
                queries.append(SearchQuery(prefix + " " + term, (gap.gap_id,), gap.description))
        result = []
        for query in queries:
            normalized = self.normalize(query.text)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(query)
            if len(result) == 3:
                break
        return tuple(result)


class CandidateSelector:
    def __init__(self, provider: LLMProvider | None = None, *, allow_external: bool = False) -> None:
        self.provider, self.allow_external = provider, allow_external
        self.last_mode = "DETERMINISTIC"

    def select(self, candidates: tuple[Candidate, ...], request: ResearchRequest,
               gaps: tuple[ResearchGap, ...], seen_sources: set[str]) -> tuple[CandidateChoice, ...]:
        self.last_mode = "DETERMINISTIC"
        selected: list[tuple[int, Candidate]] = []
        seen, titles = set(seen_sources), set()
        gap_terms = {"ROUTES": ("路线", "环线", "区域"), "EXPERIENCES": ("体验", "游玩"),
                     "DURATION": ("天", "日"), "TRANSPORT": ("交通", "自驾", "班车"),
                     "DAYS_FIT": (f"{request.days}天",),
                     "NON_SELF_DRIVE": ("不自驾", "公共交通", "包车", "班车")}
        for candidate in candidates:
            title = candidate.title or ""
            normalized = re.sub(r"\W+", "", title).casefold()
            if (candidate.source_id in seen or not candidate.detail_available
                or candidate.note_type != "normal" or not normalized or normalized in titles
                or (request.destination and request.destination not in title)):
                continue
            seen.add(candidate.source_id)
            titles.add(normalized)
            score = sum(term in title for term in ("攻略", "路线", "环线", request.time_hint or "\0"))
            score += sum(term in title for gap in gaps for term in gap_terms.get(gap.gap_id, ()))
            selected.append((-score, candidate))
        selected.sort(key=lambda item: (item[0], item[1].source_id))
        ordered = [candidate for _, candidate in selected]
        if ordered and self.provider is not None and self.allow_external:
            # Only observed titles/types and opaque local IDs cross the provider boundary.
            payload: dict[str, Any] = {"candidates": [
                {"id": str(i), "title": c.title, "note_type": c.note_type}
                for i, c in enumerate(ordered[:20])
            ], "gaps": [g.to_dict() for g in gaps]}
            schema = {"type": "object", "additionalProperties": False, "required": ["ids"],
                      "properties": {"ids": {"type": "array", "items": {"type": "string"},
                                               "uniqueItems": True}}}
            try:
                result = self.provider.structured("candidate_ranking", payload, schema)
                data = json.loads(result) if isinstance(result, str) else result
                ids = data["ids"]
                if set(data) != {"ids"} or sorted(ids) != sorted(str(i) for i in range(min(20, len(ordered)))):
                    raise ValueError("ranking invalid")
                ordered = [ordered[int(i)] for i in ids] + ordered[20:]
                self.last_mode = "LLM_METADATA_ONLY"
            except Exception:
                self.last_mode = "DETERMINISTIC_FALLBACK"
        # Keep the strongest first choice, then prefer observed title diversity.
        diverse: list[Candidate] = []
        ranks = {candidate.source_id: index for index, candidate in enumerate(ordered)}
        while ordered:
            chosen = min(ordered, key=lambda candidate: (
                max((lexical_similarity(candidate.title or "", prior.title or "")
                     for prior in diverse), default=0) * 10 + ranks[candidate.source_id] * 0.1,
                candidate.source_id,
            ))
            diverse.append(chosen)
            ordered.remove(chosen)
        return tuple(CandidateChoice(candidate, "依据真实标题、图文类型、缺口及标题多样性排序；未读正文",
                                     tuple(gap.gap_id for gap in gaps)) for candidate in diverse)
