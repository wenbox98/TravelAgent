from typing import Any
from fastapi import FastAPI, Request
from travel_agent.persistence.database import Database
from travel_agent.preview.api import PreviewConfig, error
from .flow import PlanningService, timeline
from .flow_models import PlanAction, PlanCreate, PlanIndex, PlanView, PlanDraft
from .suggestions import launch
from .flow_maps import FlowMapService, SyntheticMapAdapter
from .models import MapAction, MapView


def movement_references(draft: PlanDraft, legs: list[dict[str, Any]]) -> dict[str, float]:
    # Viewing driving references does not adopt self-driving/local transport.
    mode = {"SELF_DRIVE": "DRIVING", "PUBLIC_TRANSIT": "TRANSIT", "WALKING": "WALKING"}.get(
        draft.transport
    )
    return {
        leg["leg_id"]: leg["duration_seconds"] / 60
        for leg in legs
        if mode is not None
        and leg["mode"] == mode
        and not leg["stale"]
        and leg["status"] == "OK"
        and leg["duration_seconds"] is not None
    }


def install_flow(app: FastAPI, config: PreviewConfig) -> None:
    maps = FlowMapService(config.database, config.account_scope, config.mode, SyntheticMapAdapter())
    app.state.flow_maps = maps

    def present(view: dict[str, Any]) -> dict[str, Any]:
        legs = maps.get(view["session_id"])["legs"]
        draft = PlanDraft.model_validate(view["draft"])
        rows, gaps = timeline(draft, movement_references(draft, legs))
        view["timeline"] = rows
        view["gaps"] = list(dict.fromkeys(view["gaps"] + gaps))
        return view

    @app.get("/api/v1/preview/planning-maps/{session_id}", response_model=MapView)
    def read_maps(session_id: str) -> Any:
        return maps.get(session_id)

    @app.post("/api/v1/preview/planning-maps", response_model=MapView)
    def change_maps(body: MapAction, request: Request) -> Any:
        try:
            return maps.mutate(body, request.headers.get("idempotency-key", ""))
        except ValueError as exc:
            return error(
                str(exc)
                if str(exc)
                in {
                    "STALE_REVISION",
                    "MAP_MODE_REQUIRED",
                    "MAP_CONFIRM_PLACES_FIRST",
                    "MAP_OBJECT_TYPE_MISMATCH",
                    "MAP_REGIONAL_REFERENCE_REQUIRED",
                }
                else "INVALID_INPUT",
                409,
            )

    @app.get("/api/v1/preview/planning", response_model=PlanIndex)
    def index() -> Any:
        with Database(config.database) as db:
            value = PlanningService(db, config.account_scope).index()
            if value["current"]:
                value["current"] = present(value["current"])
            return value

    @app.post("/api/v1/preview/planning", response_model=PlanView)
    def create(body: PlanCreate, request: Request) -> Any:
        with Database(config.database) as db:
            return present(
                PlanningService(db, config.account_scope).create(
                    body, request.headers.get("idempotency-key", "")
                )
            )

    @app.get("/api/v1/preview/planning/{session_id}", response_model=PlanView)
    def read(session_id: str) -> Any:
        with Database(config.database) as db:
            return present(PlanningService(db, config.account_scope).get(session_id))

    @app.post("/api/v1/preview/planning/{session_id}", response_model=PlanView)
    def change(session_id: str, body: PlanAction, request: Request) -> Any:
        try:
            with Database(config.database) as db:
                view = PlanningService(db, config.account_scope).mutate(
                    session_id, body, request.headers.get("idempotency-key", "")
                )
            if body.action == "suggest" and view["job"] and view["job"]["status"] == "QUEUED":
                # Worker acquires QUEUED exactly once, including repeated HTTP keys.
                launch(config.database, view["job"]["job_id"])
            return present(view)
        except ValueError as exc:
            code = (
                str(exc)
                if str(exc)
                in {
                    "STALE_REVISION",
                    "STALE_PROPOSAL",
                    "PLANNING_UNAVAILABLE",
                    "INVALID_INPUT",
                    "OPTION_UNAVAILABLE",
                    "IDEMPOTENCY_CONFLICT",
                }
                else "CACHE_UNAVAILABLE"
            )
            return error(code, 409)
