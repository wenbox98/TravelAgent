"""One conservative body view; hashes and offsets refer to that exact text version."""

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import re
from typing import Literal
import unicodedata

BodyOrigin = Literal["STATE", "DOM", "UNKNOWN"]
CanonicalRelation = Literal[
    "EQUAL", "STATE_CONTAINS_DOM", "DOM_CONTAINS_STATE", "OVERLAP", "CONFLICT",
    "STATE_ONLY", "DOM_ONLY", "NONE",
]


def normalize_body(text: str | None) -> str:
    value = unicodedata.normalize("NFC", text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line for raw in value.split("\n")
                     if (line := re.sub(r"[^\S\n]+", " ", raw).strip()))


@dataclass(frozen=True, repr=False)
class BodyBlock:
    block_index: int
    text: str
    start: int
    end: int
    locator: str
    origin: BodyOrigin = "UNKNOWN"
    truncation_risk: bool = True

    @property
    def normalized_text(self) -> str:
        return normalize_body(self.text)


def body_blocks(
    body: str | None, *, origin: BodyOrigin = "UNKNOWN", truncation_risk: bool = True,
    normalized: bool = False,
) -> tuple[BodyBlock, ...]:
    """Legacy direct calls retain raw offsets; canonical calls use versioned normalized offsets."""
    if not body:
        return ()
    digest = sha256(body.encode("utf-8", errors="surrogatepass")).hexdigest()
    prefix = f"note-body:v2:{origin}:{digest}" if normalized else f"note-body:v1:{digest}"
    result: list[BodyBlock] = []
    for match in re.finditer(r"[^\r\n]+", body):
        start = match.start() + len(match.group()) - len(match.group().lstrip())
        end = match.end() - len(match.group()) + len(match.group().rstrip())
        for offset in range(start, end, 700):
            finish = min(offset + 700, end)
            result.append(BodyBlock(len(result), body[offset:finish], offset, finish,
                                    f"{prefix}:chars:{offset}-{finish}", origin, truncation_risk))
    return tuple(result)


@dataclass(frozen=True, repr=False)
class CanonicalBody:
    text: str
    origin: BodyOrigin
    relation: CanonicalRelation
    truncation_risk: bool
    completeness: str
    blocks: tuple[BodyBlock, ...]

    def safe_summary(self) -> dict[str, object]:
        return {"body_origin": self.origin, "canonical_relation": self.relation,
                "truncation_risk": self.truncation_risk, "completeness": self.completeness,
                "body_chars": len(self.text), "block_count": len(self.blocks)}


def canonicalize(
    state_body: str | None, dom_body: str | None = None, *, completeness: str = "PARTIAL_TEXT",
) -> CanonicalBody:
    state, dom = normalize_body(state_body), normalize_body(dom_body)
    origin: BodyOrigin = "STATE" if state else "DOM" if dom else "UNKNOWN"
    chosen = state or dom
    if not state and not dom:
        relation: CanonicalRelation = "NONE"
    elif not dom:
        relation = "STATE_ONLY"
    elif not state:
        relation = "DOM_ONLY"
    elif state == dom:
        relation = "EQUAL"
    elif dom in state:
        relation = "STATE_CONTAINS_DOM"
    elif state in dom:
        relation, chosen, origin = "DOM_CONTAINS_STATE", dom, "DOM"
    else:
        # Overlap describes text similarity only, never agreement about travel facts.
        relation = "OVERLAP" if SequenceMatcher(None, state, dom, autojunk=False).ratio() >= 0.35 else "CONFLICT"
    uncertain = relation not in {"EQUAL", "STATE_ONLY"}
    result_completeness = "PARTIAL_TEXT" if completeness == "FULL_TEXT" and uncertain else completeness
    risk = result_completeness != "FULL_TEXT" or uncertain
    return CanonicalBody(chosen, origin, relation, risk, result_completeness,
                         body_blocks(chosen, origin=origin, truncation_risk=risk, normalized=True))


_DIGITS = {char: str(i) for i, char in enumerate("零一二三四五六七八九")}
_DIGITS["两"] = "2"


def _number(match: re.Match[str]) -> str:
    value = match.group()
    if "十" in value:
        tens, units = value.split("十", 1)
        return str(int(_DIGITS.get(tens, "1")) * 10 + int(_DIGITS.get(units, "0")))
    return "".join(_DIGITS.get(char, char) for char in value)


def evidence_key(text: str) -> str:
    """Within-source near duplicate key; preserves negatives, quantities and opinions."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"[零一二三四五六七八九十两]+(?=\s*(?:天|日|小时|分钟|公里|元))", _number, value)
    return re.sub(r"[\s，,。.!！?？;；:：]+", "", value)
