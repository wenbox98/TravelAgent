"""Deterministic travel spending, separate from MapBudget and operation grants."""

from typing import Any
from .guide_models import BudgetLine, TripBudget

BASIS = {
    "USER_BUDGET_TARGET": "用户预算目标",
    "AI_BUDGET_PROPOSAL": "AI计划预留（非市场价）",
    "HISTORICAL_REFERENCE": "历史参考（非当前报价）",
    "OBSERVED_QUOTE": "有条件的已取得报价",
    "UNKNOWN": "未知",
    "NOT_APPLICABLE": "不适用",
    "EXCLUDED_SELF_ARRANGED": "自行安排，不计入",
}
CATEGORY = {
    "TRANSPORT": "交通",
    "LODGING": "住宿",
    "FOOD": "餐饮",
    "ACTIVITY": "门票/活动",
    "RESERVE": "可选预留",
    "DEPOSIT": "订金",
    "OTHER": "其他",
}
UNITS = {
    "ONCE": "一次性",
    "PER_PERSON": "每人",
    "PER_PERSON_DAY": "每人每天",
    "PER_ROOM_NIGHT": "每间每晚",
    "PER_DAY": "每天",
}


def amount(lo: int | None, hi: int | None) -> dict[str, Any]:
    return dict(min_fen=lo, max_fen=hi, currency="CNY")


def calculate(budget: TripBudget, selected: list[str]) -> dict[str, Any]:
    rows, unknown, excluded = [], [], []
    low = high = paid = 0
    per_low = per_high = 0
    known_count = per_count = 0
    for line in budget.lines:
        value = line.model_dump()
        value.update(
            basis_label=BASIS[line.basis],
            unit_label=UNITS[line.unit],
            category_label=CATEGORY[line.category],
        )
        reason = None
        active = set(line.activity_ids) & set(selected)
        if line.basis in {"NOT_APPLICABLE", "EXCLUDED_SELF_ARRANGED"}:
            reason = BASIS[line.basis]
        elif line.optional and not line.include_optional and not line.paid_fen and not line.locked:
            reason = "备选未纳入"
        elif line.activity_ids and not active and not line.paid_fen and not line.locked:
            reason = "对应活动未选择"
        elif line.included_in_line_id:
            reason = "已包含于另一明细，避免双计"
        if reason:
            value.update(total=amount(None, None), counting="EXCLUDED", note=reason)
            rows.append(value)
            excluded.append(line.line_id)
            continue
        count: int | None = line.quantity
        factors: tuple[int | None, ...] = {
            "ONCE": (),
            "PER_PERSON": (budget.people,),
            "PER_PERSON_DAY": (budget.people, budget.days),
            "PER_ROOM_NIGHT": (budget.rooms, budget.nights),
            "PER_DAY": (budget.days,),
        }[line.unit]
        for factor in factors:
            count = count * factor if count is not None and factor is not None else None
        partial_bundle = bool(active) and active != set(line.activity_ids)
        known = line.unit_amount.min_fen is not None and count is not None and not partial_bundle
        lo: int | None
        hi: int | None
        if known:
            assert (
                line.unit_amount.min_fen is not None
                and line.unit_amount.max_fen is not None
                and count is not None
            )
            lo, hi = line.unit_amount.min_fen * count, line.unit_amount.max_fen * count
            low += lo
            high += hi
            known_count += 1
        else:
            lo = hi = None
            unknown.append(line.line_id)
        if (
            line.unit.startswith("PER_PERSON")
            and line.unit_amount.min_fen is not None
            and not partial_bundle
        ):
            units = line.quantity * (budget.days or 1)
            if line.unit == "PER_PERSON":
                units = line.quantity
            if line.unit == "PER_PERSON" or budget.days is not None:
                per_low += units * line.unit_amount.min_fen
                per_high += units * (line.unit_amount.max_fen or 0)
                per_count += 1
        paid += line.paid_fen
        value.update(
            total=amount(lo, hi),
            counting="INCLUDED" if known else "UNKNOWN",
            note="组合已变，原合计不能拆分"
            if partial_bundle
            else "人数/天数/房间/晚数或金额仍未知"
            if not known
            else "已付包含在本明细中，不再加一次"
            if line.paid_fen
            else "仅计入当前选择",
        )
        rows.append(value)
    missing = []
    present = {(v.category, v.transport_scope) for v in budget.lines}
    for category, kind, label in [
        ("TRANSPORT", "ROUND_TRIP", "往返交通"),
        ("TRANSPORT", "LOCAL", "当地移动"),
        ("LODGING", None, "住宿"),
        ("FOOD", None, "餐饮"),
        ("ACTIVITY", None, "门票/活动"),
        ("RESERVE", None, "可选预留"),
    ]:
        if (category, kind) not in present:
            missing.append(label)
    target_note = None
    if budget.target_fen is not None and known_count and high > budget.target_fen:
        target_note = (
            "已计入部分的上界超过用户硬预算，请核对并调整；未自动删项目"
            if budget.target_locked
            else "可能超过预算目标，可减少可选项；未自动删项目"
        )
    return dict(
        known_total=amount(low if known_count else None, high if known_count else None),
        per_person=amount(per_low, per_high) if per_count else None,
        per_person_meaning="仅每人项目，不平摊房间总价",
        lines=rows,
        unknown_line_ids=unknown,
        excluded_line_ids=excluded,
        missing_categories=missing,
        completeness="PARTIAL" if unknown or missing else "COMPLETE",
        paid_fen=paid,
        remaining_fen=amount(max(0, low - paid), max(0, high - paid))
        if known_count and not unknown
        else amount(None, None),
        target_note=target_note,
        meaning="已计入部分的预算草案区间；不是全程报价",
        is_synthetic=any(v.is_synthetic for v in budget.lines),
    )


def defaults(days: int | None, self_arranged: bool) -> list[BudgetLine]:
    return [
        BudgetLine(
            line_id="round-trip",
            label="往返交通",
            category="TRANSPORT",
            transport_scope="ROUND_TRIP",
            basis="EXCLUDED_SELF_ARRANGED" if self_arranged else "UNKNOWN",
        ),
        BudgetLine(
            line_id="local", label="当地移动", category="TRANSPORT", transport_scope="LOCAL"
        ),
        BudgetLine(
            line_id="lodging",
            label="住宿",
            category="LODGING",
            unit="PER_ROOM_NIGHT",
            basis="NOT_APPLICABLE" if days == 1 else "UNKNOWN",
        ),
        BudgetLine(line_id="food", label="餐饮", category="FOOD", unit="PER_PERSON_DAY"),
        BudgetLine(line_id="activities", label="门票/活动", category="ACTIVITY"),
        BudgetLine(line_id="reserve", label="可选预留", category="RESERVE", optional=True),
    ]


def preserve_edits(before: TripBudget, after: TripBudget) -> TripBudget:
    """Only the model path may introduce an AI target; users cannot forge quotes."""
    old = {v.line_id: v for v in before.lines}
    new = {v.line_id: v for v in after.lines}
    for v in before.lines:
        if (v.locked or v.paid_fen) and (v.line_id not in new or new[v.line_id] != v):
            raise ValueError("BUDGET_LOCKED_LINE")
    for v in after.lines:
        if old.get(v.line_id) == v:
            continue
        if v.basis in {"OBSERVED_QUOTE", "HISTORICAL_REFERENCE"} or v.quote_id:
            raise ValueError("BUDGET_REFERENCE_UNAVAILABLE")
        if v.basis == "AI_BUDGET_PROPOSAL":
            v.basis = "USER_BUDGET_TARGET"
    return after
