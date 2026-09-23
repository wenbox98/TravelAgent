"""Render only grounded source material into a readable provisional research report."""

from datetime import datetime, timezone
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle

from .freshness import assess_freshness
from .quality import confidence_level, is_grounded, metadata_for, normalize_claim


def _direction(text: str) -> str | None:
    match = re.match(r"^([^：:\n，。,]{1,32}?(?:方向|区域|环线|路线))", text)
    return match[1] if match else None


def _quote_blocks(claim: dict[str, Any], metadata: dict[str, Any]) -> set[int]:
    """Only blocks containing the claim span; conditions can cite other blocks."""
    locators = metadata.get("block_locators", [])
    if not locators:
        return set(metadata.get("source_block_ids", []))
    prefix, span = claim["locator"].rsplit(":chars:", 1)
    start, end = map(int, span.split("-"))
    result: set[int] = set()
    for index, locator in zip(metadata.get("source_block_ids", []), locators, strict=True):
        block_prefix, block_span = locator.rsplit(":chars:", 1)
        low, high = map(int, block_span.split("-"))
        if prefix == block_prefix and low <= start < end <= high:
            result.add(index)
    return result


def _statement(bundle: EvidenceBundle, claim: dict[str, Any], now: datetime) -> dict[str, Any]:
    meta = metadata_for(bundle, claim)
    return {"claim_id": claim["claim_id"], "text": claim["text"], "source_id": bundle["source_id"],
            "source_title": bundle["source_title"], "source_locator": claim["locator"],
            "source_block_ids": meta.get("source_block_ids", []),
            "extraction_method": meta.get("extraction_method", "LEGACY"),
            "extraction_basis": meta.get("extraction_basis", "旧记录缺少提取依据"),
            "confidence": confidence_level(bundle, claim), "kind": claim["kind"],
            "basis": "EXTRACTED_FROM_SOURCE", "content_completeness": bundle["completeness"],
            "applicable_conditions": meta.get("applicable_conditions", []),
            "published_at": bundle["source_published_at"], "travel_time": bundle["travel_occurred_at"],
            "retrieved_at": bundle["fetched_at"], "freshness": assess_freshness(claim, bundle, now=now).to_dict()}


def build_directions(evidence: tuple[EvidenceBundle, ...], *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    groups: dict[str, dict[str, Any]] = {}
    for bundle in evidence:
        metadata = bundle.get("claim_metadata", {})
        routes = [claim for claim in bundle["claims"] if claim["topic"] == "ROUTE" and is_grounded(bundle, claim)]
        for route in routes:
            label = _direction(route["text"])
            key = normalize_claim(label or route["text"])
            item = groups.setdefault(key, {"direction": label or route["text"], "route_evidence": [],
                                            "experiences": [], "duration_clues": [], "limitations": [],
                                            "source_ids": [], "unknown": []})
            item["route_evidence"].append(_statement(bundle, route, now))
            if bundle["source_id"] not in item["source_ids"]:
                item["source_ids"].append(bundle["source_id"])
            route_blocks = _quote_blocks(route, metadata.get(route["claim_id"], {}))
            # A shared paragraph can describe several alternatives. Its co-location
            # alone must not attach every experience to every route in that paragraph.
            unambiguous_blocks = {block for block in route_blocks if sum(
                block in _quote_blocks(other, metadata.get(other["claim_id"], {}))
                for other in routes
            ) == 1}
            for claim in bundle["claims"]:
                field = {"EXPERIENCE": "experiences", "DURATION": "duration_clues",
                         "TRANSPORT": "limitations", "TRADEOFF": "limitations", "SEASON": "limitations"}.get(claim["topic"])
                if not field or not is_grounded(bundle, claim):
                    continue
                claim_label = _direction(claim["text"])
                if label and claim_label and normalize_claim(label) != normalize_claim(claim_label):
                    continue
                same_blocks = bool(unambiguous_blocks & _quote_blocks(claim, metadata.get(claim["claim_id"], {})))
                if same_blocks or label and label in claim["text"]:
                    if claim["claim_id"] not in {row["claim_id"] for row in item[field]}:
                        item[field].append(_statement(bundle, claim, now))
            item["unknown"] = [description for field, description in (
                ("experiences", "尚不能把体验材料可靠关联到这个方向"),
                ("duration_clues", "这个方向尚缺可定位的时长依据"),
                ("limitations", "这个方向尚缺明确适用条件或限制依据"),
            ) if not item[field]]
    return list(groups.values())


def _escape(text: object) -> str:
    return re.sub(r"([\\`*_{}\[\]()<>#!|])", r"\\\1", str(text).replace("\n", " "))


def render_material_report(view: dict[str, Any]) -> str:
    """Human-facing content only; callers must apply SourcePolicy before exporting."""
    lines = ["# 大致攻略研究结果", "", "这是来源材料支持的候选方向，不是最终详细行程。"]
    if view.get("is_synthetic"):
        lines += ["", "**合成 benchmark 演示：以下地名和路线不是实际川西旅行建议。**"]
    for ordinal, direction in enumerate(view["directions"], 1):
        lines += ["", f"## 方向 {ordinal}：{_escape(direction['direction'])}"]
        for key, label in (("route_evidence", "区域或路线依据"), ("experiences", "体验"),
                           ("duration_clues", "时间线索"), ("limitations", "限制与条件")):
            for statement in direction[key]:
                lines += ["", f"- {label}：{_escape(statement['text'])}（作者材料，{statement['confidence']}；"
                          f"{statement['content_completeness']}；{statement['freshness']['status']}）",
                          f"  来源：{_escape(statement['source_id'])}；证据：{_escape(statement['claim_id'])}；"
                          f"正文块：{statement['source_block_ids']}；定位：{_escape(statement['source_locator'])}",
                          f"  提取：{statement['extraction_method']}；依据：{_escape(statement['extraction_basis'])}",
                          f"  适用条件：{_escape('；'.join(statement['applicable_conditions']) or '原文未明确，仍待确认')}；"
                          f"旅行时间：{_escape(statement['travel_time'] or '未知')}；"
                          f"发布时间：{_escape(statement['published_at'] or '未知')}；"
                          f"采集时间：{_escape(statement['retrieved_at'])}。"]
        lines += ["", f"来源笔记数：{len(direction['source_ids'])}；来源独立性未确认。"]
        lines += [f"- 未知：{_escape(gap)}" for gap in direction["unknown"]]
    if not view["directions"]:
        lines += ["", "现有材料不足以形成有来源依据的候选方向，不补造方案。"]
    lines += ["", "## 研究覆盖与差异"]
    for row in view["coverage"]:
        lines.append(f"- {row['question_id']}：{row['status']}")
    for conflict in view["conflicts"]:
        lines.append(f"- 来源差异：{_escape(conflict['reason'])}；证据 {', '.join(conflict['claim_ids'])}")
    lines += ["", "## 尚缺信息"]
    lines += [f"- {_escape(gap)}" for gap in view["unknown"]]
    lines += ["", "是否自驾、实际可用天数可以继续补充；预算和人数未知不妨碍先看方向。",
              f"停止原因：{view['stop_reason']}；搜索 {view['operations']['search']} 次，"
              f"详情 {view['operations']['detail']} 次。"]
    return "\n".join(lines) + "\n"
