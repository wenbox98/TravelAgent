"""Outbound minimization fakes; no external model or real personal information."""

import pytest

from travel_agent.domain.source_policy import private_policy
from travel_agent.research.canonical import canonicalize
from travel_agent.research.extractor import EvidenceExtractor
from travel_agent.research.model_input import outbound_blocks


@pytest.mark.parametrize("sensitive", ["联系 synthetic@example.invalid", "手机号：138 0000 0000",
    "微信：synthetic_contact", "https://example.invalid/note", "身份证：110101199001010011",
    "我家地址：虚构门牌", "vx: synthetic_id"])
def test_omit_sensitive_blocks_preserves_original_indexes_and_offsets(sensitive):
    view = canonicalize("合成路线经过虚构湖泊。\n" + sensitive + "\n合成路线需要五天。")
    kept = outbound_blocks(view.blocks)
    assert [b.block_index for b in kept] == [0, 2]
    assert all(view.text[b.start:b.end] == b.text for b in kept)


def test_outbound_text_is_bounded_without_partial_block_quotes():
    view = canonicalize("\n".join(["合成" * 200] * 20))
    kept = outbound_blocks(view.blocks)
    assert sum(len(b.normalized_text) for b in kept) <= 6000
    assert len(kept) < len(view.blocks)


def test_model_cannot_cite_a_block_that_was_not_sent(clock):
    class Fake:
        is_external = True
        is_mock = False
        def structured(self, task, payload, schema):
            assert [b["block_index"] for b in payload["blocks"]] == [0]
            text = "合成路线需要五天。"
            return {"claims": [{"topic": "OTHER", "kind": "AUTHOR_OPINION", "claim": text,
                                "quote": text, "source_block_ids": [1], "confidence": "LOW",
                                "applicable_conditions": [], "extraction_basis": "猜测"}]}
    result = EvidenceExtractor(Fake(), clock=clock).extract(
        source_id="xhs:synthetic", source_title=None, body="合成路线经过虚构湖泊。\n微信：synthetic_contact 合成路线需要五天。",
        completeness="PARTIAL_TEXT", fetched_at=clock().isoformat(), policy=private_policy("owner", now=clock()))
    assert result.mode == "LLM" and result.rejected_claims == 1 and not result.bundle["claims"]
    assert "MODEL_INPUT_MINIMIZED" in result.gaps
    assert result.candidate_checks[0]["reason_code"] == "UNSENT_BLOCK_REFERENCED"
