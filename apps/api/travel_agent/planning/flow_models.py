"""Trip-local planning proposals; not source facts or map responses."""

from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import safe_text
from .models import TripInputs


class Activity(StrictModel):
    activity_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    region: str = Field(default="", max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    provenance: Literal["USER_INPUT", "SOURCE_REFERENCE", "SYNTHETIC_TEST", "PRODUCT_DEFAULT"]
    day: int = Field(default=1, ge=1, le=90)
    stay_min: int | None = Field(default=None, ge=0, le=720)
    stay_max: int | None = Field(default=None, ge=0, le=720)
    rest_minutes: int | None = Field(default=None, ge=0, le=180)
    locked_start: str | None = None
    timing_origin: Literal[
        "UNKNOWN", "USER_CONFIRMED", "AI_PROPOSED", "PRODUCT_DEFAULT", "SYNTHETIC_TEST"
    ] = "UNKNOWN"

    @field_validator("locked_start")
    @classmethod
    def time(cls, value: str | None) -> str | None:
        return TripInputs.time(value)

    @model_validator(mode="after")
    def ordered(self) -> "Activity":
        if (self.stay_min is None) != (self.stay_max is None) or (
            self.stay_min is not None
            and self.stay_max is not None
            and self.stay_min > self.stay_max
        ):
            raise ValueError("INVALID_STAY_RANGE")
        return self


class PlanDraft(StrictModel):
    direction: str | None = Field(default=None, max_length=100)
    days: int | None = Field(default=None, ge=1, le=90)
    driving: Literal["UNKNOWN", "YES", "NO"] = "UNKNOWN"
    transport: Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"] = (
        "UNKNOWN"
    )
    inputs: TripInputs = Field(default_factory=TripInputs)
    first_day: int = Field(default=1, ge=1, le=90)
    first_period: Literal["UNDECIDED", "MORNING", "AFTERNOON", "EVENING"] = "UNDECIDED"
    anchor_origin: Literal["UNKNOWN", "USER_CONFIRMED", "AI_PROPOSED", "SYNTHETIC_TEST"] = "UNKNOWN"
    return_deadline: str | None = None
    activities: list[Activity] = Field(default_factory=list, max_length=12)

    @field_validator("return_deadline")
    @classmethod
    def time(cls, value: str | None) -> str | None:
        return TripInputs.time(value)


class PlanCreate(StrictModel):
    destination: str = Field(min_length=1, max_length=80)
    request: str = Field(default="", max_length=500)
    travel_kind: Literal["CITY", "REGIONAL"] = "CITY"
    demo: Literal["CITY", "REGIONAL", "OTHER_CITY"] | None = None

    @field_validator("destination", "request")
    @classmethod
    def text(cls, value: str) -> str:
        return safe_text(value, 500).strip()


class PlanAction(StrictModel):
    action: Literal[
        "save",
        "adopt",
        "cancel",
        "collapse",
        "suggest",
        "cancel_job",
        "use_proposal",
        "confirm_direction",
        "cancel_direction",
        "add_source",
    ]
    expected_revision: int = Field(ge=0)
    draft: PlanDraft | None = None
    section: Literal["direction", "activities", "conditions", "plan"] | None = None
    collapsed: bool = False
    proposal_index: int = Field(default=0, ge=0, le=2)
    option_id: str | None = Field(default=None, max_length=100)


class SuggestedActivity(StrictModel):
    activity_id: str = Field(min_length=1, max_length=80)
    day: int = Field(ge=1, le=90)
    stay_min: int = Field(ge=10, le=360)
    stay_max: int = Field(ge=10, le=480)
    rest_minutes: int = Field(ge=0, le=120)


class Suggestion(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=240)
    first_start: str
    transport: Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"]
    activities: list[SuggestedActivity] = Field(min_length=1, max_length=12)
    citation_ids: list[str] = Field(max_length=40)
    assumptions: list[str] = Field(min_length=1, max_length=8)
    unknowns: list[str] = Field(min_length=1, max_length=8)
    impacts: list[str] = Field(max_length=8)

    @field_validator("first_start")
    @classmethod
    def time(cls, value: str) -> str:
        TripInputs.time(value)
        return value


class PlanningResponse(StrictModel):
    proposals: list[Suggestion] = Field(min_length=1, max_length=3)


class PlanView(StrictModel):
    session_id: str
    revision: int
    destination: str
    request: str
    travel_kind: str
    demo: str | None
    mode: Literal["SYNTHETIC_DEMO", "CACHED_PRIVATE_PREVIEW"]
    draft: PlanDraft
    adopted: PlanDraft | None
    collapsed: dict[str, bool]
    directions: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    gaps: list[str]
    differences: list[str]
    evidence_count: int
    direction_change_pending: bool = False
    cache_message: str
    job: dict[str, Any] | None
    model_available: bool
    provenance: dict[str, str]
    feasibility: Literal["UNVERIFIED"] = "UNVERIFIED"


class PlanIndex(StrictModel):
    trips: list[dict[str, Any]]
    current: PlanView | None
    model_used: int
    model_limit: Literal[2] = 2
