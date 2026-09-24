"""Bounded, quote-grounded evidence using the existing domain contract only."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle, SourcePolicy, validator
from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT, has_usage_basis
from travel_agent.providers.llm import LLMProvider, validate_structured
from .canonical import BodyBlock, CanonicalBody, body_blocks, canonicalize, evidence_key
from .model_input import outbound_blocks

__all__ = ["BodyBlock", "body_blocks", "EvidenceExtractor", "ExtractionResult", "EXTRACTION_SCHEMA"]

_TOPICS = validator("EvidenceClaim").schema["$defs"]["EvidenceClaim"]["properties"]["topic"]["enum"]
EXTRACTION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["claims"],
    "properties": {"claims": {"type": "array", "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "kind", "claim", "quote", "source_block_ids", "confidence",
                     "applicable_conditions", "extraction_basis"],
        "properties": {
            "topic": {"type": "string", "enum": _TOPICS},
            "kind": {"type": "string", "enum": ["AUTHOR_OPINION"]},
            "claim": {"type": "string", "minLength": 1, "maxLength": 180},
            "quote": {"type": "string", "minLength": 1, "maxLength": 180},
            "source_block_ids": {"type": "array", "minItems": 1, "maxItems": 8,
                                 "uniqueItems": True, "items": {"type": "integer", "minimum": 0}},
            "confidence": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "extraction_basis": {"type": "string", "minLength": 1, "maxLength": 240},
            "applicable_conditions": {"type": "array", "maxItems": 8, "items": {
                "type": "object", "additionalProperties": False,
                "required": ["text", "quote", "source_block_id"], "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 120},
                    "quote": {"type": "string", "minLength": 1, "maxLength": 120},
                    "source_block_id": {"type": "integer", "minimum": 0},
                },
            }},
        },
    }}},
}
_IMAGE_REFERENCE = re.compile(r"(?:见|看|如|参考|详见)图|图[一二三四五六七八九十\d]+|图片|图中|图里")
_PRIVATE = SENSITIVE_RESEARCH_TEXT
_TOPIC_PATTERNS = (
    ("TRANSPORT", r"公交|大巴|班车|包车|自驾|交通|打车|地铁|换乘"),
    ("DURATION", r"[\d一二三四五六七八九十两]+\s*(?:天|日|小时)|半天|停留"),
    ("ROUTE", r"路线|线路|出发|沿途|→"),
    ("PRICE", r"费用|价格|门票|\d+元"),
    ("SEASON", r"季节|国庆|秋季|冬季|春季|夏季"),
    ("TRADEOFF", r"拥挤|排队|小心|注意|不建议|风险"),
    ("EXPERIENCE", r"体验|徒步|风景|景色|游玩|美食|温泉"),
)


@dataclass(frozen=True, repr=False)
class ExtractionResult:
    bundle: EvidenceBundle
    blocks: tuple[BodyBlock, ...]
    gaps: tuple[str, ...]
    mode: str
    provider_called: bool
    rejected_claims: int
    canonical: CanonicalBody | None = None

    def safe_summary(self) -> dict[str, object]:
        return {"mode": self.mode, "provider_called": self.provider_called,
                "block_count": len(self.blocks), "evidence_count": len(self.bundle["claims"]),
                "rejected_claims": self.rejected_claims, "gaps": list(self.gaps),
                "completeness": self.bundle["completeness"],
                "canonical": self.canonical.safe_summary() if self.canonical else None}


def policy_allows_model(policy: SourcePolicy, *, external: bool, now: datetime) -> bool:
    """Inference permission is independent from ephemeral manual reading permission."""
    reviewed, expires = policy["reviewed_at"], policy["expires_at"]
    return bool(
        has_usage_basis(policy) and policy["allow_read"] and policy["allow_inference"]
        and (not external or policy["allow_external_model"])
        and reviewed is not None and datetime.fromisoformat(reviewed) <= now
        and (expires is None or datetime.fromisoformat(expires) > now)
    )


def _fallback(blocks: tuple[BodyBlock, ...]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for block in blocks[:120]:
        if _IMAGE_REFERENCE.search(block.text) or _PRIVATE.search(block.text):
            continue
        # A literal short excerpt, not a fabricated summary or fixture material.
        quote = re.split(r"[。！？!?]", block.text, maxsplit=1)[0].strip()[:140]
        if not quote:
            continue
        topic = next((name for name, pattern in _TOPIC_PATTERNS if re.search(pattern, quote)), "OTHER")
        output.append({"topic": topic, "kind": "AUTHOR_OPINION", "claim": quote, "quote": quote,
                       "source_block_ids": [block.block_index], "confidence": "LOW",
                       "applicable_conditions": [], "extraction_basis": "本地逐字摘取，未运行模型"})
    return sorted(output, key=lambda row: row["topic"] == "OTHER")[:3]


def _grounded(row: dict[str, Any], blocks: tuple[BodyBlock, ...]) -> tuple[int, list[str]] | None:
    ids, quote = row["source_block_ids"], row["quote"]
    if (row["claim"] != quote or any(i >= min(len(blocks), 120) for i in ids)
        or _IMAGE_REFERENCE.search(quote) or _PRIVATE.search(quote)):
        return None
    supporting = {i for i in ids if quote in blocks[i].text}
    if not supporting:
        return None
    first = min(supporting)
    conditions = []
    for condition in row["applicable_conditions"]:
        index, text = condition["source_block_id"], condition["text"]
        if (index not in ids or text != condition["quote"] or text not in blocks[index].text
            or _PRIVATE.search(text) or _IMAGE_REFERENCE.search(text) or re.search(r"(?i)https?://", text)):
            return None
        supporting.add(index)
        if text not in conditions:
            conditions.append(text)
    return (first, conditions) if supporting == set(ids) else None


def _confidence(mode: str, canonical: CanonicalBody, conditions: list[str], proposed: str) -> str:
    levels = ("LOW", "MEDIUM", "HIGH")
    ceiling = 0 if mode == "LOCAL_EXTRACTIVE" or canonical.relation == "CONFLICT" else 1
    if ceiling and canonical.completeness == "FULL_TEXT" and not canonical.truncation_risk and conditions:
        ceiling = 2
    return levels[min(ceiling, levels.index(proposed))]


def _travel_date(body: str) -> str | None:
    """A unique literal date field, normalized at day precision; never publication time."""
    dates = set(re.findall(r"(?m)^旅行日期[ \t]*[:：][ \t]*(\d{4}-\d{2}-\d{2})[ \t]*[。.]?[ \t]*$", body))
    if len(dates) != 1:
        return None
    try:
        observed = date.fromisoformat(dates.pop())
    except ValueError:
        return None
    return observed.isoformat() + "T00:00:00+00:00"


class EvidenceExtractor:
    def __init__(
        self, provider: LLMProvider | None = None, *, clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.provider = provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def extract(
        self, *, source_id: str, source_title: str | None, body: str | None,
        completeness: str, fetched_at: str, policy: SourcePolicy,
        source_published_at: str | None = None, source_type: str = "XHS",
        destination: str | None = None, applicable_conditions: Sequence[dict[str, Any]] = (),
        image_count: int = 0, temporary_read_allowed: bool = False,
        research_gaps: Sequence[str] = (),
        dom_body: str | None = None,
    ) -> ExtractionResult:
        if re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", source_id) is None or _PRIVATE.search(source_id):
            raise ValueError("证据来源标识无效")
        view = canonicalize(body, dom_body, completeness=completeness)
        completeness = view.completeness
        blocks = view.blocks if completeness in {"FULL_TEXT", "PARTIAL_TEXT"} else ()
        gaps: list[str] = []
        image_reference = _IMAGE_REFERENCE.search((body or "") + "\n" + (dom_body or ""))
        if image_count or image_reference:
            gaps.append("IMAGE_NOT_ANALYZED")
        if image_reference:
            gaps.append("IMAGE_INFORMATION_REQUIRED")
        if completeness != "FULL_TEXT":
            gaps.append("CONTENT_INCOMPLETE")
        if view.relation in {"CONFLICT", "OVERLAP"}:
            gaps.append("BODY_VERSIONS_CONFLICT" if view.relation == "CONFLICT" else "BODY_OVERLAP_UNVERIFIED")
        if source_published_at is None:
            gaps.append("PUBLISH_TIME_UNKNOWN")
        rows: list[dict[str, Any]] = []
        mode, called, rejected = "NO_BODY", False, 0
        sent_block_ids: set[int] | None = None
        canonical: CanonicalBody | None = view
        now = self.clock()
        expiry = policy["expires_at"]
        reviewed = policy["reviewed_at"]
        temporary_unknown = (
            policy["basis"] == "UNKNOWN" and temporary_read_allowed
            and (expiry is None or datetime.fromisoformat(expiry) > now)
            and (reviewed is None or datetime.fromisoformat(reviewed) <= now)
        )
        read_allowed = bool(
            policy["allow_read"] and policy["allow_inference"]
            and (temporary_unknown or policy_allows_model(policy, external=False, now=now))
        )
        private_input = bool(_PRIVATE.search((body or "") + (dom_body or "") + (source_title or "") + source_id))
        if not read_allowed:
            mode = "POLICY_BLOCKED"
            gaps.append("SOURCE_POLICY_REQUIRED")
            blocks = ()
            canonical = None
        elif private_input:
            mode = "POLICY_BLOCKED"
            gaps.append("SENSITIVE_INPUT_REJECTED")
            blocks = ()
            canonical = None
            source_title = None
        elif blocks:
            mode = "LOCAL_EXTRACTIVE"
            provider = self.provider
            provider_allowed = provider is not None and policy_allows_model(
                policy, external=getattr(provider, "is_external", True), now=self.clock(),
            ) and (not getattr(provider, "is_mock", False) or source_type == "SYNTHETIC")
            if provider_allowed:
                model_blocks = (outbound_blocks(blocks) if getattr(provider, "is_external", True)
                                else blocks[:120])
                if len(model_blocks) != len(blocks[:120]):
                    gaps.append("MODEL_INPUT_MINIMIZED")
                try:
                    assert provider is not None
                    if not model_blocks:
                        raise ValueError("NO_OUTBOUND_BLOCKS")
                    called = True
                    sent_block_ids = {b.block_index for b in model_blocks}
                    output = provider.structured("extract_evidence", {
                        "is_synthetic": source_type == "SYNTHETIC",
                        "blocks": [{"block_index": b.block_index, "text": b.normalized_text,
                                    "origin": b.origin, "truncation_risk": b.truncation_risk}
                                   for b in model_blocks],
                        "completeness": completeness,
                        "research_gaps": list(research_gaps),
                    }, EXTRACTION_SCHEMA)
                    rows = validate_structured(output, EXTRACTION_SCHEMA)["claims"]
                    mode = "MOCK" if getattr(provider, "is_mock", False) else "LLM"
                except Exception:
                    gaps.append("LLM_UNAVAILABLE_OR_INVALID")
            if mode == "LOCAL_EXTRACTIVE":
                rows = _fallback(blocks)
                gaps.append("LOCAL_EXTRACTIVE_ONLY")
        claims: list[dict[str, Any]] = []
        metadata: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for row in rows:
            grounded = (None if mode == "LLM" and sent_block_ids is not None
                        and not set(row["source_block_ids"]) <= sent_block_ids
                        else _grounded(row, blocks))
            if grounded is None or canonical is None:
                rejected += 1
                continue
            index, conditions = grounded
            quote = row["quote"]
            block = blocks[index]
            start = block.start + block.text.index(quote)
            locator = block.locator.rsplit(":chars:", 1)[0] + f":chars:{start}-{start + len(quote)}"
            # Within this source only; changed opinions/negations remain different.
            key = evidence_key(quote) + "|" + "|".join(sorted(evidence_key(c) for c in conditions))
            identity = sha256((source_id + "|" + key).encode("utf-8")).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            level = _confidence(mode, canonical, conditions, row["confidence"])
            claims.append({
                "claim_id": "claim-" + identity, "source_id": source_id, "topic": row["topic"],
                "text": quote, "kind": "AUTHOR_OPINION", "locator": locator,
                "support": "PARTIAL" if completeness != "FULL_TEXT" else "SUPPORTED",
                "valid_from": None, "valid_until": None,
                "confidence": {"LOW": 0.25, "MEDIUM": 0.6, "HIGH": 0.8}[level],
            })
            metadata["claim-" + identity] = {
                "source_block_ids": row["source_block_ids"], "body_origin": canonical.origin,
                "extraction_method": mode, "confidence_level": level,
                "extraction_basis": "逐字引文和来源条件已核对正文块；等级由定位、完整度与截断风险共同限定。",
                "applicable_conditions": conditions, "canonical_relation": canonical.relation,
                "truncation_risk": canonical.truncation_risk,
                "block_locators": [blocks[i].locator for i in row["source_block_ids"]],
            }
        if rejected:
            gaps.append("UNSUPPORTED_CLAIMS_REJECTED")
        if not claims:
            gaps.append("NO_GROUNDED_CLAIMS")
        travel_date = _travel_date(canonical.text) if canonical is not None and blocks else None
        if travel_date is None:
            gaps.append("TRAVEL_TIME_UNKNOWN")
        bundle = EvidenceBundle({
            "source_id": source_id, "source_type": source_type, "source_title": source_title,
            "destination": destination, "applicable_conditions": list(applicable_conditions),
            "completeness": completeness, "fetched_at": fetched_at,
            "source_published_at": source_published_at, "travel_occurred_at": travel_date,
            "policy_id": policy["policy_id"], "claims": claims, "missing_fields": gaps,
            "claim_metadata": metadata,
            "is_synthetic": source_type == "SYNTHETIC",
        })
        return ExtractionResult(bundle, blocks, tuple(gaps), mode, called, rejected, canonical)
