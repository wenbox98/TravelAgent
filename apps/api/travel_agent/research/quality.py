"""Inspectable coverage and conflicting-source claims. No browser or model calls."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from hashlib import sha256
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle

from .canonical import evidence_key
from .freshness import assess_freshness

_LOCATOR = re.compile(r"note-body:(?:v1:|v2:(?:STATE|DOM|UNKNOWN):)[a-f0-9]{64}:chars:(\d+)-(\d+)$")
_TOPICS = {
    "Q1_ROUTES": {"ROUTE"}, "Q2_EXPERIENCES": {"EXPERIENCE"},
    "Q3_DURATION": {"DURATION"}, "Q4_LIMITATIONS": {"TRANSPORT", "TRADEOFF", "SEASON"},
}


def normalize_claim(text: str) -> str:
    return evidence_key(text)


def has_locator(claim: dict[str, Any]) -> bool:
    locator = claim.get("locator")
    match = _LOCATOR.fullmatch(locator) if isinstance(locator, str) else None
    return bool(match and int(match[1]) < int(match[2]))


def metadata_for(bundle: EvidenceBundle, claim: dict[str, Any]) -> dict[str, Any]:
    return dict(bundle.get("claim_metadata", {}).get(claim["claim_id"], {}))


def confidence_level(bundle: EvidenceBundle, claim: dict[str, Any]) -> str:
    # Legacy numeric confidence does not prove T06 grounding. It can still be displayed.
    return str(metadata_for(bundle, claim).get("confidence_level", "LOW"))


def is_grounded(bundle: EvidenceBundle, claim: dict[str, Any]) -> bool:
    """Accepted extractive evidence; legacy locators alone do not attest grounding.

    This checks the persisted extraction attestation, not a fresh source re-read.
    Exact quote/block correspondence is verified at the extractor boundary.
    """
    meta = metadata_for(bundle, claim)
    return bool(has_locator(claim) and claim.get("support") in {"SUPPORTED", "PARTIAL"}
                and ("context_review_status" not in meta or meta["context_review_status"] in {"WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED"})
                and meta.get("source_block_ids") and meta.get("extraction_basis")
                and meta.get("extraction_method") in {"LLM", "MOCK", "LOCAL_EXTRACTIVE"})


@dataclass(frozen=True, repr=False)
class ClaimCluster:
    cluster_id: str
    claim_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    topic: str
    independence: str = "UNKNOWN"


@dataclass(frozen=True, repr=False)
class EvidenceConflict:
    conflict_id: str
    claim_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    reason: str
    status: str = "POTENTIAL_CONFLICT"


@dataclass(frozen=True, repr=False)
class Coverage:
    question_id: str
    status: str
    claim_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    reason: str

    def to_dict(self, *, safe: bool = False) -> dict[str, Any]:
        if safe:
            return {"question_id": self.question_id, "status": self.status,
                    "claim_count": len(self.claim_ids), "source_count": len(self.source_ids),
                    "reason": self.reason}
        return asdict(self)


@dataclass(frozen=True)
class SourceIndependence:
    distinct_sources: int
    group_count: int
    confirmed_independent_sources: int = 0
    status: str = "UNKNOWN"


def claim_clusters(evidence: tuple[EvidenceBundle, ...]) -> tuple[ClaimCluster, ...]:
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for bundle in evidence:
        for claim in bundle["claims"]:
            if not is_grounded(bundle, claim):
                continue
            key = (claim["topic"], normalize_claim(claim["text"]))
            groups.setdefault(key, []).append((bundle["source_id"], claim["claim_id"]))
    return tuple(ClaimCluster("cluster-" + sha256((topic + text).encode()).hexdigest()[:20],
                              tuple(dict.fromkeys(cid for _, cid in values)),
                              tuple(sorted({sid for sid, _ in values})), topic)
                 for (topic, text), values in groups.items())


def source_independence(evidence: tuple[EvidenceBundle, ...]) -> SourceIndependence:
    by_source: dict[str, set[str]] = {}
    for bundle in evidence:
        by_source.setdefault(bundle["source_id"], set()).update(
            normalize_claim(c["text"]) for c in bundle["claims"] if is_grounded(bundle, c)
        )
    groups: list[set[str]] = []
    for values in by_source.values():
        if not values:
            continue
        # Identical / largely shared excerpts are not independent corroboration.
        if not any(len(values & group) / max(1, min(len(values), len(group))) >= 0.8
                   for group in groups):
            groups.append(values)
    return SourceIndependence(len(by_source), len(groups), status=(
        "SINGLE_SOURCE" if len(by_source) <= 1 else
        "POSSIBLE_REPUBLICATION" if len(groups) < len(by_source) else "UNKNOWN"
    ))


def evidence_conflicts(evidence: tuple[EvidenceBundle, ...]) -> tuple[EvidenceConflict, ...]:
    claims = [(bundle["source_id"], claim) for bundle in evidence for claim in bundle["claims"]
              if is_grounded(bundle, claim)]
    result: list[EvidenceConflict] = []
    positive = ("宽松", "轻松", "充裕", "足够", "不赶")
    negative = ("很赶", "太赶", "赶路", "不够", "紧张", "来不及")

    def stance(text: str) -> tuple[bool, bool]:
        affirmed = any(re.search(r"(?<!不)(?<!没)(?<!未)" + word, text) for word in positive)
        denied = any(word in text for word in negative) or any(
            "不" + word in text for word in positive if not word.startswith("不")
        )
        return affirmed, denied

    def route_label(text: str) -> str | None:
        match = re.match(r"^(.{1,32}?(?:环线|路线|区域|方向))", text)
        return match[1] if match else None

    for i, (source, claim) in enumerate(claims):
        text = normalize_claim(claim["text"])
        days = set(re.findall(r"\d+(?:天|日)", text))
        for other_source, other in claims[i + 1:]:
            if source == other_source or claim["topic"] != other["topic"]:
                continue
            other_text = normalize_claim(other["text"])
            if other.get("support") == "UNSUPPORTED" or not has_locator(other):
                continue
            label, other_label = route_label(text), route_label(other_text)
            if label and other_label and label != other_label:
                continue
            same_duration = bool(days & set(re.findall(r"\d+(?:天|日)", other_text)))
            a_positive, a_negative = stance(text)
            b_positive, b_negative = stance(other_text)
            opposing = (a_positive and b_negative) or (b_positive and a_negative)
            negated = ("没有班车" in text and "可以乘班车" in other_text
                       or "没有班车" in other_text and "可以乘班车" in text)
            if (same_duration and opposing) or negated:
                ids = tuple(sorted((claim["claim_id"], other["claim_id"])))
                result.append(EvidenceConflict("conflict-" + sha256("|".join(ids).encode()).hexdigest()[:20],
                                               ids, tuple(sorted((source, other_source))),
                                               "作者对相同时间线索或交通条件表达不同，适用路线和条件仍需核对"))
    return tuple(result)


def evaluate_coverage(evidence: tuple[EvidenceBundle, ...], *, now: datetime | None = None) -> tuple[Coverage, ...]:
    now = now or datetime.now(timezone.utc)
    from .reporting import build_directions
    directions = build_directions(evidence, now=now)
    fields = {"Q1_ROUTES": "route_evidence", "Q2_EXPERIENCES": "experiences",
              "Q3_DURATION": "duration_clues", "Q4_LIMITATIONS": "limitations"}
    conflicts = evidence_conflicts(evidence)
    conflicted = {cid for conflict in conflicts for cid in conflict.claim_ids}
    result: list[Coverage] = []
    for question, topics in _TOPICS.items():
        associated = {row["claim_id"] for direction in directions for row in direction[fields[question]]}
        rows = [(bundle, claim) for bundle in evidence for claim in bundle["claims"]
                if claim["topic"] in topics and has_locator(claim)
                and claim.get("support") != "UNSUPPORTED"]
        supported: list[tuple[EvidenceBundle, dict[str, Any]]] = []
        for bundle, claim in rows:
            meta = metadata_for(bundle, claim)
            freshness = assess_freshness(claim, bundle, now=now)
            if (is_grounded(bundle, claim) and claim["claim_id"] in associated
                and confidence_level(bundle, claim) in {"MEDIUM", "HIGH"}
                and meta.get("extraction_method") in {"LLM", "MOCK"}
                and claim["support"] in {"SUPPORTED", "PARTIAL"}
                and claim["claim_id"] not in conflicted
                and not (question == "Q3_DURATION" and meta.get("duration_scope") == "DAY_SEGMENT")
                and freshness.status in {"USABLE_REFERENCE", "HISTORICAL"}):
                supported.append((bundle, claim))
        status = "SUPPORTED" if supported else "PARTIAL" if rows else "UNSUPPORTED"
        reason = ("DIRECT_GROUNDED_REFERENCE" if supported else
                  "WEAK_STALE_CONFLICTED_OR_UNDATED_REFERENCE" if rows else "NO_GROUNDED_REFERENCE")
        result.append(Coverage(question, status, tuple(dict.fromkeys(claim["claim_id"] for _, claim in rows)),
                               tuple(sorted({bundle["source_id"] for bundle, _ in rows})), reason))
    return tuple(result)


def lexical_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_claim(left), normalize_claim(right)).ratio()
