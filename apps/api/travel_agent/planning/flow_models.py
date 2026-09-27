"""Trip-local planning proposals; not source facts or map responses."""

from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from travel_agent.preview.models import StrictModel
from travel_agent.preview.projection import safe_text
from .models import TripInputs


class SpatialIntent(StrictModel):
    intent: Literal["UNDECIDED", "CITY_CORE", "CITY_AND_SURROUNDINGS", "REGIONAL"] = "UNDECIDED"
    origin: Literal["UNKNOWN", "USER_EXPLICIT", "TEST_INPUT", "PRODUCT_PROPOSED"] = "UNKNOWN"


class KnowledgeBinding(StrictModel):
    card_id: str = Field(pattern=r"^card-[a-f0-9]{28}$")
    version: int = Field(ge=1)
    card_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class Activity(StrictModel):
    knowledge_refs: list[KnowledgeBinding] = Field(default_factory=list, max_length=12)
    activity_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=120)
    region: str = Field(default="", max_length=80)
    region_origin: Literal["REQUEST_FILTER", "USER_INPUT"] = "REQUEST_FILTER"
    spatial_status: Literal["MATCH", "MISMATCH", "UNKNOWN"] = "UNKNOWN"
    spatial_basis: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    source_locations: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=200)
    reference_kinds: list[str] = Field(default_factory=list, max_length=8)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    discovery_ids: list[str] = Field(default_factory=list, max_length=12)
    conditions: list[str] = Field(default_factory=list, max_length=30)
    provenance: Literal[
        "USER_INPUT", "SOURCE_REFERENCE", "SOURCE_MENTION", "SYNTHETIC_TEST", "PRODUCT_DEFAULT"
    ]
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
    spatial: SpatialIntent = Field(default_factory=SpatialIntent)
    direction: str | None = Field(default=None, max_length=100)
    days: int | None = Field(default=None, ge=1, le=90)
    driving: Literal["UNKNOWN", "YES", "NO"] = "UNKNOWN"
    transport: Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"] = (
        "UNKNOWN"
    )
    walking_allowed: bool = False
    adjustment: Literal["NONE", "FEWER", "LONGER_FIRST", "SWAP_FIRST_TWO"] = "NONE"
    adjustment_minutes: int | None = Field(default=None, ge=5, le=120)
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
    knowledge_first: bool = False
    destination: str = Field(min_length=1, max_length=80)
    request: str = Field(default="", max_length=500)
    travel_kind: Literal["CITY", "REGIONAL"] = "CITY"
    demo: Literal["CITY", "REGIONAL", "OTHER_CITY"] | None = None
    validation_trip: bool = False

    @field_validator("destination", "request")
    @classmethod
    def text(cls, value: str) -> str:
        return safe_text(value, 500).strip()


class OperationAuthorization(StrictModel):
    confirm: Literal[True]
    tasks: list[Literal["RESEARCH", "PLANNING", "REVISION", "MAP"]] = Field(
        min_length=1, max_length=4
    )
    hours: int = Field(default=24, ge=1, le=168)
    connect: int = Field(default=0, ge=0, le=1)
    search: int = Field(default=0, ge=0, le=3)
    detail: int = Field(default=0, ge=0, le=6)
    model: int = Field(default=0, ge=0, le=20)
    map_place: int = Field(default=0, ge=0, le=16)
    map_route: int = Field(default=0, ge=0, le=16)


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
        "research",
        "adopt_research",
        "use_activities",
        "discover_places",
        "use_leads",
        "authorize",
        "revoke_authorization",
        "reuse_activities",
    ]
    expected_revision: int = Field(ge=0)
    draft: PlanDraft | None = None
    section: Literal["direction", "activities", "conditions", "plan"] | None = None
    collapsed: bool = False
    proposal_index: int = Field(default=0, ge=0, le=2)
    option_id: str | None = Field(default=None, max_length=100)
    activity_ids: list[str] = Field(default_factory=list, max_length=12)
    authorization: OperationAuthorization | None = None
    reuse_key: str | None = Field(default=None, max_length=64)


class GroundedActivity(StrictModel):
    candidate_key: str = Field(pattern=r"^candidate-[0-9]{1,2}$")
    place_name: str = Field(min_length=2, max_length=30)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


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
    grounded_activities: list[GroundedActivity] = Field(default_factory=list, max_length=12)


class UnresolvedSuggestions(StrictModel):
    transport: (
        Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"] | None
    ) = None
    first_start: str | None = None

    @field_validator("first_start")
    @classmethod
    def time(cls, value: str | None) -> str | None:
        return TripInputs.time(value)


class Arrangement(StrictModel):
    title: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=240)
    activities: list[SuggestedActivity] = Field(min_length=1, max_length=12)
    citation_ids: list[str] = Field(max_length=40)
    assumptions: list[str] = Field(min_length=1, max_length=8)
    unknowns: list[str] = Field(min_length=1, max_length=8)
    impacts: list[str] = Field(max_length=8)
    unresolved_suggestions: UnresolvedSuggestions | None = None


class ArrangementResponse(StrictModel):
    protocol_version: Literal[2]
    proposals: list[Arrangement] = Field(min_length=1, max_length=3)
    grounded_activities: list[GroundedActivity] = Field(default_factory=list, max_length=12)


class RevisionProposal(StrictModel):
    reason_code: Literal["LONGER_FIRST", "FEWER"]
    activities: list[SuggestedActivity] = Field(min_length=1, max_length=12)
    citation_ids: list[str] = Field(max_length=40)


class RevisionResponse(StrictModel):
    protocol_version: Literal[3]
    proposals: list[RevisionProposal] = Field(min_length=1, max_length=3)


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
    proposal_preview_active: bool = False
    direction_change_pending: bool = False
    cache_message: str
    job: dict[str, Any] | None
    model_available: bool
    provenance: dict[str, str]
    feasibility: Literal["UNVERIFIED"] = "UNVERIFIED"
    validation_trip: bool = False
    activity_candidates: list[Activity] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    research_job: dict[str, Any] | None = None
    private_budget: dict[str, Any] | None = None
    research_available: bool = False
    private_model_available: bool = False
    model_reason: str | None = None
    discovery_available: bool = False
    place_leads: list[dict[str, Any]] = Field(default_factory=list)
    operation: dict[str, Any] | None = None
    reuse_options: list[dict[str, Any]] = Field(default_factory=list)
    model_status: str | None = None


class PlanIndex(StrictModel):
    trips: list[dict[str, Any]]
    current: PlanView | None
    model_used: int
    model_limit: int = 2
