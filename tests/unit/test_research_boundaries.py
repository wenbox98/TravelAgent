"""Local lifecycle and report associations, with no external source access."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from travel_agent.research.ephemeral import EphemeralSourceContent
from travel_agent.research.quality import evidence_conflicts
from travel_agent.research.reporting import build_directions


def source(sid, rows):
    return {"source_id": sid, "source_title": "合成来源", "completeness": "PARTIAL_TEXT",
            "source_published_at": None, "travel_occurred_at": None,
            "fetched_at": "2026-09-24T00:00:00Z", "claims": [
                {"claim_id": cid, "topic": topic, "text": text, "kind": "AUTHOR_OPINION",
                 "support": "PARTIAL", "locator": "note-body:v1:" + "a" * 64 + ":chars:0-12"}
                for cid, topic, text in rows], "claim_metadata": {
                    cid: {"source_block_ids": [0], "extraction_method": "MOCK",
                          "extraction_basis": "合成定位", "confidence_level": "MEDIUM"}
                    for cid, _, _ in rows}}


def test_ephemeral_raw_content_is_private_and_expires_on_read():
    clock = [0.0]
    content = EphemeralSourceContent("synthetic raw", "synthetic DOM", ttl_seconds=2,
                                     clock=lambda: clock[0])
    assert "synthetic" not in repr(content)
    assert content.read() == ("synthetic raw", "synthetic DOM")
    clock[0] = 2
    with pytest.raises(ValueError, match="过期"):
        content.read()
    assert content._state == "" and content._dom is None


def test_ephemeral_close_ends_use_without_waiting_for_ttl():
    content = EphemeralSourceContent("synthetic raw")
    content.close()
    content.close()
    with pytest.raises(ValueError):
        content.read()
    with pytest.raises(ValueError):
        EphemeralSourceContent("body", ttl_seconds=301)


def test_multiple_routes_in_same_block_do_not_borrow_unattributed_experience():
    data = source("a", [("a1", "ROUTE", "甲方向：甲谷"), ("a2", "ROUTE", "乙方向：乙湖"),
                        ("a3", "EXPERIENCE", "这里有徒步体验"),
                        ("a4", "DURATION", "甲方向用了五天")])
    results = build_directions((data,), now=datetime(2026, 9, 24, tzinfo=timezone.utc))
    assert len(results) == 2
    assert all(not row["experiences"] for row in results)
    assert results[0]["duration_clues"][0]["claim_id"] == "a4"
    assert results[1]["duration_clues"] == []


def test_different_explicit_routes_are_not_a_duration_contradiction():
    first = source("a", [("a1", "DURATION", "甲环线五天很宽松")])
    second = source("b", [("b1", "DURATION", "乙环线五天很赶")])
    assert evidence_conflicts((first, second)) == ()
    second = deepcopy(second)
    second["claims"][0]["text"] = "甲环线五天不宽松"
    assert len(evidence_conflicts((first, second))) == 1
    first["claims"][0]["text"] = "甲环线五天很赶"
    assert evidence_conflicts((first, second)) == ()
