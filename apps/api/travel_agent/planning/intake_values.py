"""Field-discriminated intake values and allow-listed diagnostics, never raw error text."""

from copy import deepcopy
import json
import re
from typing import Annotated, Any, Literal

from pydantic import Field, StrictBool, StrictInt, ValidationError
from travel_agent.preview.models import StrictModel


class EvidenceUpdate(StrictModel):
    start: Annotated[StrictInt, Field(ge=0, le=500)]
    end: Annotated[StrictInt, Field(ge=1, le=500)]
    quote: str = Field(min_length=1, max_length=500, strict=True)


class DestinationUpdate(EvidenceUpdate):
    field: Literal["destination"]
    value: str = Field(min_length=1, max_length=80, strict=True)


class DaysUpdate(EvidenceUpdate):
    field: Literal["days"]
    value: Annotated[StrictInt, Field(ge=1, le=90)] | None


class PeopleUpdate(EvidenceUpdate):
    field: Literal["people"]
    value: Annotated[StrictInt, Field(ge=1, le=100)] | None


class BudgetUpdate(EvidenceUpdate):
    field: Literal["target_fen"]
    value: Annotated[StrictInt, Field(ge=0, le=100_000_000)] | None


class ArrivalUpdate(EvidenceUpdate):
    field: Literal["arrival_transport"]
    value: Literal["UNKNOWN", "AIR", "RAIL", "ROAD"]


class TransportUpdate(EvidenceUpdate):
    field: Literal["transport"]
    value: Literal["UNKNOWN", "PUBLIC_TRANSIT", "SELF_DRIVE", "LOCAL_SERVICE", "WALKING"]


class DrivingUpdate(EvidenceUpdate):
    field: Literal["driving"]
    # Canonical strings preferred. Legacy JSON booleans require the evidence rule below.
    value: Literal["UNKNOWN", "YES", "NO"] | StrictBool


class RentalUpdate(EvidenceUpdate):
    field: Literal["rental"]
    value: Literal["UNKNOWN", "YES", "NO"]


class PaceUpdate(EvidenceUpdate):
    field: Literal["pace"]
    value: Literal["UNKNOWN", "RELAXED"]


class WalkingUpdate(EvidenceUpdate):
    field: Literal["walking_allowed"]
    value: StrictBool | None


class SpatialUpdate(EvidenceUpdate):
    field: Literal["spatial"]
    value: Literal["UNDECIDED", "CITY_CORE", "CITY_AND_SURROUNDINGS", "REGIONAL"]


class ClockUpdate(EvidenceUpdate):
    field: Literal["activity_start", "return_deadline"]
    value: Annotated[str, Field(strict=True, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")] | None


class DateUpdate(EvidenceUpdate):
    field: Literal["depart_at", "return_by"]
    value: Annotated[str, Field(strict=True, max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?$")] | None


Update = Annotated[DestinationUpdate | DaysUpdate | PeopleUpdate | BudgetUpdate | ArrivalUpdate
    | TransportUpdate | DrivingUpdate | RentalUpdate | PaceUpdate | WalkingUpdate | SpatialUpdate
    | ClockUpdate | DateUpdate, Field(discriminator="field")]

FIELDS = frozenset({"destination", "days", "people", "target_fen", "arrival_transport", "transport",
    "driving", "rental", "pace", "walking_allowed", "spatial", "activity_start", "return_deadline",
    "depart_at", "return_by"})


class IntakeError(ValueError):
    def __init__(self, code: str, *, phase: str = "INTAKE_SCHEMA", field: str | None = None,
                 category: str = "SCHEMA") -> None:
        super().__init__(code)
        self.failure = dict(reason=code, phase=phase, category=category,
                            field=field if field in FIELDS else None)


def invalid_value(exc: ValidationError, phase: str = "INTAKE_SCHEMA") -> IntakeError:
    errors = exc.errors(include_input=False, include_url=False)
    first = errors[0]
    field = next((v for v in first["loc"] if v in FIELDS), None)
    kind = first["type"]
    category = "TYPE" if kind.endswith("_type") or kind.endswith("_parsing") else (
        "ENUM" if kind in {"literal_error", "union_tag_invalid"} else
        "RANGE" if kind.startswith(("less_than", "greater_than", "string_too")) else
        "FORMAT" if kind in {"string_pattern_mismatch", "value_error"} else "SCHEMA")
    return IntakeError("INTAKE_INVALID_VALUE", phase=phase, field=field, category=category)


def boolean_driving(item: DrivingUpdate) -> tuple[Literal["YES", "NO"], dict[str, Any]]:
    """Exact JSON bool only; an unambiguous explicit driving phrase must agree."""
    # This is compatibility validation, not extraction or inference of other conditions.
    phrase = re.sub(r"^(?:我们|我)", "", item.quote.strip().strip("，。！!"))
    action = r"(?:(?:开车)?自驾(?:去)?|自己开(?:车)?(?:去)?|租车自驾|租车自己开(?:车)?|开租来的车)"
    yes = re.fullmatch(r"(?:愿意|想|要|打算)?" + action, phrase) is not None
    no = re.fullmatch(r"(?:不|不想|不愿意|不要)" + action, phrase) is not None
    if type(item.value) is not bool or not (yes if item.value else no) or yes == no:
        raise IntakeError("INTAKE_BOOLEAN_EVIDENCE_REQUIRED", phase="INTAKE_EVIDENCE",
                          field="driving", category="EVIDENCE")
    value: Literal["YES", "NO"] = "YES" if item.value is True else "NO"
    return value, dict(field="driving", rule="EXPLICIT_DRIVING_BOOL_V1",
                       received_type="boolean", received_value=item.value, value=value)


def model_record(db: Any, scope: str, sid: str, grant: str, p: dict[str, Any]) -> Any:
    return db.connection.execute(
        "SELECT job_id,status,summary_json FROM preview_jobs WHERE job_id=? AND account_scope=? "
        "AND session_id=? AND continuation_id=? AND research_id LIKE 'agent-%'",
        (p.get("agent_model_job_id"), scope, sid, grant),
    ).fetchone()


def understanding_view(db: Any, scope: str, sid: str, task: Any,
                       p: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any] | None:
    """Read-only historical diagnosis; never repair or replay old stored tasks."""
    value: dict[str, Any] | None = deepcopy(p.get("agent_understanding"))
    if not value or summary.get("reason") != "AGENT_STOPPED" or task["stage"] != "INTAKE":
        return value
    child = model_record(db, scope, sid, task["grant_id"], p)
    if not child:
        return value
    info = json.loads(child["summary_json"] or "{}")
    if info.get("purpose") != "travel_intake_v1":
        return value
    failure = dict(reason="INTAKE_APPLY_FAILED", phase="INTAKE_APPLY", field=None,
                   category="UNKNOWN", historical=True)
    if child["status"] == "COMPLETED":
        for update in info.get("result", {}).get("updates", []):
            if update.get("field") == "driving" and type(update.get("value")) is bool:
                failure.update(reason="INTAKE_LEGACY_VALUE_TYPE", field="driving", category="TYPE")
                break
    value.update(status="FAILED", model_executed=bool(info.get("model_executed") or
        info.get("diagnostic", {}).get("http_attempts")), job_id=child["job_id"],
        reason=failure["reason"], failure=failure, stored_reason=summary["reason"])
    return value
