"""Advisory guide and the existing AmountRange/BudgetLine monetary concepts.

Amounts are integer fen; targets are never observations or supplier quotes.
"""

from typing import Literal
from pydantic import Field, model_validator, field_validator
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import safe_text


class AmountRange(StrictModel):
    min_fen: int | None = Field(default=None, ge=0, le=100_000_000)
    max_fen: int | None = Field(default=None, ge=0, le=100_000_000)
    currency: Literal["CNY"] = "CNY"

    @model_validator(mode="after")
    def ordered(self) -> "AmountRange":
        if (self.min_fen is None) != (self.max_fen is None) or (
            self.min_fen is not None and self.max_fen is not None and self.min_fen > self.max_fen
        ):
            raise ValueError("INVALID_AMOUNT_RANGE")
        return self


class BudgetLine(StrictModel):
    inclusion: Literal["AUTO", "IN_SCOPE", "OUT_OF_SCOPE", "UNDECIDED"] = "AUTO"
    inclusion_origin: Literal["PROGRAM_CONTEXT", "NORMALIZED"] | None = None
    line_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    label: str = Field(min_length=1, max_length=100)
    category: Literal["TRANSPORT", "LODGING", "FOOD", "ACTIVITY", "RESERVE", "DEPOSIT", "OTHER"]
    transport_scope: Literal["ROUND_TRIP", "LOCAL"] | None = None
    unit: Literal["ONCE", "PER_PERSON", "PER_PERSON_DAY", "PER_ROOM_NIGHT", "PER_DAY"] = "ONCE"
    quantity: int = Field(default=1, ge=1, le=100)
    unit_amount: AmountRange = Field(default_factory=AmountRange)
    status: Literal["QUOTED", "ESTIMATED", "HISTORICAL", "PAID", "UNKNOWN"] = "UNKNOWN"
    basis: Literal[
        "USER_BUDGET_TARGET",
        "AI_BUDGET_PROPOSAL",
        "HISTORICAL_REFERENCE",
        "OBSERVED_QUOTE",
        "UNKNOWN",
        "NOT_APPLICABLE",
        "EXCLUDED_SELF_ARRANGED",
    ] = "UNKNOWN"
    included_in_line_id: str | None = Field(default=None, max_length=80)
    quote_id: str | None = Field(default=None, max_length=160)
    conditions: list[str] = Field(default_factory=list, max_length=12)
    citation_ids: list[str] = Field(default_factory=list, max_length=12)
    queried_at: str | None = Field(default=None, max_length=40)
    activity_ids: list[str] = Field(default_factory=list, max_length=12)
    optional: bool = False
    include_optional: bool = False
    paid_fen: int = Field(default=0, ge=0, le=100_000_000)
    locked: bool = False
    is_synthetic: bool = False

    @model_validator(mode="after")
    def honest(self) -> "BudgetLine":
        safe_text(self.label, 100)
        for text in self.conditions:
            safe_text(text, 300)
        known = self.unit_amount.min_fen is not None
        empty = self.basis in {"UNKNOWN", "NOT_APPLICABLE", "EXCLUDED_SELF_ARRANGED"}
        if empty and (known or self.status != "UNKNOWN"):
            raise ValueError("UNKNOWN_AMOUNT_NOT_ZERO")
        if not empty and (not known or self.status == "UNKNOWN"):
            raise ValueError("AMOUNT_BASIS_REQUIRED")
        if self.basis == "OBSERVED_QUOTE" and not (
            self.quote_id and self.queried_at and self.status == "QUOTED"
        ):
            raise ValueError("QUOTE_REFERENCE_REQUIRED")
        if self.basis == "HISTORICAL_REFERENCE" and not (
            self.citation_ids and self.status == "HISTORICAL"
        ):
            raise ValueError("HISTORICAL_REFERENCE_REQUIRED")
        if self.status == "QUOTED" and self.basis != "OBSERVED_QUOTE":
            raise ValueError("QUOTE_REFERENCE_REQUIRED")
        return self


