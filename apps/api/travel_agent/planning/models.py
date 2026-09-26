from datetime import datetime
import re
from typing import Literal
from pydantic import Field, field_validator, model_validator
from travel_agent.preview.models import StrictModel, PreviewSavedPreferences, PreviewSchedule
from travel_agent.preview.projection import safe_text
from travel_agent.providers.amap import SHANGHAI


class PlaceInput(StrictModel):
    place_id: str = Field(pattern=r"^[a-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=80)
    region: str = Field(default="", max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    provenance: Literal["EVIDENCE_FRAGMENT", "USER_INPUT"] = "USER_INPUT"
    object_type: Literal[
        "UNKNOWN", "AREA", "TOWN", "STATION", "SCENIC", "ENTRANCE", "PARKING", "VISITOR_CENTER"
    ] = "UNKNOWN"
    private_address: bool = False

    @field_validator("name", "region")
    @classmethod
    def text(cls, value: str) -> str:
        return safe_text(value, 80).strip()


class TripInputs(StrictModel):
    depart_at: str | None = None
    return_by: str | None = None
    origin: str = Field(default="", max_length=80)
    destination: str = Field(default="", max_length=80)
    same_return: bool = False
    endpoints_private: bool = False
    charter: Literal["UNKNOWN", "COMPARE", "NO"] = "UNKNOWN"
    mode: Literal["TRANSIT", "DRIVING", "WALKING"] = "TRANSIT"
    activity_start: str | None = None
    activity_end: str | None = None
    stay_minutes: int | None = Field(default=None, ge=0, le=43200)
    rest_minutes: int | None = Field(default=None, ge=0, le=43200)
    buffer_minutes: int | None = Field(default=None, ge=0, le=43200)
    transfer_minutes: int | None = Field(default=None, ge=0, le=43200)
    places: list[PlaceInput] = Field(default_factory=list, max_length=12)

    @field_validator("origin", "destination")
    @classmethod
    def text(cls, value: str) -> str:
        return safe_text(value, 80).strip()

    @field_validator("depart_at", "return_by")
    @classmethod
    def date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 40 or "T" not in value:
            raise ValueError("INVALID_DATETIME")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SHANGHAI)
        return dt.astimezone(SHANGHAI).isoformat()

    @field_validator("activity_start", "activity_end")
    @classmethod
    def time(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("INVALID_ACTIVITY_WINDOW")
        return value

    @model_validator(mode="after")
    def valid(self) -> "TripInputs":
        if (
            self.depart_at
            and self.return_by
            and datetime.fromisoformat(self.return_by) <= datetime.fromisoformat(self.depart_at)
        ):
            raise ValueError("INVALID_TIME_WINDOW")
        if (
            self.depart_at
            and self.return_by
            and (
                datetime.fromisoformat(self.return_by) - datetime.fromisoformat(self.depart_at)
            ).days
            > 90
        ):
            raise ValueError("WINDOW_TOO_LONG")
        ids = [p.place_id for p in self.places]
        if len(set(ids)) != len(ids) or set(ids) & {"origin", "return"}:
            raise ValueError("DUPLICATE_PLACE")
        if self.same_return:
            self.destination = self.origin
        return self


class MapAction(StrictModel):
    action: Literal["save", "cancel", "adopt", "resolve", "confirm_place", "route"]
    session_id: str = Field(max_length=100)
    expected_revision: int = Field(ge=0)
    expected_preview_revision: int = Field(ge=0)
    inputs: TripInputs | None = None
    place_id: str | None = Field(default=None, max_length=80)
    candidate_id: str | None = Field(default=None, max_length=80)
    relation: Literal["SAME_OBJECT", "REGIONAL_REFERENCE", "ACCESS_POINT"] | None = None
    leg_id: str | None = Field(default=None, max_length=170)
    send_confirmed: bool = False
    private_send_confirmed: bool = False
    # A leg date is explicit; never infer every intermediate departure from trip start.
    leg_depart_at: str | None = None

    @field_validator("leg_depart_at")
    @classmethod
    def date(cls, value: str | None) -> str | None:
        return TripInputs.date(value)


class MapCandidate(StrictModel):
    candidate_id: str
    name: str
    type: str
    address: str
    pname: str
    cityname: str
    adname: str
    citycode: str
    adcode: str
    location: str
    coordinate_system: Literal["GCJ02"]
    object_type: str
    uri: str


class MapConfirmed(MapCandidate):
    relation: Literal["SAME_OBJECT", "REGIONAL_REFERENCE", "ACCESS_POINT"]


class MapPlace(PlaceInput):
    raw_name: str
    status: str
    candidates: list[MapCandidate]
    confirmed: MapConfirmed | None
    source: Literal["USER_INPUT", "REVIEWED_SOURCE_FRAGMENT"]


class MapLeg(StrictModel):
    leg_id: str
    from_id: str
    to_id: str
    from_name: str
    to_name: str
    mode: Literal["TRANSIT", "DRIVING", "WALKING"]
    endpoint_confidence: str
    kind: Literal["OUTBOUND", "RETURN", "BETWEEN_SOURCE_PLACES"]
    status: str
    stale: bool
    duration_seconds: float | None
    distance_meters: float | None
    queried_at: str | None
    date_applicability: str
    requested_depart_at: str | None
    availability: Literal["UNKNOWN"]
    basis: str
    gaps: list[str]
    result_endpoint_names: list[str]
    error_code: str | None


class TimeCheck(StrictModel):
    completeness: Literal["COMPLETE", "PARTIAL"]
    scenario: Literal[
        "UNKNOWN", "FITS_UNDER_STATED_ASSUMPTIONS", "EXCEEDS_UNDER_STATED_ASSUMPTIONS"
    ]
    executable: Literal["UNVERIFIED"]
    known_movement_minutes: float
    known_components_minutes: float
    available_minutes: float | None
    assumptions: list[str]
    unknown_legs: list[str]
    missing_inputs: list[str]
    checked_scope: Literal["LOCAL_DAY_SEGMENT", "WHOLE_SELECTED_OBJECT"]
    meaning: str


class MapCounts(StrictModel):
    map_place: int = Field(ge=0)
    map_route: int = Field(ge=0)


class MapQuota(StrictModel):
    used: MapCounts
    remaining: MapCounts
    total_used: int = Field(ge=0, le=16)
    total_limit: Literal[16]


class NoResearchCalls(StrictModel):
    xhs_connect: Literal[0]
    xhs_search: Literal[0]
    xhs_detail: Literal[0]
    xhs_browser: Literal[0]
    model: Literal[0]


class MapView(StrictModel):
    session_id: str
    revision: int
    preview_revision: int
    interest: str
    evidence_count: int
    inherited: PreviewSavedPreferences
    source_schedule: PreviewSchedule
    source_route_fragments: list[str]
    source_reference_kinds: list[str]
    inputs: TripInputs
    adopted_inputs: TripInputs | None
    has_changes: bool
    places: list[MapPlace]
    legs: list[MapLeg]
    time_check: TimeCheck
    configured: bool
    configuration_status: Literal["CONFIGURED_NOT_VERIFIED", "AMAP_LIVE_BLOCKED_NOT_CONFIGURED"]
    budget: MapQuota
    map_storage: Literal["EPHEMERAL_MEMORY_ONLY"]
    map_result_state: Literal["STALE", "CURRENT_PROCESS", "EXPIRED_OR_NOT_QUERIED"]
    message: str
    last_action: str | None
    business_calls: NoResearchCalls
