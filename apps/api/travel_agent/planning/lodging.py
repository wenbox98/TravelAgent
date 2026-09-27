"""Lodging scope is independent of an unknown monetary amount."""

from typing import Any
from .flow_models import PlanDraft
from .guide_models import BudgetLine, TripBudget

VERSION = "lodging-scope-1"


def context(draft: PlanDraft) -> dict[str, Any]:
    b = draft.trip_budget
    protected = any(
        v.category == "LODGING"
        and (
            v.paid_fen
            or v.locked
            or v.basis in {"USER_BUDGET_TARGET", "OBSERVED_QUOTE", "HISTORICAL_REFERENCE"}
        )
        for v in b.lines
    )
    if protected:
        state, origin, reason = (
            "IN_SCOPE",
            "PROTECTED_COST",
            "保留已有用户、已付、锁定或有引用的住宿费用；不由模型覆盖。",
        )
    elif b.lodging_scope == "EXCLUDE":
        state, origin, reason = (
            "OUT_OF_SCOPE",
            "USER_CHOICE",
            "本次明确不纳入住宿；已填晚数保留，不表示酒店免费。",
        )
    elif b.nights is not None and b.nights > 0:
        state, origin, reason = (
            "IN_SCOPE",
            "CONFIRMED_NIGHTS",
            "本次已填写住宿晚数，住宿纳入草案；金额仍可未知。",
        )
    elif b.lodging_scope == "INCLUDE":
        state, origin, reason = (
            "IN_SCOPE",
            "USER_CHOICE",
            "本次选择考虑住宿，晚数与金额可以继续待定。",
        )
    elif b.nights == 0:
        state, origin, reason = (
            "OUT_OF_SCOPE",
            "USER_CHOICE",
            "本次明确不纳入住宿；不表示酒店免费。",
        )
    elif draft.days == 1:
        state, origin, reason = (
            "OUT_OF_SCOPE",
            "PRODUCT_DEFAULT",
            "本草案暂不安排住宿（可修改的产品缺省），不表示你已确认不住酒店，也不是免费。",
        )
    else:
        state, origin, reason = (
            "UNDECIDED",
            "UNKNOWN",
            "住宿是否纳入、位置和费用仍待决定；未知不按零计算。",
        )
    return dict(state=state, origin=origin, reason=reason, rule=VERSION)


def from_payload(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("lodging_context"):
        return dict(data["lodging_context"])
    # Old immutable v4 inputs supply enough information for this conservative default.
    return context(
        PlanDraft(
            days=data.get("days"),
            trip_budget=TripBudget.model_validate(
                {k: data["budget_context"].get(k) for k in ("people", "nights", "rooms")}
            ),
        )
    )


def empty(line: BudgetLine) -> bool:
    return (
        line.unit_amount.min_fen is None
        and line.unit_amount.max_fen is None
        and line.status == "UNKNOWN"
        and line.basis in {"UNKNOWN", "NOT_APPLICABLE"}
        and not (
            line.paid_fen
            or line.locked
            or line.quote_id
            or line.queried_at
            or line.included_in_line_id
        )
    )


def project_line(line: BudgetLine, decision: dict[str, Any]) -> BudgetLine:
    out = line.model_copy(deep=True)
    if out.category != "LODGING":
        return out
    if (
        out.paid_fen
        or out.locked
        or out.basis in {"USER_BUDGET_TARGET", "OBSERVED_QUOTE", "HISTORICAL_REFERENCE"}
    ):
        out.inclusion = "IN_SCOPE"
        out.inclusion_origin = "PROGRAM_CONTEXT"
        return out
    if decision["state"] == "OUT_OF_SCOPE" and empty(out):
        out.inclusion = "OUT_OF_SCOPE"
        out.inclusion_origin = out.inclusion_origin or "PROGRAM_CONTEXT"
    elif decision["state"] != "OUT_OF_SCOPE":
        out.inclusion = decision["state"]
        out.inclusion_origin = "PROGRAM_CONTEXT"
        if empty(out) and out.basis == "NOT_APPLICABLE":
            out.basis = "UNKNOWN"
    return out
