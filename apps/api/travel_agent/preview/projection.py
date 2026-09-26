"""Deterministic, conservative projection of already reviewed Evidence."""
from hashlib import sha256
import json
import re
from typing import Any

from travel_agent.domain.models import EvidenceBundle
from travel_agent.domain.source_policy import SENSITIVE_RESEARCH_TEXT
from travel_agent.research.quality import normalize_claim
from travel_agent.research.reporting import build_directions, unassociated_statements

EMPTY = "本次预览未启用新资料研究；当前没有足够本地材料"
BASE_GAPS = ["核实从出发地到返回终点的门到门总时间。", "补足各路段移动、活动停留与休息时间。",
             "核实当前道路、开放、预约及季节适用性；历史文字与图片未分析部分不能作保证。"]
_PRIVATE = re.compile(r"https?://|[A-Za-z]:[\\/]|sk-[A-Za-z0-9_-]{12,}|\b1[3-9]\d{9}\b", re.I)
_DAY = re.compile(r"^\W*Day\s*(\d{1,2})(?!\d)", re.I)


def safe_text(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str) or len(value) > limit or SENSITIVE_RESEARCH_TEXT.search(value) or _PRIVATE.search(value):
        raise ValueError("UNSAFE_PREVIEW_TEXT")
    return value


