"""Deterministic partial accounting. Missing components never become zero."""

from datetime import datetime, timedelta
from typing import Any
from .models import TripInputs


def check_time(
    inputs: TripInputs, legs: list[dict[str, Any]], *, checked_scope: str
) -> dict[str, Any]:
    if inputs.planning_scope == "ACTIVITY_WINDOW":
        legs = [leg for leg in legs if leg.get("kind") not in {"OUTBOUND", "RETURN"}]
    missing = []
    assumptions = []
    unknown = [
        leg["leg_id"] for leg in legs if leg.get("duration_seconds") is None or leg.get("stale")
    ]
    movement = sum(
        leg["duration_seconds"] / 60
        for leg in legs
        if leg.get("duration_seconds") is not None and not leg.get("stale")
    )
    if not legs:
        missing.append("ROUTE_NOT_CHECKED")
    if inputs.planning_scope == "DOOR_TO_DOOR" and (not inputs.origin or not inputs.destination):
        missing.append("ENDPOINTS_UNKNOWN")
    available = None
    if inputs.planning_scope == "ACTIVITY_WINDOW":
        assumptions.append("SELF_ARRIVAL_NOT_CHECKED_NOT_ZERO")
        if inputs.return_by:
            missing.append("RETURN_HARD_CONSTRAINT_UNVERIFIED")
        if inputs.activity_start and inputs.activity_end:
            h, m = map(int, inputs.activity_start.split(":"))
            h2, m2 = map(int, inputs.activity_end.split(":"))
            available = float((h2 * 60 + m2 - h * 60 - m) % 1440)
        else:
            missing.append("ACTIVITY_WINDOW_UNKNOWN")
    elif not inputs.depart_at or not inputs.return_by:
        missing.append("TIME_WINDOW_UNCONFIRMED")
    elif not inputs.activity_start or not inputs.activity_end:
        missing.append("ACTIVITY_WINDOW_UNKNOWN")
    else:
        start, end = (
            datetime.fromisoformat(inputs.depart_at),
            datetime.fromisoformat(inputs.return_by),
        )
        day = start.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        available = 0.0
        while day < end:
            h, m = map(int, inputs.activity_start.split(":"))
            a = day.replace(hour=h, minute=m)
            h, m = map(int, inputs.activity_end.split(":"))
            b = day.replace(hour=h, minute=m)
            if b <= a:
                b += timedelta(days=1)
            available += max(0, (min(b, end) - max(a, start)).total_seconds() / 60)
            day += timedelta(days=1)
        assumptions.append("USER_ACTIVITY_WINDOW_EXCLUDES_NIGHT_REST")
    known = movement
    for field, code in [
        ("stay_minutes", "STAY"),
        ("rest_minutes", "REST"),
        ("buffer_minutes", "BUFFER"),
        ("transfer_minutes", "ACCESS_TRANSFER"),
    ]:
        value = getattr(inputs, field)
        if value is None:
            missing.append(code + "_UNKNOWN")
        else:
            known += value
            assumptions.append(f"USER_{code}_MINUTES={value}")
    if unknown:
        missing.append("UNCHECKED_LEGS")
    if checked_scope != "WHOLE_SELECTED_OBJECT":
        missing.append("LOCAL_SCOPE_NOT_WHOLE_TRIP")
    # These are estimates, not a proven full-trip lower bound, even when exceeding.
    scenario = "UNKNOWN"
    if available is not None and known > available:
        scenario = "EXCEEDS_UNDER_STATED_ASSUMPTIONS"
    elif available is not None and not missing:
        scenario = "FITS_UNDER_STATED_ASSUMPTIONS"
    return {
        "completeness": "PARTIAL" if missing else "COMPLETE",
        "scenario": scenario,
        "executable": "UNVERIFIED",
        "known_movement_minutes": movement,
        "known_components_minutes": known,
        "available_minutes": available,
        "assumptions": assumptions,
        "unknown_legs": unknown,
        "missing_inputs": missing,
        "checked_scope": checked_scope,
        "meaning": "已知部分为地图估算与用户假设，非全程可靠下界；运营、预约和交通可用性未核实。",
    }
