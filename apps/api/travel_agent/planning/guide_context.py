"""Program-owned advisory preferences and budget factors; no historical rewrites."""

import re
from typing import Any
from .flow_models import PlanDraft

WALK_LABELS = {"UNKNOWN": "步行意愿未定", "ALLOWED": "允许步行", "DECLINED": "明确不接受步行"}

_NUMBER = r"(?:\d{1,2}|[零一二两三四五六七八九十]{1,3})"


def number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {c: i for i, c in enumerate("零一二三四五六七八九")}
    digits["两"] = 2
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value, -1)


def request_quantity(request: str, unit: str, minimum: int = 1) -> int | None:
    # A date, ordinal, alternative, bound or conflicting duration is not a trip length.
    matches = list(
        re.finditer(rf"(?<![第\d零一二两三四五六七八九十])({_NUMBER})\s*(?:{unit})", request)
    )
    matches = [
        m
        for m in matches
        if not (
            m[0].endswith("日")
            and (
                request[max(0, m.start() - 1) : m.start()] == "月"
                or re.match(r"(?:出发|到达|返程|返回|抵达|入住|退房|开始)", request[m.end() :])
            )
        )
    ]
    values = {number(m[1]) for m in matches}
    if len(values) != 1 or not minimum <= next(iter(values)) <= 90:
        return None
    for m in matches:
        prefix = request[max(0, m.start() - 8) : m.start()]
        clause = re.split(r"[，。；;,\n]", prefix)[-1]
        if re.search(
            r"第|可能|也许|大概|约|至少|最多|不超过|不止|不是|或者|或|至|到|[~～–-]$", clause
        ):
            return None
    if re.search(rf"{_NUMBER}\s*(?:或|到|至|[-~～–])\s*{_NUMBER}\s*(?:{unit})", request):
        return None
    return next(iter(values))


def walking(draft: PlanDraft, request: str = "") -> dict[str, Any]:
    value = draft.walking_allowed
    origin: str = draft.walking_origin
    if origin != "USER_EXPLICIT":
        # Only an unambiguous recorded refusal is evidence; an old unchecked box is not.
        clauses = [s.strip() for s in re.split(r"[，。；;,\n]", request)]
        if any(
            re.fullmatch(
                r"(?:我)?(?:明确)?(?:不接受步行|拒绝步行|禁止步行|不能步行|不要安排步行)", s
            )
            for s in clauses
        ):
            value, origin = False, "RECORDED_REFUSAL"
        elif value is True or draft.transport == "WALKING":
            value, origin = True, "LEGACY_ALLOW"
        else:
            value, origin = None, "UNKNOWN"
    state = "UNKNOWN" if value is None else "ALLOWED" if value else "DECLINED"
    return dict(state=state, allowed=value, origin=origin, label=WALK_LABELS[state])


def from_request(draft: PlanDraft, request: str) -> None:
    """Only explicit clauses establish consent; softer walking wishes stay unknown."""
    draft.walking_allowed = None
    draft.days = request_quantity(request, r"天|日(?!期)")
    if re.search(r"轻松|慢游|休闲|不要排(?:得)?太满|不赶(?:路|行程)", request) and not re.search(
        r"不(?:要|想)轻松|不(?:要|想)休闲", request
    ):
        draft.pace = "RELAXED"
    for key, unit in (("people", "(?:个)?人"), ("rooms", "间房"), ("nights", "晚")):
        value = request_quantity(request, unit, 0 if key == "nights" else 1)
        if value is not None:
            setattr(draft.trip_budget, key, value)
    clauses = [s.strip() for s in re.split(r"[，。；;,\n]", request)]
    refused = walking(draft, request)["state"] == "DECLINED"
    allowed = any(
        re.fullmatch(r"(?:我)?(?:明确)?(?:允许步行|接受步行|可以步行|公共交通和步行|步行)", s)
        for s in clauses
    )
    if refused or allowed:
        draft.walking_allowed = not refused
        draft.walking_origin = "USER_EXPLICIT"


def budget_context(draft: PlanDraft) -> dict[str, Any]:
    b = draft.trip_budget
    values = dict(people=b.people, days=draft.days, nights=b.nights, rooms=b.rooms)
    labels = {
        "people": ("人数", "人"),
        "days": ("天数", "天"),
        "nights": ("住宿晚数", "晚"),
        "rooms": ("房间数", "间房"),
    }
    return dict(
        **values,
        target_fen=b.target_fen,
        target_locked=b.target_locked,
        round_trip_self_arranged=draft.inputs.planning_scope == "ACTIVITY_WINDOW",
        known_conditions=[
            f"{value}{labels[key][1]}" for key, value in values.items() if value is not None
        ],
        pending_conditions=[
            labels[key][0] + "未定" for key, value in values.items() if value is None
        ],
        quantity_meaning="模型每条quantity固定1；人数、天数、房间和晚数只由程序按unit乘一次。ONCE为整条一次性预算，不再乘人数。",
    )
