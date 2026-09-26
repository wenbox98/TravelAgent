"""P01 HTTP input contracts; outputs are explicitly projected, never raw bundles."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .projection import safe_text

Mode = Literal["CACHED_PRIVATE_PREVIEW", "SYNTHETIC_DEMO"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PreviewCreate(StrictModel):
    research_id: str | None = Field(default=None, max_length=180)
    text: str = Field(default="", max_length=500)

    @field_validator("text", "research_id")
    @classmethod
    def safe(cls, value: str | None) -> str | None:
        return safe_text(value) if value is not None else None


class PreviewPreferences(StrictModel):
    days: int | None = Field(default=None, ge=1, le=90)
    driving: Literal["YES", "NO", "UNKNOWN"] = "UNKNOWN"


class PreviewMutation(StrictModel):
    action: Literal["preferences", "preview", "cancel", "confirm"]
    expected_revision: int = Field(ge=0)
    option_id: str | None = Field(default=None, max_length=80)
    preferences: PreviewPreferences | None = None
    text: str | None = Field(default=None, max_length=500)

    @field_validator("text")
    @classmethod
    def safe(cls, value: str | None) -> str | None:
        return safe_text(value) if value is not None else None


class PreviewEvidence(StrictModel):
    claim_id: str
    source_id: str
    source_title: str
    text: str
    topic: str
    locator: str
    reference_kind: str
    duration_scope: str | None
    conditions: list[str]
    block_locators: list[str]
    span_ids: list[str]
    completeness: str
    review_status: Literal["WORK_REVIEWED", "MODEL_CONTEXT_REVIEWED", "LOCAL_REVALIDATION"]
    travel_time: str | None
    retrieved_at: str
    source_url: str | None


class PreviewScheduleEntry(StrictModel):
    day: int
    text: str
    evidence_ids: list[str]


class PreviewSchedule(StrictModel):
    entries: list[PreviewScheduleEntry]
    day_count: int | None
    basis: Literal["DERIVED_FROM_SOURCE_SCHEDULE", "INCOMPLETE_OR_AMBIGUOUS"]
    meaning: str


class PreviewCondition(StrictModel):
    text: str
    evidence_ids: list[str]


class PreviewOption(StrictModel):
    option_id: str
    label: str
    label_evidence_ids: list[str]
    reference_kinds: list[str]
    source_count: int
    independent_source_count: None
    opinion_count: int
    evidence: list[PreviewEvidence]
    route_evidence_ids: list[str]
    experience_evidence_ids: list[str]
    source_transport_conditions: list[PreviewCondition]
    source_time_conditions: list[PreviewCondition]
    source_schedule: PreviewSchedule
    verified_duration_days: None
    cost_cny_fen: None
    feasibility: Literal["UNVERIFIED"]
    unknown: list[str]


class PreviewSavedPreferences(StrictModel):
    days: int | None
    driving: Literal["YES", "NO", "UNKNOWN"]
    budget_cny_fen: int | None
    traveler_count: int | None
    time_hint: str | None
    travel_date: None
    charter: Literal["UNKNOWN"]
    answered: list[str]


class PreviewDifference(StrictModel):
    option_id: str
    added: list[str]
    removed: list[str]
    retained: list[str]
    gaps_added: list[str]
    gaps_removed: list[str]
    gaps_retained: list[str]


class PreviewQuestion(StrictModel):
    field: str
    title: str
    advice: str
    choices: list[str]


class PreviewCalls(StrictModel):
    connect: Literal[0]
    search: Literal[0]
    detail: Literal[0]
    xhs_browser: Literal[0]
    model: Literal[0]


class PreviewView(StrictModel):
    session_id: str
    revision: int
    research_id: str | None
    research_revision: int | None
    mode: Mode
    input_text: str
    options: list[PreviewOption]
    other_clues: list[PreviewEvidence]
    evidence_count: int
    source_count: int
    preferences: PreviewSavedPreferences
    confirmed_option_id: str | None
    preview: PreviewDifference | None
    gaps: list[str]
    questions: list[PreviewQuestion] = Field(max_length=2)
    clarification: str | None
    stale: bool
    cache_message: str | None
    feasibility: Literal["UNVERIFIED"]
    business_calls: PreviewCalls
    interest_needs_confirmation: bool = False
    previous_interest: str | None = None


class PreviewResearch(StrictModel):
    research_id: str
    research_revision: int
    label: str
    evidence_count: int


class PreviewIndex(StrictModel):
    mode: Mode
    csrf_token: str
    researches: list[PreviewResearch]
    session: PreviewView | None
    workbench_available: bool = False
    replay_available: bool = False


class ReplayItem(StrictModel):
    source_label: str
    candidate_index: int
    topic: str
    origin: str
    rule_version: int
    action: str
    reason_code: str
    category: str
    explanation: str
    next_action: str
    quote: str | None
    locator: str | None
    conversion: str | None


class ReplayUpdate(StrictModel):
    revalidation_id: str
    research_id: str
    evidence_count: int
    added: int


class ReplayIndex(StrictModel):
    items: list[ReplayItem]
    updates: list[ReplayUpdate]
    message: str


class ReplayAdopt(StrictModel):
    session_id: str = Field(max_length=100)
    revalidation_id: str = Field(max_length=100)
    expected_revision: int = Field(ge=0)


class JobCreate(StrictModel):
    session_id: str = Field(max_length=100)
    expected_revision: int = Field(ge=0)
    destination: str | None = Field(default=None,max_length=80)

    @field_validator('destination')
    @classmethod
    def safe(cls, value: str | None) -> str | None:
        return safe_text(value,80) if value is not None else None


class JobAction(StrictModel):
    action: Literal['cancel','adopt']
    expected_revision: int = Field(ge=0)


class JobView(StrictModel):
    job_id: str
    session_id: str
    status: Literal['QUEUED','RUNNING','WAITING_LOGIN','VERIFICATION_REQUIRED','PARTIAL','COMPLETED',
                    'NEEDS_REVIEW','FAILED','CANCELED','INTERRUPTED']
    request_revision: int
    cancel_requested: bool
    new_evidence_count: int
    reviewed: int
    pending: int
    rejected: int
    reason: str | None
    can_adopt: bool


class WorkbenchCounts(StrictModel):
    connect: int = Field(ge=0)
    search: int = Field(ge=0)
    detail: int = Field(ge=0)
    model: int = Field(ge=0)


class WorkbenchBudget(StrictModel):
    used: WorkbenchCounts
    remaining: WorkbenchCounts
    gate: str
    closed: bool


class WorkbenchIndex(StrictModel):
    enabled: bool
    configured: bool
    budget: WorkbenchBudget
    jobs: list[JobView]
    data_use: str
