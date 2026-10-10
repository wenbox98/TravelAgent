"""Versioned, snapshot-bound selection. IDs prove location, never context or truth."""

from hashlib import sha256
import json
import re
from typing import Any

from .canonical import CanonicalBody
from .model_input import outbound_blocks

REFERENCE_VERSION = 2
EXTRACTION_VERSION = 3
PROMPT_VERSION = "reference-selection-v2"
REFERENCE_KINDS = ("AUTHOR_RECORDED_TRIP", "AUTHOR_PROPOSED_PLAN", "GUIDE_SUGGESTION", "UNKNOWN")


def catalog(view: CanonicalBody, source_id: str, content_id: str, content_hash: str,
            *, version: int = REFERENCE_VERSION) -> dict[str, Any]:
    """Filter whole blocks first; transmit each text character once, never a hidden parent."""
    if version not in {1, 2}:
        raise ValueError("REFERENCE_VERSION_UNSUPPORTED")
    binding = {"source_id": source_id, "content_id": content_id, "content_hash": content_hash,
               "normalization_version": 1, "canonical_hash": sha256(view.text.encode()).hexdigest(),
               "reference_version": version, "prompt_version": f"reference-selection-v{version}"}
    prefix = sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()[:20]
    spans = {}
    for block in outbound_blocks(view.blocks):
        # Sentence boundaries retain punctuation. Long sentences are explicitly split,
        # with parent coordinates and mandatory context review, not silently truncated.
        # v2 exposes exact clauses so a price and a play suggestion can be reviewed
        # separately. Every character is still sent once with the complete parent;
        # no redaction or rewriting. v1 remains reproducible for saved references.
        boundary_pattern = (r"[^。！？!?；;，,]+[。！？!?；;，,]*|[。！？!?；;，,]+"
                            if version == 2 else r"[^。！？!?；;]+[。！？!?；;]*|[。！？!?；;]+")
        for sentence in re.finditer(boundary_pattern, block.text):
            cursor, stop = sentence.start(), sentence.end()
            while cursor < stop:
                end = min(cursor + 120, stop)
                if end < stop:
                    boundary = max(block.text.rfind(c, cursor + 1, end) for c in ("，", ",", " "))
                    if boundary > cursor:
                        end = boundary + 1
                start_abs, end_abs = block.start + cursor, block.start + end
                identifier = f"P{prefix}-{block.block_index}-{start_abs}-{end_abs}"
                parent_start = view.text.rfind("\n", 0, block.start) + 1
                parent_end = view.text.find("\n", block.end)
                if parent_end < 0:
                    parent_end = len(view.text)
                spans[identifier] = {"span_id": identifier, "block_index": block.block_index,
                    "start": start_abs, "end": end_abs, "parent_start": parent_start, "parent_end": parent_end,
                    "context_required": bool(view.truncation_risk or start_abs != parent_start or end_abs != parent_end),
                    "locator": block.locator.rsplit(":chars:", 1)[0] + f":chars:{start_abs}-{end_abs}"}
                cursor = end
    manifest = sha256(json.dumps(spans, sort_keys=True).encode()).hexdigest()
    return {"binding": binding, "manifest_hash": manifest, "spans": spans}


def payload(directory: dict[str, Any], view: CanonicalBody) -> list[dict[str, Any]]:
    # No source/account identifiers, content IDs, title or duplicate parent text leave.
    return [{"span_id": s["span_id"], "text": view.text[s["start"]:s["end"]],
             "parent_block": s["block_index"], "context_required": s["context_required"]}
            for s in directory["spans"].values()]


def clause_context(reference: dict[str, Any], conditions: list[str]) -> list[str]:
    """Project already audited exact premises in the statement's parent only.

    Persisted conditions are a set, so reconstruct a span/text pair only where its
    character length uniquely identifies both. Ambiguity gives no subject link.
    This never reads another paragraph or changes an independent review.
    """
    if reference.get("reference_version") != 2:
        return []
    statement = reference["statement"]
    spans = reference["conditions"]
    result = []
    for span in spans:
        size = span["end"] - span["start"]
        texts = [c for c in conditions if len(c) == size]
        matching = [s for s in spans if s["end"] - s["start"] == size]
        if (len(texts) == len(matching) == 1
            and all(span[k] == statement[k] for k in ("parent_start", "parent_end"))):
            result.append((span["start"], texts[0]))
    return [text for _, text in sorted(result)]


def materialize(selection: dict[str, Any], directory: dict[str, Any], view: CanonicalBody) -> dict[str, Any]:
    ids = [selection["statement_span_id"], *selection["condition_span_ids"]]
    if any(identifier not in directory["spans"] for identifier in ids):
        raise ValueError("REFERENCE_ID_NOT_SENT")
    spans = [directory["spans"][identifier] for identifier in ids]
    for s in spans:
        b = view.blocks[s["block_index"]]
        if not b.start <= s["start"] < s["end"] <= b.end or s["end"] - s["start"] > 120:
            raise ValueError("REFERENCE_BOUNDARY_INVALID")
    quote = view.text[spans[0]["start"]:spans[0]["end"]]
    conditions = [{"text": view.text[s["start"]:s["end"]], "quote": view.text[s["start"]:s["end"]],
                   "source_block_id": s["block_index"]} for s in spans[1:]]
    blocks = sorted({s["block_index"] for s in spans})
    if len(blocks) > 8:
        raise ValueError("REFERENCE_BLOCK_LIMIT")
    return {"topic": selection["topic"], "kind": "AUTHOR_OPINION", "claim": quote, "quote": quote,
        "confidence": "MEDIUM", "applicable_conditions": conditions, "source_block_ids": blocks,
        "reference_selection": {**directory["binding"], "manifest_hash": directory["manifest_hash"],
            "statement": spans[0], "conditions": spans[1:],
            "proposed_reference_kind": selection["proposed_reference_kind"]}}


def validate_reference(row: dict[str, Any], view: CanonicalBody, source_id: str) -> None:
    ref = row["reference_selection"]
    directory = catalog(view, source_id, ref["content_id"], ref["content_hash"], version=ref["reference_version"])
    selected = {"topic": row["topic"], "statement_span_id": ref["statement"]["span_id"],
        "condition_span_ids": [s["span_id"] for s in ref["conditions"]],
        "proposed_reference_kind": ref["proposed_reference_kind"]}
    rebuilt = materialize(selected, directory, view)
    if any(row[k] != value for k, value in rebuilt.items()):
        raise ValueError("REFERENCE_MAPPING_MISMATCH")


def selection_schema(topics: list[str]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["claims"], "properties": {
        "claims": {"type": "array", "maxItems": 12, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["topic", "statement_span_id", "condition_span_ids", "proposed_reference_kind"],
            "properties": {"topic": {"enum": topics},
                "statement_span_id": {"type": "string", "minLength": 1, "maxLength": 100},
                "condition_span_ids": {"type": "array", "maxItems": 8, "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 100}},
                "proposed_reference_kind": {"enum": list(REFERENCE_KINDS)}}}}}}
