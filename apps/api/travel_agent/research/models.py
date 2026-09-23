"""Internal research orchestration types; evidence remains the existing contract."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from travel_agent.domain.models import EvidenceBundle

StopReason = Literal[
    "EVIDENCE_SUFFICIENT", "BUDGET_EXHAUSTED", "NEED_LOGIN", "VERIFICATION_REQUIRED",
    "NO_USEFUL_CANDIDATES", "SOURCE_UNAVAILABLE", "ERROR",
]


@dataclass(frozen=True)
class ResearchRequest:
    departure: str | None = None
    destination: str | None = None
    time_hint: str | None = None
    research_question: str = "有哪些大致路线或区域组合，体验、时长和交通条件有什么差异？"
    days: int | None = None
    no_self_drive: bool = False
    budget_cny_fen: int | None = None
    transport: str | None = None
    traveler_count: int | None = None

    def __post_init__(self) -> None:
        for value in (self.days, self.traveler_count):
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError("天数和人数须为正整数或未知")
        if self.budget_cny_fen is not None and (
            type(self.budget_cny_fen) is not int or self.budget_cny_fen < 0
        ):
            raise ValueError("预算须为非负整数或未知")
        if not self.research_question.strip():
            raise ValueError("研究问题不能为空")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResearchBudget:
    max_search_operations: int = 3
    max_feed_details: int = 6

    def __post_init__(self) -> None:
        if (type(self.max_search_operations) is not int
            or not 0 <= self.max_search_operations <= 3
            or type(self.max_feed_details) is not int or not 0 <= self.max_feed_details <= 6):
            raise ValueError("PoC 上限为 3 次搜索、6 次详情，允许零预算")


@dataclass(frozen=True)
class ResearchGap:
    gap_id: str
    description: str
    topics: tuple[str, ...] = ()
    status: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchQuery:
    text: str
    gap_ids: tuple[str, ...]
    purpose: str


@dataclass(frozen=True, repr=False)
class Candidate:
    source_id: str
    title: str | None
    note_type: str
    detail_available: bool


@dataclass(frozen=True, repr=False)
class CandidateChoice:
    candidate: Candidate
    reason: str
    expected_gap_to_fill: tuple[str, ...]
    metadata_used: tuple[str, ...] = ("source_id", "title", "note_type", "detail_available")


@dataclass(frozen=True, repr=False)
class DetailMaterial:
    source_id: str
    title: str | None
    body: str
    completeness: str
    fetched_at: str
    published_at: str | None = None
    image_count: int = 0
    identity_match: bool = True
    source_type: str = "XHS"


@dataclass(frozen=True, repr=False)
class ResearchReport:
    research_id: str
    revision: int
    run_id: str
    request: ResearchRequest
    evidence: tuple[EvidenceBundle, ...]
    gaps: tuple[ResearchGap, ...]
    stop_reason: StopReason
    operations: dict[str, int]
    cache_sources: int
    query_count: int = 0
    candidate_count: int = 0
    extraction_modes: tuple[str, ...] = ()
    obsolete: bool = False
    diagnostic: str | None = None
    selection: tuple[CandidateChoice, ...] = field(default=(), repr=False)

    def safe_summary(self) -> dict[str, Any]:
        """No real claim/title, source IDs, access URLs or account identifiers."""
        claims = [claim for bundle in self.evidence for claim in bundle["claims"]]
        return {
            "revision": self.revision, "stop_reason": self.stop_reason,
            "operations": dict(self.operations), "cache_sources": self.cache_sources,
            "query_count": self.query_count, "candidate_count": self.candidate_count,
            "source_count": len(self.evidence), "evidence_count": len(claims),
            "topics": sorted({claim["topic"] for claim in claims}),
            "gaps": [gap.to_dict() for gap in self.gaps],
            "completeness": [bundle["completeness"] for bundle in self.evidence],
            "extraction_modes": list(self.extraction_modes), "obsolete": self.obsolete,
            "diagnostic": self.diagnostic, "is_final_itinerary": False,
            "claim_basis": "EXTRACTED_FROM_SOURCE", "gaps_basis": "DERIVED",
            "travel_time_unknown": all(bundle["travel_occurred_at"] is None
                                       for bundle in self.evidence),
            "network": {"measurement": "NOT_MEASURED", "requests": None, "bytes": None},
        }

    def material_view(self) -> dict[str, Any]:
        """Private in-memory presentation; persistence/export needs SourcePolicy checks."""
        groups: dict[str, list[dict[str, Any]]] = {
            "routes_areas": [], "experiences": [], "duration_clues": [], "transport_clues": [],
        }
        mapping = {"ROUTE": "routes_areas", "EXPERIENCE": "experiences",
                   "DURATION": "duration_clues", "TRANSPORT": "transport_clues"}
        for bundle in self.evidence:
            for claim in bundle["claims"]:
                group = mapping.get(claim["topic"])
                if group:
                    groups[group].append({**claim, "basis": "EXTRACTED_FROM_SOURCE",
                                          "completeness": bundle["completeness"]})
        return {**self.safe_summary(), "materials": groups,
                "observed": {"sources_read": len(self.evidence)},
                "unknown": [gap.description for gap in self.gaps]}


class ResearchStopped(RuntimeError):
    def __init__(self, reason: StopReason, code: str | None = None,
                 *, fallback_eligible: bool = False) -> None:
        self.reason = reason
        self.code = code or reason
        self.fallback_eligible = fallback_eligible
        super().__init__(reason)
