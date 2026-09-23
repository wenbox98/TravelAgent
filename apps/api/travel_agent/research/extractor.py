"""Bounded, quote-grounded evidence using the existing domain contract only."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle, SourcePolicy, validator
from travel_agent.providers.llm import LLMProvider, validate_structured

_TOPICS = validator("EvidenceClaim").schema["$defs"]["EvidenceClaim"]["properties"]["topic"]["enum"]
EXTRACTION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["claims"],
    "properties": {"claims": {"type": "array", "maxItems": 12, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["topic", "claim", "quote", "block_index", "confidence"],
        "properties": {
            "topic": {"type": "string", "enum": _TOPICS},
            "claim": {"type": "string", "minLength": 1, "maxLength": 180},
            "quote": {"type": "string", "minLength": 1, "maxLength": 180},
            "block_index": {"type": "integer", "minimum": 0},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }}},
}
_IMAGE_REFERENCE = re.compile(r"(?:见|看|如|参考|详见)图|图[一二三四五六七八九十\d]+|图片|图中|图里")
_PRIVATE = re.compile(
    r"(?i)xsec[_-]?token|access[_-]?token|authorization|cookie\s*[:=]|"
    r"session\s*[:=]|bearer\s+|[?&]token=|SECRET_(?:COOKIE|XSEC|SESSION|AUTHORIZATION|QR)"
)
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
class BodyBlock:
    block_index: int
    text: str
    start: int
    end: int
    locator: str


def body_blocks(body: str | None) -> tuple[BodyBlock, ...]:
    """Nonempty lines, bounded chunks, exact offsets in the unmodified source body."""
    if not body:
        return ()
    digest = sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()
    result: list[BodyBlock] = []
    for match in re.finditer(r"[^\r\n]+", body):
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        end = match.end() - len(match.group()) + len(match.group().rstrip())
        for offset in range(start, end, 700):
            finish = min(offset + 700, end)
            result.append(BodyBlock(
                len(result), body[offset:finish], offset, finish,
                f"note-body:v1:{digest}:chars:{offset}-{finish}",
            ))
    return tuple(result)


@dataclass(frozen=True, repr=False)
class ExtractionResult:
    bundle: EvidenceBundle
    blocks: tuple[BodyBlock, ...]
    gaps: tuple[str, ...]
    mode: str
    provider_called: bool
    rejected_claims: int

    def safe_summary(self) -> dict[str, object]:
        return {"mode": self.mode, "provider_called": self.provider_called,
                "block_count": len(self.blocks), "evidence_count": len(self.bundle["claims"]),
                "rejected_claims": self.rejected_claims, "gaps": list(self.gaps),
                "completeness": self.bundle["completeness"]}


def policy_allows_model(policy: SourcePolicy, *, external: bool, now: datetime) -> bool:
    """Inference permission is independent from ephemeral manual reading permission."""
    reviewed, expires = policy["reviewed_at"], policy["expires_at"]
    return bool(
        policy["basis"] != "UNKNOWN" and policy["allow_read"] and policy["allow_inference"]
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
        output.append({"topic": topic, "claim": quote, "quote": quote,
                       "block_index": block.block_index, "confidence": 0.25})
    return sorted(output, key=lambda row: row["topic"] == "OTHER")[:3]


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
    ) -> ExtractionResult:
        if re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", source_id) is None or _PRIVATE.search(source_id):
            raise ValueError("证据来源标识无效")
        blocks = body_blocks(body) if completeness in {"FULL_TEXT", "PARTIAL_TEXT"} else ()
        gaps: list[str] = []
        if image_count or _IMAGE_REFERENCE.search(body or ""):
            gaps.append("IMAGE_NOT_ANALYZED")
        if _IMAGE_REFERENCE.search(body or ""):
            gaps.append("IMAGE_INFORMATION_REQUIRED")
        if completeness != "FULL_TEXT":
            gaps.append("CONTENT_INCOMPLETE")
        if source_published_at is None:
            gaps.append("PUBLISH_TIME_UNKNOWN")
        gaps.append("TRAVEL_TIME_UNKNOWN")
        rows: list[dict[str, Any]] = []
        mode, called, rejected = "NO_BODY", False, 0
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
        private_input = bool(_PRIVATE.search((body or "") + (source_title or "") + source_id))
        if not read_allowed:
            mode = "POLICY_BLOCKED"
            gaps.append("SOURCE_POLICY_REQUIRED")
            blocks = ()
        elif private_input:
            mode = "POLICY_BLOCKED"
            gaps.append("SENSITIVE_INPUT_REJECTED")
            blocks = ()
            source_title = None
        elif blocks:
            mode = "LOCAL_EXTRACTIVE"
            provider = self.provider
            provider_allowed = provider is not None and policy_allows_model(
                policy, external=getattr(provider, "is_external", True), now=self.clock(),
            ) and (not getattr(provider, "is_mock", False) or source_type == "SYNTHETIC")
            if provider_allowed:
                called = True
                try:
                    assert provider is not None
                    output = provider.structured("extract_evidence", {
                        "is_synthetic": source_type == "SYNTHETIC",
                        "blocks": [{"block_index": b.block_index, "text": b.text} for b in blocks[:120]],
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
        seen: set[str] = set()
        for row in rows:
            index, quote = row["block_index"], row["quote"]
            if (
                index >= len(blocks) or quote not in blocks[index].text or row["claim"] != quote
                or _IMAGE_REFERENCE.search(quote) or _PRIVATE.search(quote)
            ):
                rejected += 1
                continue
            block = blocks[index]
            start = block.start + block.text.index(quote)
            locator = block.locator.rsplit(":chars:", 1)[0] + f":chars:{start}-{start + len(quote)}"
            identity = sha256((source_id + locator + quote).encode("utf-8")).hexdigest()
            if identity in seen:
                continue
            seen.add(identity)
            claims.append({
                "claim_id": "claim-" + identity, "source_id": source_id, "topic": row["topic"],
                "text": quote, "kind": "AUTHOR_OPINION", "locator": locator,
                "support": "PARTIAL" if completeness != "FULL_TEXT" else "SUPPORTED",
                "valid_from": None, "valid_until": None,
                "confidence": min(row["confidence"], 0.25 if mode == "LOCAL_EXTRACTIVE" else 0.6),
            })
        if rejected:
            gaps.append("UNSUPPORTED_CLAIMS_REJECTED")
        if not claims:
            gaps.append("NO_GROUNDED_CLAIMS")
        bundle = EvidenceBundle({
            "source_id": source_id, "source_type": source_type, "source_title": source_title,
            "destination": destination, "applicable_conditions": list(applicable_conditions),
            "completeness": completeness, "fetched_at": fetched_at,
            "source_published_at": source_published_at, "travel_occurred_at": None,
            "policy_id": policy["policy_id"], "claims": claims, "missing_fields": gaps,
            "is_synthetic": source_type == "SYNTHETIC",
        })
        return ExtractionResult(bundle, blocks, tuple(gaps), mode, called, rejected)
