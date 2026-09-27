from typing import Any
from fastapi import FastAPI, Request
from travel_agent.persistence.database import Database
from travel_agent.preview.api import PreviewConfig, error
from .flow import PlanningService, timeline
from .flow_models import PlanAction, PlanCreate, PlanIndex, PlanView, PlanDraft
from .suggestions import launch
from .flow_maps import FlowMapService, SyntheticMapAdapter, PrivateFlowMapService
from travel_agent.providers.amap import AmapAdapter
from .models import MapAction, MapView
from .workbench import STATUS_MESSAGES


def movement_references(draft: PlanDraft, legs: list[dict[str, Any]]) -> dict[str, float]:
    # Viewing driving references does not adopt self-driving/local transport.
    mode = {"SELF_DRIVE": "DRIVING", "PUBLIC_TRANSIT": "TRANSIT", "WALKING": "WALKING"}.get(
        draft.transport
    )
    return {
        leg["leg_id"]: leg["duration_seconds"] / 60
        for leg in legs
        if mode is not None
        and (leg["mode"] == mode or (draft.walking_allowed and leg["mode"] == "WALKING"))
        and not leg["stale"]
        and leg["status"] == "OK"
        and leg["duration_seconds"] is not None
    }


def install_flow(app: FastAPI, config: PreviewConfig) -> None:
    maps = FlowMapService(config.database, config.account_scope, config.mode, SyntheticMapAdapter())
    private_maps = PrivateFlowMapService(
        config.database, config.account_scope, config.mode, AmapAdapter.from_env()
    )
    app.state.flow_maps = maps
    app.state.private_flow_maps = private_maps

    def selected_maps(sid: str) -> FlowMapService:
        with Database(config.database) as db:
            _, state = PlanningService(db, config.account_scope).load(sid)
        return maps if state["planning"]["demo"] else private_maps

    def present(view: dict[str, Any]) -> dict[str, Any]:
        legs = selected_maps(view["session_id"]).get(view["session_id"])["legs"]
        draft = PlanDraft.model_validate(view["draft"])
        rows, gaps = timeline(draft, movement_references(draft, legs))
        view["timeline"] = rows
        view["gaps"] = list(dict.fromkeys(view["gaps"] + gaps))
        return view

    @app.get("/api/v1/preview/planning-maps/{session_id}", response_model=MapView)
    def read_maps(session_id: str) -> Any:
        return selected_maps(session_id).get(session_id)

    @app.post("/api/v1/preview/planning-maps", response_model=MapView)
    def change_maps(body: MapAction, request: Request) -> Any:
        try:
            return selected_maps(body.session_id).mutate(
                body, request.headers.get("idempotency-key", "")
            )
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
                    "MAP_ADOPT_ORDER_FIRST",
                }
                | STATUS_MESSAGES.keys()
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
                PlanningService(
                    db, config.account_scope, daily_workbench=config.daily_workbench
                ).create(body, request.headers.get("idempotency-key", ""))
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
            if (
                body.action == "research"
                and view["research_job"]
                and view["research_job"]["status"] == "QUEUED"
            ):
                launch(config.database, view["research_job"]["job_id"], research=True)
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
                | STATUS_MESSAGES.keys()
                else "CACHE_UNAVAILABLE"
            )
            return error(code, 409)
