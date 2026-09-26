"""Exact extractive checks. Passing location is not a semantic/context approval."""

from dataclasses import dataclass
import re
from typing import Any

from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT
from .canonical import BodyBlock

RULE_VERSION = 2
IMAGE_REFERENCE = re.compile(r"(?:见|看|如|参考|详见)图|图[一二三四五六七八九十\d]+|图片|图中|图里")
REASONS = frozenset({"LOCATOR_PASS", "CLAIM_QUOTE_MISMATCH", "QUOTE_NOT_IN_CITED_BLOCK",
    "BLOCK_ID_OUT_OF_RANGE", "UNSENT_BLOCK_REFERENCED", "CONDITION_QUOTE_MISMATCH",
    "CONDITION_NOT_IN_CITED_BLOCK", "UNSUPPORTED_EXTRA_BLOCK_REFERENCE", "DUPLICATE_BLOCK_REFERENCE",
    "IMAGE_INFORMATION_REQUIRED", "SENSITIVE_CONTENT_REJECTED"})
CONTEXT_REASONS = frozenset({"CONTEXT_REVIEW_REQUIRED", "WORK_CONTEXT_VERIFIED", "CONTEXT_UNCERTAIN",
    "CONTEXT_NEGATION_OMITTED", "CONTEXT_CONDITION_OMITTED", "CONTEXT_SUBJECT_OMITTED",
    "CONTEXT_TIME_UNCERTAIN", "CONTEXT_TRANSPORT_MISMATCH", "DEPENDENCY_UNRESOLVED",
    "DEPENDENCY_INDEPENDENT", "NOT_TRAVEL_EVIDENCE", "UNVERIFIED_IMPORTANT_FACT"})
REVIEW_DIMENSIONS = frozenset({"subject", "negation", "hypothesis", "time", "transport", "scope",
                               "source_kind", "images"})


@dataclass(frozen=True, repr=False)
class GroundingResult:
    passed: bool
    reason_code: str
    block_ids: tuple[int, ...]
    first_block: int | None = None
    conditions: tuple[str, ...] = ()

    def safe_dict(self, candidate_index: int) -> dict[str, Any]:
        return {"candidate_index": candidate_index, "passed": self.passed,
                "reason_code": self.reason_code, "block_ids": list(self.block_ids), "rule_version": RULE_VERSION}


def check_grounding(row: dict[str, Any], blocks: tuple[BodyBlock, ...],
                    sent_block_ids: set[int] | None = None) -> GroundingResult:
    ids, quote = row["source_block_ids"], row["quote"]
    def fail(reason: str) -> GroundingResult:
        return GroundingResult(False, reason, tuple(ids))
    texts = [row["claim"], quote] + [c[k] for c in row["applicable_conditions"] for k in ("text", "quote")]
    if any(SENSITIVE_RESEARCH_TEXT.search(t) or re.search(r"(?i)https?://", t) for t in texts):
        return fail("SENSITIVE_CONTENT_REJECTED")
    if any(IMAGE_REFERENCE.search(t) for t in texts):
        return fail("IMAGE_INFORMATION_REQUIRED")
    if row["claim"] != quote:
        return fail("CLAIM_QUOTE_MISMATCH")
    if not ids or any(type(i) is not int or not 0 <= i < min(len(blocks), 120) for i in ids):
        return fail("BLOCK_ID_OUT_OF_RANGE")
    if len(set(ids)) != len(ids):
        return fail("DUPLICATE_BLOCK_REFERENCE")
    if sent_block_ids is not None and not set(ids) <= sent_block_ids:
        return fail("UNSENT_BLOCK_REFERENCED")
    supporting = {i for i in ids if quote in blocks[i].text}
    if not supporting:
        return fail("QUOTE_NOT_IN_CITED_BLOCK")
    first = min(supporting)
    conditions = []
    for condition in row["applicable_conditions"]:
        index, text = condition["source_block_id"], condition["text"]
        if not 0 <= index < len(blocks):
            return fail("BLOCK_ID_OUT_OF_RANGE")
        if text != condition["quote"]:
            return fail("CONDITION_QUOTE_MISMATCH")
        if index not in ids or text not in blocks[index].text:
            return fail("CONDITION_NOT_IN_CITED_BLOCK")
        supporting.add(index)
        if text not in conditions:
            conditions.append(text)
    if supporting != set(ids):
        return fail("UNSUPPORTED_EXTRA_BLOCK_REFERENCE")
    return GroundingResult(True, "LOCATOR_PASS", tuple(ids), first, tuple(conditions))


def context_hazard(row: dict[str, Any], blocks: tuple[BodyBlock, ...]) -> str | None:
    """Catch one provable clipping error; all other semantics still require Work review."""
    for i in row["source_block_ids"]:
        text = blocks[i].text
        position = text.find(row["quote"])
        if position >= 0 and re.search(r"(?:不能|不可|无法|不建议|不适合|不要|没法|并非)$", text[:position]):
            return "CONTEXT_NEGATION_OMITTED"
    return None
