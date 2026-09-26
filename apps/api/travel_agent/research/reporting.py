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
            "route_association": meta.get("route_association"),
            "published_at": bundle["source_published_at"], "travel_time": bundle["travel_occurred_at"],
            "retrieved_at": bundle["fetched_at"], "freshness": assess_freshness(claim, bundle, now=now).to_dict()}


def build_directions(evidence: tuple[EvidenceBundle, ...], *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for bundle in evidence:
        metadata = bundle.get("claim_metadata", {})
        routes = [claim for claim in bundle["claims"] if claim["topic"] == "ROUTE" and is_grounded(bundle, claim)]
        for route in routes:
            label = _direction(route["text"])
            association = metadata.get(route["claim_id"], {}).get("route_association")
            key = (bundle["source_id"], association["object_locator"] if association else
                   normalize_claim(label or route["text"]))
            item = groups.setdefault(key, {"direction": association["object_quote"] if association else label or route["text"], "route_evidence": [],
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
                claim_association = metadata.get(claim["claim_id"], {}).get("route_association")
                if not association and label and claim_label and normalize_claim(label) != normalize_claim(claim_label):
                    continue
                same_blocks = bool(unambiguous_blocks & _quote_blocks(claim, metadata.get(claim["claim_id"], {})))
                # An explicit reviewed object supersedes all proximity/label heuristics.
                linked = (bool(association and claim_association and
                              association["object_locator"] == claim_association["object_locator"])
                          if association or claim_association else same_blocks or bool(label and label in claim["text"]))
                if linked:
                    if claim["claim_id"] not in {row["claim_id"] for row in item[field]}:
                        item[field].append(_statement(bundle, claim, now))
            item["unknown"] = [description for field, description in (
                ("experiences", "尚不能把体验材料可靠关联到这个方向"),
                ("duration_clues", "这个方向尚缺可定位的时长依据"),
                ("limitations", "这个方向尚缺明确适用条件或限制依据"),
            ) if not item[field]]
            if item["duration_clues"] and all((s.get("route_association") or {}).get("scope") == "SEGMENT"
                                              for s in item["duration_clues"]):
                item["unknown"].append("只有局部时长，整趟总天数仍未知")
    return list(groups.values())


def unassociated_statements(evidence: tuple[EvidenceBundle, ...], *, now: datetime) -> list[dict[str, Any]]:
    attached = {s["claim_id"] for d in build_directions(evidence, now=now)
                for key in ("route_evidence", "experiences", "duration_clues", "limitations") for s in d[key]}
    return [_statement(b, c, now) for b in evidence for c in b["claims"]
            if c["claim_id"] not in attached and c["topic"] in {"EXPERIENCE", "DURATION", "TRANSPORT"}
            and is_grounded(b, c)]


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


def render_private_report(view: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    """Compact local report with short source references; never reproduce full bodies."""
    refs = {source["source_id"]: f"S{i}" for i, source in enumerate(sources, 1)}
    lines = ["# 国庆成都出发去川西：第一轮大致攻略", "",
             "以下方向来自本次实际读取的笔记文字，供你先比较；尚未核实国庆出行可行性，不是最终行程。"]
    constraints = view.get("request_constraints", {})
    def statement(row: dict[str, Any], label: str) -> str:
        conditions = "；".join(row["applicable_conditions"]) or "原文未明确，不能补推"
        association = row.get("route_association")
        if label == "作者的时间线索" and association:
            label = "作者当次整趟时长" if association["scope"] == "WHOLE_TRIP" else "作者局部路段或活动时长（不是总天数）"
        return (f"- {label}：作者写道“{_escape(row['text'])}”。[{refs[row['source_id']]}] "
                f"对应条件：{_escape(conditions)}。" +
                (f"旅行日期：{_escape(row['travel_time'])}。" if row.get("travel_time") else "") +
                ("这条线索的当前适用性未核实。" if row["freshness"]["status"] == "CURRENT_UNVERIFIED" else "") +
                ("当前仅有部分文字，图片未分析。" if row["content_completeness"] != "FULL_TEXT" else "图片未分析。"))
    if constraints.get("days") or constraints.get("no_self_drive"):
        known = ([f"{constraints['days']}天"] if constraints.get("days") else []) + (["不自驾"] if constraints.get("no_self_drive") else [])
        lines += ["", "你已给定：" + "、".join(known) + "。适配性尚未建立；自驾经历只提供目的地参考，不能证明公共交通可行。"]
    if len(view["directions"]) == 1:
        lines += ["", "当前只有一个有依据的方向，属于单方向参考，还未完成多方案比较。"]
    for number, direction in enumerate(view["directions"], 1):
        lines += ["", f"## 方向 {number}：{_escape(direction['direction'])}"]
        for key, label in (("route_evidence", "路线或区域"), ("experiences", "主要体验"),
                           ("duration_clues", "作者的时间线索"), ("limitations", "条件与提醒")):
            rows = direction[key]
            if not rows:
                lines.append(f"- {label}：现有文字还不能可靠说明。")
            for row in rows:
                lines.append(statement(row, label))
        count = sum(len(direction[key]) for key in ("route_evidence", "experiences", "duration_clues", "limitations"))
        lines += [f"- 当前依据：{len(direction['source_ids'])} 篇笔记、{count} 条文字证据；独立性未确认。",
                  "- 仍不确定：" + "；".join(direction["unknown"] or ["路线能否满足你的具体交通与时间条件尚未验证"]) + "。"]
    if not view["directions"]:
        lines += ["", "现有正文尚不足以提出可靠路线方向，保留缺口，不补造攻略。"]
    if view.get("unassociated_statements"):
        lines += ["", "## 可参考的局部体验与线索", "", "以下尚未可靠关联成完整路线，不能相互拼接为行程。"]
        lines += [statement(row, "局部作者材料") for row in view["unassociated_statements"]]
    unknown_preferences = [label for key, label in (("budget_cny_fen", "预算"), ("traveler_count", "人数"))
                           if constraints.get(key) is None]
    if not constraints.get("no_self_drive") and not constraints.get("transport"):
        unknown_preferences.append("交通方式")
    lines += ["", "## 当前还不确定的事", "",
              ("、".join(unknown_preferences) + "仍未知；" if unknown_preferences else "") +
              "发布时间不代表实际旅行时间，旧经验不代表今年国庆的交通、开放或预约情况。",
              "笔记中的图片没有分析；只读到部分文字的资料也不能当成完整攻略。"]
    for conflict in view["conflicts"]:
        lines.append("- 来源差异：" + _escape(conflict["reason"]))
    lines += ["- " + _escape(value) for value in dict.fromkeys(view["unknown"])]
    questions = []
    if not constraints.get("days"):
        questions.append("你大概能安排几天？建议先给出可用天数，再筛掉明显过长的作者行程。")
    if not constraints.get("no_self_drive") and not constraints.get("transport"):
        questions.append("是否考虑自驾？若不自驾，建议把公共交通或正规包车的适配性留作下一项核实。")
    if questions:
        lines += ["", "## 目前还需要你决定", ""] + [f"{i}. {q}" for i, q in enumerate(questions, 1)]
    lines += ["", "## 本次已读取来源", ""]
    for source in sources:
        description = "部分文字" if source["completeness"] != "FULL_TEXT" else "当前可访问正文"
        lines.append(f"- [{refs[source['source_id']]}] {_escape(source['source_title'] or '未提供标题')}"
                     f"；{description}；图片未分析；公开笔记标识：{_escape(source['source_id'])}。")
    return "\n".join(lines) + "\n"
