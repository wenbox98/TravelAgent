"""Program-owned advisory preferences and budget factors; no historical rewrites."""

import re
from typing import Any
from .flow_models import PlanDraft

WALK_LABELS = {"UNKNOWN": "步行意愿未定", "ALLOWED": "允许步行", "DECLINED": "明确不接受步行"}


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
    digits = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "零": 0}
    for key, unit in (("people", "(?:个)?人"), ("rooms", "间房"), ("nights", "晚")):
        match = re.search(r"(\d{1,2}|一|两|二|三|四|五|零)" + unit, request)
        if match:
            value = int(match[1]) if match[1].isdigit() else digits[match[1]]
            if value > 0 or key == "nights":
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
