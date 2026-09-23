"""Deterministic gaps, bounded queries and metadata-only candidate selection."""

import json
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle
from travel_agent.providers.llm import LLMProvider

from .models import Candidate, CandidateChoice, ResearchGap, ResearchRequest, SearchQuery


class SufficiencyEvaluator:
    """Conservative coverage for research materials, never a route feasibility proof."""

    def gaps(self, request: ResearchRequest, evidence: tuple[EvidenceBundle, ...]) -> tuple[ResearchGap, ...]:
        claims = [claim for bundle in evidence for claim in bundle["claims"]
                  if claim["locator"] and claim["support"] in {"SUPPORTED", "PARTIAL"}
                  and (claim["confidence"] or 0) >= 0.5]
        topics = {claim["topic"] for claim in claims}
        specs = (
            ("ROUTES", "主要路线或区域组合尚缺可靠正文依据", "ROUTE"),
            ("EXPERIENCES", "主要体验差异尚缺可靠正文依据", "EXPERIENCE"),
            ("DURATION", "大致需要几天尚缺可靠正文依据", "DURATION"),
            ("TRANSPORT", "交通条件及限制尚缺可靠正文依据", "TRANSPORT"),
        )
        gaps = [ResearchGap(key, text, (topic,)) for key, text, topic in specs if topic not in topics]
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
        return tuple(CandidateChoice(candidate, "依据已观测标题、图文类型和当前缺口排序；未读正文",
                                     tuple(gap.gap_id for gap in gaps)) for candidate in ordered)
