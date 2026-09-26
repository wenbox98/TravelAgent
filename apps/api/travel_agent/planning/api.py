from typing import Any
from fastapi import FastAPI, Request
from travel_agent.preview.api import PreviewConfig, error
from travel_agent.providers.amap import AmapAdapter
from .models import MapAction, MapView
from .service import RoutePreviewService


def install_routes(app: FastAPI, config: PreviewConfig) -> None:
    service = RoutePreviewService(
        config.database, config.account_scope, config.mode, AmapAdapter.from_env()
    )
    app.state.route_preview = service

    @app.get("/api/v1/preview/routes/{session_id}", response_model=MapView)
    def read(session_id: str) -> Any:
        try:
            return service.get(session_id)
        except ValueError:
            return error("MAP_SCOPE_UNAVAILABLE", 409)

    @app.post("/api/v1/preview/routes", response_model=MapView)
    def change(body: MapAction, request: Request) -> Any:
        try:
            return service.mutate(body, request.headers.get("idempotency-key", ""))
        except ValueError as exc:
            allowed = {
                "STALE_REVISION",
                "IDEMPOTENCY_CONFLICT",
                "INVALID_INPUT",
                "MAP_INTEREST_REQUIRED",
                "MAP_GRANT_BINDING_CHANGED",
                "MAP_CANDIDATE_UNAVAILABLE",
                "MAP_OBJECT_TYPE_MISMATCH",
                "MAP_REGIONAL_REFERENCE_REQUIRED",
                "MAP_SEND_CONFIRMATION_REQUIRED",
                "MAP_PRIVATE_ADDRESS_CONFIRMATION_REQUIRED",
                "MAP_CONFIRM_PLACES_FIRST",
                "MAP_CHARTER_UNDECIDED",
                "CITYCODE_REQUIRED",
            }
            return error(str(exc) if str(exc) in allowed else "MAP_SCOPE_UNAVAILABLE", 409)