def fingerprint(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_schedule(rows: list[dict[str, Any]]) -> dict[str, Any]:
    entries = []
    for row in rows:
        match = _DAY.match(row["text"])
        if match:
            entries.append({"day": int(match[1]), "text": row["text"], "evidence_ids": [row["claim_id"]]})
    numbers = [row["day"] for row in entries]
    continuous = bool(len(numbers) > 1 and sorted(numbers) == list(range(1, len(numbers) + 1)))
    return {"entries": entries, "day_count": len(numbers) if continuous else None,
            "basis": "DERIVED_FROM_SOURCE_SCHEDULE" if continuous else "INCOMPLETE_OR_AMBIGUOUS",
            "meaning": "仅为同一已审核对象的来源日序，不是用户所需天数或实测耗时。"}


def parse_preferences(text: str) -> tuple[dict[str, Any], str | None]:
    """Small advertised grammar. Ambiguity leaves *all* inferred changes unapplied."""
    values: dict[str, Any] = {}
    if not text:
        return values, None
    day_hits = re.findall(r"(\d{1,2}|[一二三四五六七八九十两])天", text)
    digits = {word: number for number, word in enumerate("零一二三四五六七八九十")}
    digits["两"] = 2
    days = {int(hit) if hit.isdigit() else digits[hit] for hit in day_hits}
    driving_no = bool(re.search(r"不想(?:自己)?(?:开车|自驾)|不自驾|不愿(?:自己)?开车", text))
    driving_yes = bool(re.search(r"(?<!不)愿意(?:自己)?(?:开车|自驾)|(?<!不)想自驾", text))
    if (len(days) > 1 or (driving_yes and driving_no) or
        re.search(r"不是|不一定|可能|也许|或者|大概|不超过|至少|最多|不止|除了", text) or
        (day_hits and re.search(r"不.{0,3}(?:\d|[一二三四五六七八九十])天", text))):
        return {}, "这句话有不确定或冲突条件，请用下方选项确认可用天数和驾驶意愿；也可保留未知。"
    if days and next(iter(days)) > 0:
        values["days"] = next(iter(days))
    if driving_no or driving_yes:
        values["driving"] = "NO" if driving_no else "YES"
    if "国庆" in text:
        values["time_hint"] = "国庆"
    return values, None


def gaps(preferences: dict[str, Any], option: dict[str, Any] | None = None) -> list[str]:
    result = list(BASE_GAPS)
    if preferences.get("days"):
        result.append(f"核实 {preferences['days']} 天能覆盖哪些兴趣点；来源日序不能直接删减为可执行路线，适配待核实／需重新编排。")
    if preferences.get("driving") == "NO":
        result.append("核实不自己开车时的路段交通与当地接驳。现有自驾资料既不能证明公共交通可行，也不能证明无法前往；是否接受包车仍未知。")
    if option:
        result += option["unknown"]
    return list(dict.fromkeys(result))


def questions(preferences: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    answered = preferences.get("answered", [])
    if preferences.get("days") is None and "days" not in answered:
        result.append({"field": "days", "title": "大概能安排几天？", "advice": "建议先确定可用天数，再核实范围；现有草案尚未证明恰好适配。", "choices": ["3天", "5天", "7天", "自定义", "暂不确定"]})
    if preferences.get("driving") == "UNKNOWN" and "driving" not in answered:
        result.append({"field": "driving", "title": "愿意自己开车吗？", "advice": "先表达驾驶意愿即可；不想开车不等于只接受公共交通，其他方式仍待核实。", "choices": ["愿意", "不想开", "暂不确定"]})
    return result


def project(evidence: tuple[EvidenceBundle, ...], *, scope: str, research_id: str, now: Any) -> dict[str, Any]:
    """Reuse reviewed object grouping. Never assemble separate day objects into a trip."""
    by_id = {c["claim_id"]: (b, c, b["claim_metadata"][c["claim_id"]]) for b in evidence for c in b["claims"]}

    def statement(row: dict[str, Any]) -> dict[str, Any]:
        bundle, claim, meta = by_id[row["claim_id"]]
        reference = meta.get("reference_selection") or {}
        return {"claim_id": claim["claim_id"], "source_id": bundle["source_id"],
                "source_title": safe_text(bundle["source_title"] or "未提供标题"),
                "text": safe_text(claim["text"]), "topic": claim["topic"], "locator": claim["locator"],
                "reference_kind": meta.get("reference_scope", "UNKNOWN"),
                "duration_scope": meta.get("duration_scope"),
                "conditions": [safe_text(c) for c in meta["applicable_conditions"]],
                "block_locators": meta["block_locators"],
                "span_ids": [s["span_id"] for s in ([reference["statement"]] + reference["conditions"])] if reference else [],
                "completeness": bundle["completeness"], "review_status": meta["context_review_status"],
                "travel_time": bundle["travel_occurred_at"], "retrieved_at": bundle["fetched_at"],
                "source_url": "https://www.xiaohongshu.com/explore/" + bundle["source_id"][4:]
                    if re.fullmatch(r"xhs:[a-f0-9]{24}", bundle["source_id"]) else None}

    options: list[dict[str, Any]] = []
    def conditions(rows: dict[str, Any], pattern: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[str]] = {}
        for row in rows.values():
            for condition in row["conditions"]:
                if re.search(pattern, condition, re.I):
                    grouped.setdefault(condition, []).append(row["claim_id"])
        return [{"text": text, "evidence_ids": sorted(set(ids))} for text, ids in grouped.items()]

    for direction in build_directions(evidence, now=now):
        field_names = ("route_evidence", "experiences", "duration_clues", "limitations")
        rows = {row["claim_id"]: statement(row) for key in field_names for row in direction[key]}
        ids = sorted(rows)
        routes = [rows[row["claim_id"]] for row in direction["route_evidence"]]
        # Identical same-source quotes count once for schedule derivation, all IDs stay in lineage.
        unique_routes = list({(r["source_id"], r["locator"], r["text"]): r for r in reversed(routes)}.values())[::-1]
        options.append({"option_id": "option-" + fingerprint([scope, research_id, direction["direction"], ids])[:24],
            "label": safe_text(direction["direction"]), "label_evidence_ids": [r["claim_id"] for r in routes],
            "reference_kinds": sorted({r["reference_kind"] for r in rows.values()}),
            "source_count": len(direction["source_ids"]), "independent_source_count": None,
            "opinion_count": len({(r["source_id"], r["topic"], normalize_claim(r["text"])) for r in rows.values()}),
            "evidence": list(rows.values()), "route_evidence_ids": [r["claim_id"] for r in routes],
            "experience_evidence_ids": [r["claim_id"] for r in direction["experiences"]],
            "source_transport_conditions": conditions(rows, r"自驾|电车|开车|步行|徒步|公交|班车|包车|油车|铁路"),
            "source_time_conditions": conditions(rows, r"月|季|国庆|Day\s*\d|\d[./]\d"),
            "source_schedule": source_schedule(unique_routes), "verified_duration_days": None,
            "cost_cny_fen": None, "feasibility": "UNVERIFIED",
            "unknown": list(dict.fromkeys(direction["unknown"] + ["这只是来源内已关联草案／日段；不代表完整可行路线。", "图片未分析，当前交通与季节适用性未核实。"]))})
    options.sort(key=lambda option: option["source_schedule"]["day_count"] is None)
    return {"options": options, "other_clues": [statement(row) for row in unassociated_statements(evidence, now=now)],
            "evidence_count": len(by_id), "source_count": len(evidence)}
