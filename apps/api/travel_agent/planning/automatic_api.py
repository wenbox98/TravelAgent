"""Same-origin explicit intents; status reads are handled by the planning projection."""

from typing import Any
from fastapi import FastAPI, Request
from travel_agent.persistence.database import Database
from travel_agent.preview.api import PreviewConfig, error
from .automatic import AutomaticService
from .automatic_models import AutomaticAction, AutomaticStart
from .flow_models import PlanView
from .conversation import ConversationAction, action as conversation_action


def install_automatic(app: FastAPI, config: PreviewConfig, present: Any) -> None:
    def dispatch(view: Any) -> Any:
        if (view.get("answer_job") or {}).get("status") == "QUEUED":
            from .suggestions import launch

            launch(config.database, view["answer_job"]["job_id"], question=True)
        if (view.get("automatic_task") or {}).get("status") == "QUEUED":
            from .suggestions import launch

            launch(config.database, view["automatic_task"]["task_id"], automatic=True)
        return present(view)

    from .agent_map import AgentMapAction, AgentMapResult
    @app.post("/api/v1/preview/agent-map/{session_id}", response_model=AgentMapResult)
    def map_tool(session_id: str, body: AgentMapAction, request: Request) -> Any:
        from .agent_map import execute
        try:
            if not config.daily_workbench:
                raise ValueError("DAILY_TRIP_REQUIRED")
            return execute(app.state.private_flow_maps,session_id,body,
                           request.headers.get("idempotency-key",""))
        except ValueError as exc:
            return error(str(exc),409)

    @app.post("/api/v1/preview/conversation/{session_id}", response_model=PlanView)
    def converse(session_id: str, body: ConversationAction, request: Request) -> Any:
        try:
            if not config.daily_workbench:
                raise ValueError("DAILY_TRIP_REQUIRED")
            with Database(config.database) as db:
                view = conversation_action(
                    db,
                    config.account_scope,
                    session_id,
                    body,
                    request.headers.get("idempotency-key", ""),
                )
            return dispatch(view)
        except ValueError as exc:
            return error(str(exc), 409)

    @app.post("/api/v1/preview/automatic-planning", response_model=PlanView)
    def start(body: AutomaticStart, request: Request) -> Any:
        try:
            if not config.daily_workbench:
                raise ValueError("DAILY_TRIP_REQUIRED")
            with Database(config.database) as db:
                view = AutomaticService(db, config.account_scope).start(
                    body, request.headers.get("idempotency-key", "")
                )
            return dispatch(view)
        except ValueError as exc:
            return error(str(exc), 409)

    @app.post("/api/v1/preview/automatic-planning/{session_id}", response_model=PlanView)
    def action(session_id: str, body: AutomaticAction, request: Request) -> Any:
        try:
            if not config.daily_workbench:
                raise ValueError("DAILY_TRIP_REQUIRED")
            with Database(config.database) as db:
                view = AutomaticService(db, config.account_scope).action(
                    session_id, body, request.headers.get("idempotency-key", "")
                )
            return dispatch(view)
        except ValueError as exc:
            return error(str(exc), 409)