class TripBudget(StrictModel):
    lodging_scope: Literal["AUTO", "INCLUDE", "EXCLUDE"] = "AUTO"
    people: int | None = Field(default=None, ge=1, le=100)
    days: int | None = Field(default=None, ge=1, le=90)
    nights: int | None = Field(default=None, ge=0, le=90)
    rooms: int | None = Field(default=None, ge=1, le=100)
    target_fen: int | None = Field(default=None, ge=0, le=100_000_000)
    target_locked: bool = False
    assumptions: list[str] = Field(default_factory=list, max_length=12)
    lines: list[BudgetLine] = Field(default_factory=list, max_length=36)

    @model_validator(mode="after")
    def distinct(self) -> "TripBudget":
        ids = [v.line_id for v in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("DUPLICATE_BUDGET_LINE")
        by_id = {v.line_id: v for v in self.lines}
        for v in self.lines:
            parent = by_id.get(v.included_in_line_id or "")
            if v.included_in_line_id and (not parent or parent is v or parent.included_in_line_id):
                raise ValueError("INVALID_INCLUDED_BUDGET_LINE")
        for text in self.assumptions:
            safe_text(text, 300)
        return self


class DiningAdvice(StrictModel):
    day: int = Field(ge=1, le=90)
    window: Literal["LUNCH", "DINNER"]
    strategy: Literal["BETWEEN_ACTIVITIES", "NEAR_SELECTED_AREA", "OPTIONAL_FINISH"]


class LodgingAdvice(StrictModel):
    strategy: Literal[
        "NOT_APPLICABLE", "UNDECIDED", "NEAR_ACTIVITIES", "NEXT_DAY_AREA", "FEWER_MOVES"
    ] = "UNDECIDED"
    area_ids: list[str] = Field(default_factory=list, max_length=4)


class GuideDayChoice(StrictModel):
    """An intentional non-activity day, never an automatically filled itinerary."""

    day: int = Field(ge=1, le=90)
    kind: Literal["REST", "SELF_ARRANGED", "GAP"]
    reason: str = Field(min_length=1, max_length=240)

    @field_validator("reason")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        return safe_text(value, 240)


class GuideContent(StrictModel):
    day_choices: list[GuideDayChoice] = Field(default_factory=list, max_length=90)
    walking_requirement: Literal["NONE", "OPTIONAL", "REQUIRED"] = "NONE"
    title: str = Field(default="可修改的旅行建议", max_length=80)
    reason: str = Field(default="先选想做的项目，再决定节奏。", max_length=240)
    dining: list[DiningAdvice] = Field(default_factory=list, max_length=12)
    lodging: LodgingAdvice = Field(default_factory=LodgingAdvice)
    assumptions: list[str] = Field(default_factory=list, max_length=8)
    unknowns: list[str] = Field(default_factory=list, max_length=8)
    impacts: list[str] = Field(default_factory=list, max_length=8)
    origin: Literal["PRODUCT_DEFAULT", "AI_PROPOSED", "USER_CONFIRMED"] = "PRODUCT_DEFAULT"

    @field_validator("title", "reason")
    @classmethod
    def safe(cls, text: str) -> str:
        return safe_text(text, 240)

    @model_validator(mode="after")
    def safe_lists(self) -> "GuideContent":
        for text in self.assumptions + self.unknowns + self.impacts:
            safe_text(text, 500)
        return self


class GuideActivity(StrictModel):
    activity_id: str = Field(min_length=1, max_length=80)
    day: int = Field(ge=1, le=90)
    period: Literal["UNDECIDED", "MORNING", "AFTERNOON", "EVENING"] = "UNDECIDED"
    stay_min: int | None = Field(default=None, ge=10, le=360)
    stay_max: int | None = Field(default=None, ge=10, le=480)
    rest_minutes: int | None = Field(default=None, ge=0, le=120)

    @model_validator(mode="after")
    def ordered(self) -> "GuideActivity":
        if (self.stay_min is None) != (self.stay_max is None) or (
            self.stay_min is not None
            and self.stay_max is not None
            and self.stay_min > self.stay_max
        ):
            raise ValueError("INVALID_STAY_RANGE")
        return self


class GuideProposal(StrictModel):
    day_choices: list[GuideDayChoice] = Field(default_factory=list, max_length=90)
    walking_requirement: Literal["NONE", "OPTIONAL", "REQUIRED"] = "NONE"
    title: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=240)
    activities: list[GuideActivity] = Field(min_length=1, max_length=12)
    citation_ids: list[str] = Field(max_length=40)
    assumptions: list[str] = Field(min_length=1, max_length=8)
    unknowns: list[str] = Field(min_length=1, max_length=8)
    impacts: list[str] = Field(default_factory=list, max_length=8)
    dining: list[DiningAdvice] = Field(default_factory=list, max_length=12)
    lodging: LodgingAdvice = Field(default_factory=LodgingAdvice)
    budget_lines: list[BudgetLine] = Field(default_factory=list, max_length=24)


class GuideResponse(StrictModel):
    protocol_version: Literal[4]
    proposals: list[GuideProposal] = Field(min_length=1, max_length=3)


class GuideExport(StrictModel):
    filename: str
    markdown: str
    adopted_version: int
    revision: int
