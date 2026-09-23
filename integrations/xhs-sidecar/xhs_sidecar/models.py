"""Versioned internal sidecar contract, separate from Evidence/Research APIs."""

from dataclasses import dataclass, field
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, computed_field, model_validator

Completeness = Literal["FULL_TEXT", "PARTIAL_TEXT", "SUMMARY_ONLY", "METADATA_ONLY"]
FilterStatus = Literal["APPLIED", "NOT_REQUESTED", "FAILED", "UNKNOWN"]
ResourceCategory = Literal["document", "xhr_fetch", "image", "media", "other"]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class SourceIdentity(ContractModel):
    provider: Literal["xhs"] = "xhs"
    note_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def source_id(self) -> str:
        return f"{self.provider}:{self.note_id}"


@dataclass(frozen=True, repr=False)
class AccessLocator:
    """Private, memory-only capability. Never an API/Evidence model."""

    source: SourceIdentity
    session_id: str
    xsec_token: SecretStr
    ttl_status: Literal["UNKNOWN"] = field(default="UNKNOWN", init=False)

    def __repr__(self) -> str:
        return "AccessLocator(private)"


class SearchFilters(ContractModel):
    sort_by: Literal["综合", "最新", "最多点赞", "最多评论", "最多收藏"] | None = None
    note_type: Literal["不限", "视频", "图文"] | None = None
    publish_time: Literal["不限", "一天内", "一周内", "半年内"] | None = None
    search_scope: Literal["不限", "已看过", "未看过", "已关注"] | None = None
    location: Literal["不限", "同城", "附近"] | None = None

    def specified(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class SearchRequest(ContractModel):
    keyword: str = Field(min_length=1, max_length=200, pattern=r"\S")
    filters: SearchFilters = Field(default_factory=SearchFilters)


class DetailRequest(ContractModel):
    note_handle: str = Field(pattern=r"^[a-f0-9]{32}$")


class Candidate(ContractModel):
    source: SourceIdentity
    note_handle: str = Field(pattern=r"^[a-f0-9]{32}$")
    title: str
    note_type: Literal["normal", "video", "unknown"] = "unknown"
    published_at: None = None
    summary: None = None


class RequestCounts(ContractModel):
    document: int | None = Field(default=None, ge=0)
    xhr_fetch: int | None = Field(default=None, ge=0)
    image: int | None = Field(default=None, ge=0)
    media: int | None = Field(default=None, ge=0)
    other: int | None = Field(default=None, ge=0)


class NetworkSnapshot(ContractModel):
    # Deterministic local-route property, separate from unmeasured browser traffic.
    login_status_external_requests: Literal[0] = 0
    measurement: Literal["NOT_MEASURED", "SIMULATED"] = "NOT_MEASURED"
    browser_navigation: int | None = Field(default=None, ge=0)
    requests: RequestCounts = Field(default_factory=RequestCounts)
    total_requests: int | None = Field(default=None, ge=0)
    total_bytes: int | None = Field(default=None, ge=0)
    scope: Literal["none", "synthetic_events_only"] = "none"

    @model_validator(mode="after")
    def coherent_measurement(self) -> Self:
        counts = self.requests.model_dump().values()
        if self.measurement == "NOT_MEASURED":
            if (
                any(value is not None for value in counts)
                or self.browser_navigation is not None
                or self.total_requests is not None
                or self.total_bytes is not None
                or self.scope != "none"
            ):
                raise ValueError("未观测的数据必须未知")
        elif (
            any(value is None for value in counts)
            or self.browser_navigation is None
            or self.total_requests != sum(value or 0 for value in counts)
            or self.scope != "synthetic_events_only"
        ):
            raise ValueError("合成计数不一致")
        return self


class SearchResult(ContractModel):
    mode: Literal["offline"] = "offline"
    is_synthetic: Literal[True] = True
    candidates: list[Candidate]
    filter_requested: SearchFilters
    filter_applied: SearchFilters
    filter_status: FilterStatus
    network: NetworkSnapshot

    @model_validator(mode="after")
    def honest_filters(self) -> Self:
        requested = self.filter_requested.specified()
        applied = self.filter_applied.specified()
        if self.filter_status == "APPLIED":
            valid = bool(requested) and requested == applied
        elif self.filter_status == "NOT_REQUESTED":
            valid = not requested and not applied
        else:
            valid = bool(requested) and not applied
        if not valid:
            raise ValueError("筛选状态与实际确认条件不一致")
        return self


class Classification(ContractModel):
    completeness: Completeness
    reason: Literal[
        "verified_text_scope", "unverified_or_truncated_text", "summary_only", "no_text"
    ]


@dataclass(frozen=True, repr=False)
class RawDetail:
    source: SourceIdentity
    title: str
    body: str | None = None
    summary: str | None = None
    text_scope_verified: bool = False
    truncated: bool = False
    http_status: int = 200


class DetailResult(ContractModel):
    mode: Literal["offline"] = "offline"
    is_synthetic: Literal[True] = True
    source: SourceIdentity
    title: str
    body: str | None
    summary: str | None
    completeness: Completeness
    completeness_reason: str
    images_read: Literal[False] = False
    network: NetworkSnapshot


class BrowserState(ContractModel):
    mode: Literal["offline", "login"] = "offline"
    backend: Literal["fake", "playwright"] = "fake"
    state: Literal["ACTIVE", "CLOSED"]
    session_id: str | None = None


LoginStatus = Literal[
    "NOT_IMPLEMENTED",
    "DISCONNECTED",
    "STARTING_BROWSER",
    "SESSION_PRESENT_UNVERIFIED",
    "CHECKING",
    "LOGIN_REQUIRED",
    "WAITING_USER",
    "AUTHENTICATED",
    "VERIFICATION_REQUIRED",
    "CANCELLED",
    "ERROR",
]
LoginError = Literal[
    "BROWSER_ERROR", "LOGIN_TIMEOUT", "LOGIN_STATE_UNCERTAIN", "CLEANUP_FAILED", "FLOW_STOP_TIMEOUT"
]
LoginStopReason = Literal[
    "AUTHENTICATED", "VERIFICATION_REQUIRED", "OBSERVATION_TIMEOUT", "OBSERVATION_LIMIT",
    "LOGIN_TIMEOUT", "BROWSER_ERROR", "CANCELLED", "DISCONNECTED", "SHUTDOWN",
    "CLEANUP_FAILED", "FLOW_STOP_TIMEOUT",
]


class LoginEvidence(ContractModel):
    """Public diagnostic facts only: no page text, URLs, identifiers or credentials."""

    current_url_classification: Literal[
        "OFFICIAL_PAGE", "OTHER_OFFICIAL_PAGE", "LOGIN", "VERIFICATION", "FOREIGN_ORIGIN", "UNKNOWN"
    ] = "UNKNOWN"
    page_ready: bool | None = None
    login_dialog_present: bool | None = None
    login_button_present: bool | None = None
    authenticated_account_entry_present: bool | None = None
    account_entry_identity_matches: bool = False
    legacy_account_entry_present: bool | None = None
    authenticated_user_state: bool | None = None
    account_identity_available: bool = False
    verification_present: bool | None = None
    access_restriction_present: bool | None = None


class LoginState(ContractModel):
    mode: Literal["offline", "login"] = "offline"
    status: LoginStatus = "NOT_IMPLEMENTED"
    generation: int = Field(default=0, ge=0)
    flow_id: str | None = None
    remote_checked: bool = False
    account_identity: Literal["KNOWN", "UNKNOWN"] = "UNKNOWN"
    login_status_external_requests: Literal[0] = 0
    error_code: LoginError | None = None
    evidence: LoginEvidence | None = None
    observation_attempts: int = Field(default=0, ge=0, le=10_000)
    stop_reason: LoginStopReason | None = None


class Health(ContractModel):
    status: Literal["ok"] = "ok"
    mode: Literal["offline", "login"] = "offline"
    backend: Literal["fake", "playwright"] = "fake"
    contract_version: Literal["0.3.0"] = "0.3.0"


class SidecarError(ContractModel):
    code: Literal[
        "LOCAL_ONLY",
        "UNAUTHORIZED",
        "QUERY_NOT_ALLOWED",
        "INTERNAL_ERROR",
        "INVALID_REQUEST",
        "INVALID_HANDLE",
        "SESSION_CLOSED",
        "NOT_FOUND",
        "METHOD_NOT_ALLOWED",
        "BACKEND_CONTRACT_ERROR",
        "LOGIN_NOT_ENABLED",
        "LOGIN_ONLY",
    ]
    message: Literal["本地只读服务请求未完成"] = "本地只读服务请求未完成"


class ErrorResponse(ContractModel):
    error: SidecarError
